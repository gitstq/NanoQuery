"""数据源适配层：把各类本地文件读成 :class:`~nanoquery.batch.Batch` 流。

NanoQuery 的核心卖点是**不启动任何数据库服务、不导入数据**，直接对躺在磁盘上的
文件执行 SQL。本模块就是这条能力链的入口，目前内置四类数据源：

============  ==============================  =====================================
格式          扩展名                          说明
============  ==============================  =====================================
CSV / TSV     ``.csv`` ``.tsv`` ``.txt``      自动嗅探分隔符，自动做类型推断
JSON Lines    ``.jsonl`` ``.ndjson``          每行一个 JSON 对象，自动展平嵌套
文本日志      ``.log``                        默认整行为 ``line`` 列，可用正则抽字段
NanoQuery     ``.nq``                        自研列存格式，读取速度最快
============  ==============================  =====================================
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from typing import Any, Dict, Iterator, List, Optional, Sequence

from .batch import Batch, batch_from_rows
from .types import StorageError

__all__ = [
    "Source", "CsvSource", "JsonlSource", "LogSource", "NqSource", "MemorySource",
    "open_source", "source_for_path", "infer_value", "FORMATS",
]

FORMATS = ("csv", "tsv", "jsonl", "ndjson", "json", "log", "nq")

_EXT_TO_FORMAT = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".txt": "csv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".json": "json",
    ".log": "log",
    ".nq": "nq",
}


# --------------------------------------------------------------------------- #
# 值推断
# --------------------------------------------------------------------------- #

_NULL_LITERALS = frozenset({"", "null", "none", "nil", "nan", "na", "\\n"})
_TRUE_LITERALS = frozenset({"true", "t", "yes", "y", "on"})
_FALSE_LITERALS = frozenset({"false", "f", "no", "n", "off"})


def infer_value(text: str) -> Any:
    """把字符串解析为 ``None`` / ``bool`` / ``int`` / ``float`` / ``str``。

    这是 CSV 类数据源"开箱即用"的关键：无需预先声明 schema 即可做数值比较与聚合。
    """
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if stripped.lower() in _NULL_LITERALS:
        return None
    lowered = stripped.lower()
    if lowered in _TRUE_LITERALS:
        return True
    if lowered in _FALSE_LITERALS:
        return False
    # 整数（允许前导 + / -）
    if re.fullmatch(r"[+-]?\d+", stripped):
        try:
            return int(stripped)
        except ValueError:
            return text
    # 浮点 / 科学计数法
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", stripped):
        try:
            return float(stripped)
        except ValueError:
            return text
    return text


# --------------------------------------------------------------------------- #
# Source 抽象
# --------------------------------------------------------------------------- #


class Source:
    """数据源基类。子类需实现 :meth:`schema` 与 :meth:`batches`。"""

    kind = "abstract"

    def __init__(self, path: str, batch_size: int = 4096, infer_types: bool = True) -> None:
        self.path = path
        self.batch_size = batch_size
        self.infer_types = infer_types

    @property
    def name(self) -> str:
        """默认表名：去掉目录与扩展名的文件名。"""
        base = os.path.basename(self.path)
        stem, _ = os.path.splitext(base)
        return _sanitize_identifier(stem or "data")

    def schema(self) -> List[Dict[str, str]]:
        """返回列信息列表 ``[{"name": ..., "type": ...}, ...]``。"""
        raise NotImplementedError

    def batches(self) -> Iterator[Batch]:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - 调试用途
        return f"<{self.__class__.__name__} path={self.path!r}>"


class MemorySource(Source):
    """内存数据源：直接把 Python 数据（Batch / 行字典）当作一张表。

    这是 NanoQuery 作为**嵌入式库**使用的关键入口——数据不必先落盘成文件。

    用法::

        MemorySource(Batch({"name": ["alice"], "age": [31]}))
        MemorySource([{"name": "alice", "age": 31}, ...])
    """

    kind = "memory"

    def __init__(
        self,
        data,
        name: str = "memory",
        batch_size: int = 4096,
        columns: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(f"memory:{name}", batch_size=batch_size)
        if isinstance(data, Batch):
            self._batches = [data] if data.row_count else []
        else:
            rows = list(data)
            self._batches = [batch_from_rows(rows, columns)] if rows else []
        self._columns = columns

    @property
    def name(self) -> str:
        return _sanitize_identifier(str(self.path).split(":", 1)[-1] or "memory")

    def schema(self) -> List[Dict[str, str]]:
        if not self._batches:
            return []
        types = self._batches[0].infer_types()
        return [{"name": n, "type": t} for n, t in types.items()]

    def batches(self) -> Iterator[Batch]:
        yield from self._batches

    def __repr__(self) -> str:  # pragma: no cover - 调试用途
        rows = sum(b.row_count for b in self._batches)
        return f"<MemorySource rows={rows}>"


def _sanitize_identifier(name: str) -> str:
    """把文件名规整为合法 SQL 标识符。"""
    cleaned = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]", "_", name)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or "data"


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #


class CsvSource(Source):
    """CSV / TSV 数据源。"""

    kind = "csv"

    def __init__(
        self,
        path: str,
        batch_size: int = 4096,
        infer_types: bool = True,
        delimiter: Optional[str] = None,
        has_header: bool = True,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(path, batch_size, infer_types)
        self.delimiter = delimiter
        self.has_header = has_header
        self.encoding = encoding

    def _detect_delimiter(self, sample: str) -> str:
        if self.delimiter:
            return self.delimiter
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    def _open(self):
        return io.open(self.path, "r", encoding=self.encoding, newline="", errors="replace")

    def _header(self) -> List[str]:
        with self._open() as handle:
            sample = handle.read(64 * 1024)
        if not sample.strip():
            return []
        delimiter = self._detect_delimiter(sample)
        reader = csv.reader(io.StringIO(sample.splitlines()[0]), delimiter=delimiter)
        first = next(reader, [])
        if self.has_header:
            seen: Dict[str, int] = {}
            names = []
            for raw in first:
                name = _sanitize_identifier(raw.strip() or "col")
                if name in seen:
                    seen[name] += 1
                    name = f"{name}_{seen[name]}"
                else:
                    seen[name] = 0
                names.append(name)
            return names
        return [f"c{i}" for i in range(len(first))]

    def schema(self) -> List[Dict[str, str]]:
        from .types import infer_type  # 局部导入避免循环

        names = self._header()
        if not names:
            return []
        # 采样前若干行推断类型
        samples: Dict[str, List[Any]] = {n: [] for n in names}
        with self._open() as handle:
            sample = handle.read(64 * 1024)
            delimiter = self._detect_delimiter(sample)
            rows = list(csv.reader(io.StringIO(sample), delimiter=delimiter))
        start = 1 if self.has_header else 0
        for row in rows[start : start + 200]:
            for i, name in enumerate(names):
                samples[name].append(infer_value(row[i]) if i < len(row) else None)
        return [{"name": n, "type": infer_type(samples[n])} for n in names]

    def batches(self) -> Iterator[Batch]:
        with self._open() as handle:
            sample = handle.read(64 * 1024)
            handle.seek(0)
            delimiter = self._detect_delimiter(sample)
            reader = csv.reader(handle, delimiter=delimiter)
            header = self._header()
            ncols = len(header)
            if self.has_header:
                try:
                    next(reader)
                except StopIteration:
                    return

            chunk: List[List[Any]] = []
            for row in reader:
                if not row or (len(row) == 1 and row[0].strip() == ""):
                    continue
                if len(row) < ncols:
                    row = row + [None] * (ncols - len(row))
                elif len(row) > ncols:
                    row = row[:ncols]
                chunk.append([infer_value(v) if self.infer_types else v for v in row])
                if len(chunk) >= self.batch_size:
                    yield batch_from_rows([dict(zip(header, r)) for r in chunk], header)
                    chunk = []
            if chunk:
                yield batch_from_rows([dict(zip(header, r)) for r in chunk], header)


# --------------------------------------------------------------------------- #
# JSON Lines
# --------------------------------------------------------------------------- #


class JsonlSource(Source):
    """JSON Lines / NDJSON / JSON 数组数据源，自动展平一层嵌套对象。"""

    kind = "jsonl"

    @staticmethod
    def _flatten(obj: Any) -> Dict[str, Any]:
        if not isinstance(obj, dict):
            return {"value": obj}
        flat: Dict[str, Any] = {}
        for key, value in obj.items():
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    flat[f"{key}.{sub_key}"] = sub_value
            else:
                flat[key] = value
        return flat

    def schema(self) -> List[Dict[str, str]]:
        from .types import infer_type

        names: List[str] = []
        samples: Dict[str, List[Any]] = {}
        count = 0
        for batch in self.batches():
            for name in batch.column_names:
                if name not in samples:
                    samples[name] = []
                    names.append(name)
                samples[name].extend(batch.columns[name][:50])
            count += 1
            if count >= 1:
                break
        return [{"name": n, "type": infer_type(samples.get(n, []))} for n in names]

    def batches(self) -> Iterator[Batch]:
        with io.open(self.path, "r", encoding="utf-8", errors="replace") as handle:
            first = handle.read(1)
            handle.seek(0)
            if first == "[":
                yield from self._read_array(handle)
                return

            chunk: List[Dict[str, Any]] = []
            for line in handle:
                line = line.strip().rstrip(",")
                if not line or line in ("[", "]"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk.append(self._flatten(obj))
                if len(chunk) >= self.batch_size:
                    yield self._to_batch(chunk)
                    chunk = []
            if chunk:
                yield self._to_batch(chunk)

    def _read_array(self, handle) -> Iterator[Batch]:
        text = handle.read()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StorageError(f"JSON 解析失败 {self.path}: {exc}")
        if not isinstance(data, list):
            data = [data]
        rows = [self._flatten(obj) for obj in data]
        for start in range(0, len(rows), self.batch_size):
            yield self._to_batch(rows[start : start + self.batch_size])

    @staticmethod
    def _to_batch(rows: List[Dict[str, Any]]) -> Batch:
        columns: List[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        return batch_from_rows(rows, columns)


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #


class LogSource(Source):
    """纯文本日志数据源。

    未提供正则时，整行作为 ``line`` 列，并额外产出 ``lineno`` 与 ``length`` 两个
    派生列；提供命名分组正则时，每个分组成为一列，未匹配的行落到 ``line`` 列。
    """

    kind = "log"

    def __init__(
        self,
        path: str,
        batch_size: int = 4096,
        infer_types: bool = True,
        pattern: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(path, batch_size, infer_types)
        self.pattern = pattern
        self._regex = re.compile(pattern) if pattern else None
        self.encoding = encoding

    def _columns(self) -> List[str]:
        if self._regex:
            names = [n or f"g{i}" for i, n in enumerate(self._regex.groupindex, start=1)]
            return ["lineno"] + names + ["line"]
        return ["lineno", "line", "length"]

    def schema(self) -> List[Dict[str, str]]:
        return [{"name": n, "type": "STR"} for n in self._columns()]

    def batches(self) -> Iterator[Batch]:
        chunk: List[Dict[str, Any]] = []
        with io.open(self.path, "r", encoding=self.encoding, errors="replace") as handle:
            for lineno, raw in enumerate(handle, start=1):
                line = raw.rstrip("\n").rstrip("\r")
                if self._regex:
                    match = self._regex.search(line)
                    if match:
                        row: Dict[str, Any] = {"lineno": lineno}
                        for i, name in enumerate(self._regex.groupindex, start=1):
                            value = match.group(name)
                            row[name] = infer_value(value) if self.infer_types and value is not None else value
                        row["line"] = line
                    else:
                        row = {"lineno": lineno, "line": line}
                        for name in self._regex.groupindex:
                            row[name] = None
                else:
                    row = {"lineno": lineno, "line": line, "length": len(line)}
                chunk.append(row)
                if len(chunk) >= self.batch_size:
                    yield batch_from_rows(chunk, self._columns())
                    chunk = []
        if chunk:
            yield batch_from_rows(chunk, self._columns())


# --------------------------------------------------------------------------- #
# 列存
# --------------------------------------------------------------------------- #


class NqSource(Source):
    """NanoQuery 自研列存格式（``.nq``）数据源。"""

    kind = "nq"

    def schema(self) -> List[Dict[str, str]]:
        from .storage import read_header

        header = read_header(self.path)
        return [{"name": c["name"], "type": c["type"]} for c in header["columns"]]

    def batches(self) -> Iterator[Batch]:
        from .storage import read_batches

        yield from read_batches(self.path)


# --------------------------------------------------------------------------- #
# 工厂
# --------------------------------------------------------------------------- #


def detect_format(path: str, fmt: Optional[str] = None) -> str:
    if fmt:
        fmt = fmt.lower().lstrip(".")
        if fmt in FORMATS:
            return fmt
        raise StorageError(f"不支持的数据格式：{fmt}")
    _, ext = os.path.splitext(path)
    return _EXT_TO_FORMAT.get(ext.lower(), "csv")


def source_for_path(
    path: str,
    fmt: Optional[str] = None,
    batch_size: int = 4096,
    infer_types: bool = True,
    delimiter: Optional[str] = None,
    has_header: bool = True,
    log_pattern: Optional[str] = None,
    encoding: str = "utf-8",
) -> Source:
    """根据路径或显式格式构造对应的 :class:`Source` 实例。"""
    if not os.path.exists(path):
        raise StorageError(f"数据文件不存在：{path}")
    kind = detect_format(path, fmt)
    if kind in ("csv", "tsv"):
        return CsvSource(
            path,
            batch_size=batch_size,
            infer_types=infer_types,
            delimiter=delimiter or ("," if kind == "csv" else "\t"),
            has_header=has_header,
            encoding=encoding,
        )
    if kind in ("jsonl", "json"):
        return JsonlSource(path, batch_size=batch_size, infer_types=infer_types)
    if kind == "log":
        return LogSource(path, batch_size=batch_size, infer_types=infer_types, pattern=log_pattern, encoding=encoding)
    if kind == "nq":
        return NqSource(path, batch_size=batch_size, infer_types=infer_types)
    raise StorageError(f"不支持的数据格式：{kind}")


def open_source(path: str, **kwargs) -> Source:  # 兼容别名
    return source_for_path(path, **kwargs)
