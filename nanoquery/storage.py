"""NanoQuery 自研列式存储格式（``.nq``）。

设计目标
--------
1. **零依赖**：仅使用标准库 ``struct`` / ``json`` / ``zlib`` 即可读写。
2. **列式布局**：同一列的数据物理相邻，聚合查询只需读取涉及的列。
3. **轻量压缩**：按列自动在 RAW / 字典编码 / 游程编码之间择优，
   在不牺牲解码速度的前提下显著缩小体积。
4. **自描述**：文件头以 JSON 保存 schema，任何语言都能解析。

文件布局（全部小端序）::

    +---------------------------+
    | magic  "NQ01"      4B     |
    | version            1B     |
    | flags              1B     |
    | reserved           2B     |
    | header_len         4B     |
    | header JSON   header_len  |  {"row_count":N,"columns":[...],...}
    +---------------------------+
    | column chunk 0            |
    |   name_len   2B           |
    |   name       name_len     |
    |   type_code  1B           |
    |   encoding   1B           |
    |   payload_len 4B          |
    |   payload    payload_len  |
    +---------------------------+
    | column chunk 1 ...        |
    +---------------------------+

每个列的 payload 结构为：``null bitmap (ceil(N/8) 字节)`` + 值区。
"""

from __future__ import annotations

import json
import struct
import time
import zlib
from typing import Any, Dict, Iterator, List, Sequence, Tuple

from .batch import Batch
from .types import (
    TYPE_BOOL, TYPE_FLOAT, TYPE_INT, TYPE_NULL, TYPE_STR, StorageError, infer_type,
)

__all__ = [
    "MAGIC", "VERSION", "write_nq", "read_header", "read_batches", "read_column",
    "Encoding", "choose_encoding",
]

MAGIC = b"NQ01"
VERSION = 1

# 类型码
_TYPE_CODE = {TYPE_NULL: 0, TYPE_BOOL: 1, TYPE_INT: 2, TYPE_FLOAT: 3, TYPE_STR: 4}
_CODE_TYPE = {v: k for k, v in _TYPE_CODE.items()}

# 压缩标志（flags 位）
_FLAG_ZLIB = 0x01


class Encoding:
    """列编码方式常量。"""

    RAW = 0
    DICT = 1
    RLE = 2

    NAMES = {RAW: "RAW", DICT: "DICT", RLE: "RLE"}


# --------------------------------------------------------------------------- #
# 编码选择
# --------------------------------------------------------------------------- #


def choose_encoding(values: Sequence[Any]) -> int:
    """根据列的取值分布启发式选择编码方式。

    策略：
        * 平均游程长度 >= 4  -> RLE（适合枚举、状态码、日志级别）
        * 唯一值比例 <= 0.4 且唯一值数量 <= 65535 -> DICT（适合城市、类别）
        * 其余 -> RAW
    """
    n = len(values)
    if n == 0:
        return Encoding.RAW

    # 游程统计（限制采样规模，避免大列拖慢导入）
    step = 1 if n <= 20000 else max(1, n // 20000)
    sample = values[::step]
    runs = 1
    for i in range(1, len(sample)):
        if sample[i] != sample[i - 1]:
            runs += 1
    avg_run = len(sample) / max(1, runs)
    if avg_run >= 4:
        return Encoding.RLE

    if step == 1:
        unique = len(set(values))
    else:
        unique = len(set(sample))
    if unique <= 65535 and unique / n <= 0.4:
        return Encoding.DICT
    return Encoding.RAW


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #


def _bitmap(values: Sequence[Any]) -> bytearray:
    """生成 NULL 位图：1 表示该位置为 NULL。"""
    out = bytearray((len(values) + 7) // 8)
    for i, value in enumerate(values):
        if value is None:
            out[i >> 3] |= 1 << (i & 7)
    return out


def _encode_values(values: Sequence[Any], col_type: str, encoding: int, compress: bool) -> bytes:
    bitmap = bytes(_bitmap(values))
    body = _encode_body(values, col_type, encoding)
    payload = bitmap + body
    if compress and len(payload) > 512:
        return b"\x01" + zlib.compress(payload, 6)
    return b"\x00" + payload


def _encode_body(values: Sequence[Any], col_type: str, encoding: int) -> bytes:
    if col_type == TYPE_NULL:
        return b""

    if encoding == Encoding.RLE:
        return _encode_rle(values, col_type)

    if encoding == Encoding.DICT:
        return _encode_dict(values, col_type)

    return _encode_raw(values, col_type)


def _encode_raw(values: Sequence[Any], col_type: str) -> bytes:
    if col_type == TYPE_BOOL:
        return bytes(1 if (v is True) else 0 for v in values)
    if col_type == TYPE_INT:
        out = bytearray()
        chunk = 8192
        for start in range(0, len(values), chunk):
            part = [0 if v is None else int(v) for v in values[start : start + chunk]]
            out += struct.pack(f"<{len(part)}q", *part)
        return bytes(out)
    if col_type == TYPE_FLOAT:
        out = bytearray()
        chunk = 8192
        for start in range(0, len(values), chunk):
            part = [0.0 if v is None else float(v) for v in values[start : start + chunk]]
            out += struct.pack(f"<{len(part)}d", *part)
        return bytes(out)
    # STR
    out = bytearray()
    for value in values:
        if value is None:
            out += struct.pack("<I", 0)
            continue
        raw = value.encode("utf-8") if isinstance(value, str) else str(value).encode("utf-8")
        out += struct.pack("<I", len(raw)) + raw
    return bytes(out)


def _encode_dict(values: Sequence[Any], col_type: str) -> bytes:
    mapping: Dict[Any, int] = {}
    order: List[Any] = []
    for value in values:
        if value is None:
            continue
        if value not in mapping:
            mapping[value] = len(order)
            order.append(value)
    if len(order) > 65535:  # 兜底：退化成 RAW
        return b"\x00" + _encode_raw(values, col_type)

    table = bytearray()
    table += struct.pack("<I", len(order))
    for item in order:
        raw = item.encode("utf-8") if isinstance(item, str) else str(item).encode("utf-8")
        table += struct.pack("<I", len(raw)) + raw
    # 索引：0 表示 NULL，实际值下标 +1
    idx = [0 if v is None else mapping[v] + 1 for v in values]
    fmt = "<H" if len(order) < 65535 else "<I"
    body = bytearray(struct.pack("<B", 2 if fmt == "<H" else 4))
    chunk = 8192
    for start in range(0, len(idx), chunk):
        part = idx[start : start + chunk]
        body += struct.pack(f"{fmt[0]}{len(part)}{fmt[1]}", *part)
    return b"\x01" + bytes(table) + bytes(body)


def _encode_rle(values: Sequence[Any], col_type: str) -> bytes:
    """游程编码：``runs(uint32)`` + 每个游程 ``count(uint32) + value``。"""
    runs: List[Tuple[int, Any]] = []
    prev = object()
    count = 0
    for value in values:
        if value == prev:
            count += 1
        else:
            if count:
                runs.append((count, prev))
            prev = value
            count = 1
    if count:
        runs.append((count, prev))

    out = bytearray(struct.pack("<I", len(runs)))
    for count, value in runs:
        out += struct.pack("<I", count)
        if value is None:
            out += b"\x00"
            continue
        out += b"\x01"
        if col_type == TYPE_INT:
            out += struct.pack("<q", int(value))
        elif col_type == TYPE_FLOAT:
            out += struct.pack("<d", float(value))
        elif col_type == TYPE_BOOL:
            out += struct.pack("<B", 1 if value else 0)
        else:
            raw = value.encode("utf-8") if isinstance(value, str) else str(value).encode("utf-8")
            out += struct.pack("<I", len(raw)) + raw
    return b"\x02" + bytes(out)


def write_nq(
    path: str,
    batches: Iterator[Batch] | Sequence[Batch],
    column_order: Sequence[str] | None = None,
    compress: bool = True,
    source: str | None = None,
) -> Dict[str, Any]:
    """把 Batch 流写入 ``.nq`` 列存文件，返回写入统计信息。

    Args:
        path: 目标文件路径。
        batches: 输入批序列，所有批的列名需一致。
        column_order: 可选的列顺序；缺省取首批的列顺序。
        compress: 是否对列载荷启用 zlib 压缩。
        source: 原始数据来源描述，写入文件头便于溯源。

    Returns:
        包含 ``path``/``row_count``/``columns``/``bytes`` 的统计字典。
    """
    materialized: Dict[str, List[Any]] = {}
    names: List[str] = list(column_order) if column_order else []
    row_count = 0

    for batch in batches:
        if not names:
            names = batch.column_names
        for name in names:
            if name not in materialized:
                materialized[name] = []
            materialized[name].extend(batch.columns.get(name, [None] * batch.row_count))
        row_count += batch.row_count

    if not names:
        raise StorageError("没有可写入的列")

    columns_meta = []
    payloads: List[bytes] = []
    for name in names:
        values = materialized[name]
        col_type = infer_type(values)
        encoding = choose_encoding(values)
        if col_type == TYPE_NULL:
            encoding = Encoding.RAW
        payloads.append(_encode_values(values, col_type, encoding, compress))
        columns_meta.append(
            {"name": name, "type": col_type, "encoding": Encoding.NAMES[encoding]}
        )

    header = {
        "format": "nanoquery-columnar",
        "version": VERSION,
        "row_count": row_count,
        "columns": columns_meta,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source or "",
    }
    header_bytes = json.dumps(header, ensure_ascii=False).encode("utf-8")

    with open(path, "wb") as handle:
        flags = _FLAG_ZLIB if compress else 0
        handle.write(MAGIC + struct.pack("<BBHI", VERSION, flags, 0, len(header_bytes)))
        handle.write(header_bytes)
        for name, meta, payload in zip(names, columns_meta, payloads):
            raw_name = name.encode("utf-8")
            handle.write(struct.pack("<H", len(raw_name)) + raw_name)
            handle.write(struct.pack("<BB", _TYPE_CODE[meta["type"]], Encoding.RAW if meta["encoding"] == "RAW" else (Encoding.DICT if meta["encoding"] == "DICT" else Encoding.RLE)))
            handle.write(struct.pack("<I", len(payload)))
            handle.write(payload)

    import os

    return {
        "path": path,
        "row_count": row_count,
        "columns": columns_meta,
        "bytes": os.path.getsize(path),
    }


# --------------------------------------------------------------------------- #
# 读取
# --------------------------------------------------------------------------- #


def _open(path: str):
    try:
        handle = open(path, "rb")
    except OSError as exc:
        raise StorageError(f"无法打开列存文件 {path}: {exc}")
    with handle:
        blob = handle.read()
    if not blob.startswith(MAGIC):
        raise StorageError(f"{path} 不是有效的 NanoQuery 列存文件")
    version, flags, _reserved, header_len = struct.unpack("<BBHI", blob[4:12])
    if version != VERSION:
        raise StorageError(f"列存版本不匹配：文件 {version}，当前支持 {VERSION}")
    header = json.loads(blob[12 : 12 + header_len].decode("utf-8"))
    return header, blob[12 + header_len :], flags


def read_header(path: str) -> Dict[str, Any]:
    """读取 ``.nq`` 文件头（含 schema），不加载数据。"""
    header, _body, _flags = _open(path)
    return header


def _read_payload(body: bytes, offset: int) -> Tuple[str, str, int, bytes, int]:
    (name_len,) = struct.unpack_from("<H", body, offset)
    offset += 2
    name = body[offset : offset + name_len].decode("utf-8")
    offset += name_len
    type_code, encoding = struct.unpack_from("<BB", body, offset)
    offset += 2
    (payload_len,) = struct.unpack_from("<I", body, offset)
    offset += 4
    payload = body[offset : offset + payload_len]
    offset += payload_len
    return name, _CODE_TYPE[type_code], encoding, payload, offset


def _decode_payload(payload: bytes, col_type: str, encoding: int, row_count: int) -> List[Any]:
    if not payload:
        return [None] * row_count
    compressed = payload[0] == 1
    data = zlib.decompress(payload[1:]) if compressed else payload[1:]
    bitmap_len = (row_count + 7) // 8
    bitmap = data[:bitmap_len]
    body = data[bitmap_len:]

    values = _decode_body(body, col_type, encoding, row_count)
    out = []
    for i in range(row_count):
        if i < len(values):
            out.append(None if (bitmap[i >> 3] >> (i & 7)) & 1 else values[i])
        else:
            out.append(None)
    return out


def _decode_body(body: bytes, col_type: str, encoding: int, row_count: int) -> List[Any]:
    if col_type == TYPE_NULL:
        return [None] * row_count
    if encoding == Encoding.RLE:
        return _decode_rle(body, col_type)
    if encoding == Encoding.DICT:
        return _decode_dict(body)
    return _decode_raw(body, col_type, row_count)


def _decode_raw(body: bytes, col_type: str, row_count: int) -> List[Any]:
    offset = 0
    values: List[Any] = []
    if col_type == TYPE_BOOL:
        return [bool(b) for b in body[:row_count]]
    if col_type == TYPE_INT:
        for start in range(0, row_count, 8192):
            count = min(8192, row_count - start)
            values.extend(struct.unpack_from(f"<{count}q", body, offset))
            offset += count * 8
        return values
    if col_type == TYPE_FLOAT:
        for start in range(0, row_count, 8192):
            count = min(8192, row_count - start)
            values.extend(struct.unpack_from(f"<{count}d", body, offset))
            offset += count * 8
        return values
    for _ in range(row_count):
        (length,) = struct.unpack_from("<I", body, offset)
        offset += 4
        values.append(body[offset : offset + length].decode("utf-8") if length else "")
        offset += length
    return values


def _decode_dict(body: bytes) -> List[Any]:
    if not body or body[0] != 1:
        raise StorageError("字典编码载荷损坏")
    offset = 1
    (dict_size,) = struct.unpack_from("<I", body, offset)
    offset += 4
    table: List[str] = []
    for _ in range(dict_size):
        (length,) = struct.unpack_from("<I", body, offset)
        offset += 4
        table.append(body[offset : offset + length].decode("utf-8"))
        offset += length
    width = body[offset]
    offset += 1
    fmt = "<H" if width == 2 else "<I"
    step = 2 if width == 2 else 4
    remaining = (len(body) - offset) // step
    values: List[Any] = []
    for start in range(0, remaining, 8192):
        count = min(8192, remaining - start)
        for idx in struct.unpack_from(f"{fmt[0]}{count}{fmt[1]}", body, offset):
            values.append(table[idx - 1] if idx else "")
        offset += count * step
    return values


def _decode_rle(body: bytes, col_type: str) -> List[Any]:
    if not body or body[0] != 2:
        raise StorageError("游程编码载荷损坏")
    offset = 1
    (runs,) = struct.unpack_from("<I", body, offset)
    offset += 4
    values: List[Any] = []
    for _ in range(runs):
        (count,) = struct.unpack_from("<I", body, offset)
        offset += 4
        flag = body[offset]
        offset += 1
        if flag == 0:
            values.extend([None] * count)
            continue
        if col_type == TYPE_INT:
            (value,) = struct.unpack_from("<q", body, offset)
            offset += 8
        elif col_type == TYPE_FLOAT:
            (value,) = struct.unpack_from("<d", body, offset)
            offset += 8
        elif col_type == TYPE_BOOL:
            value = bool(body[offset])
            offset += 1
        else:
            (length,) = struct.unpack_from("<I", body, offset)
            offset += 4
            value = body[offset : offset + length].decode("utf-8")
            offset += length
        values.extend([value] * count)
    return values


def read_column(path: str, column: str) -> List[Any]:
    """只读取单列数据——列存格式的核心优势。"""
    header, body, _flags = _open(path)
    row_count = header["row_count"]
    offset = 0
    for _ in header["columns"]:
        name, col_type, encoding, payload, offset = _read_payload(body, offset)
        if name == column:
            return _decode_payload(payload, col_type, encoding, row_count)
    raise StorageError(f"列不存在：{column}")


def read_batches(path: str, batch_size: int = 4096, columns: Sequence[str] | None = None) -> Iterator[Batch]:
    """把 ``.nq`` 文件解码为 Batch 流。"""
    header, body, _flags = _open(path)
    row_count = header["row_count"]
    if row_count == 0:
        return

    wanted = set(columns) if columns else None
    data: Dict[str, List[Any]] = {}
    order: List[str] = []
    offset = 0
    for _ in header["columns"]:
        name, col_type, encoding, payload, offset = _read_payload(body, offset)
        if wanted is not None and name not in wanted:
            continue
        data[name] = _decode_payload(payload, col_type, encoding, row_count)
        order.append(name)

    for start in range(0, row_count, batch_size):
        stop = min(start + batch_size, row_count)
        yield Batch({name: data[name][start:stop] for name in order}, stop - start)
