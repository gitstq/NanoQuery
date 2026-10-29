"""列式数据批（Batch）——NanoQuery 向量化执行的基本单元。

一个 :class:`Batch` 就是一个 ``{列名: 列数组}`` 的映射，同一 Batch 内所有列长度相同。
执行引擎的所有算子都以 Batch 为输入与输出，这种"一次处理一批"的方式：

* 让标量函数的 Python 调用开销被摊薄到整列上；
* 使过滤、聚合等操作可以使用列表推导等高效原语；
* 天然支持超过内存容量的数据（配合迭代式扫描分批处理）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Sequence

from .types import infer_type

__all__ = ["Batch", "DEFAULT_BATCH_SIZE", "batch_from_rows", "concat_batches"]

#: 默认批大小（行数）。可通过 CLI 的 ``--batch-size`` 调整。
DEFAULT_BATCH_SIZE = 4096


class Batch:
    """一批列式数据。

    Args:
        columns: 列名到列数组的映射，所有数组长度必须一致。
        row_count: 行数。为空时自动取第一列长度。
    """

    __slots__ = ("columns", "row_count")

    def __init__(self, columns: Optional[Dict[str, List[Any]]] = None, row_count: Optional[int] = None):
        self.columns: Dict[str, List[Any]] = columns or {}
        if row_count is not None:
            self.row_count = row_count
        elif self.columns:
            self.row_count = len(next(iter(self.columns.values())))
        else:
            self.row_count = 0

    # ------------------------------------------------------------------ #
    # 基本操作
    # ------------------------------------------------------------------ #

    @property
    def column_names(self) -> List[str]:
        return list(self.columns.keys())

    def column(self, name: str) -> List[Any]:
        """取列数组；列名不存在时抛出 ``KeyError`` 风格的异常。"""
        try:
            return self.columns[name]
        except KeyError:
            raise KeyError(name) from None

    def has(self, name: str) -> bool:
        return name in self.columns

    def add(self, name: str, values: Sequence[Any]) -> None:
        self.columns[name] = list(values)
        self.row_count = len(values)

    def rename(self, old: str, new: str) -> None:
        if old in self.columns:
            self.columns[new] = self.columns.pop(old)

    def project(self, names: Sequence[str]) -> "Batch":
        """按给定列名与顺序生成新的 Batch（共享底层数组引用）。"""
        return Batch({name: self.columns[name] for name in names}, self.row_count)

    def empty_like(self) -> "Batch":
        return Batch({name: [] for name in self.columns}, 0)

    def slice_rows(self, start: int, stop: int) -> "Batch":
        return Batch({k: v[start:stop] for k, v in self.columns.items()}, max(0, stop - start))

    def mask(self, keep: Sequence[bool]) -> "Batch":
        """按布尔掩码筛出行，返回新 Batch。"""
        out: Dict[str, List[Any]] = {}
        for name, values in self.columns.items():
            out[name] = [v for v, k in zip(values, keep) if k]
        return Batch(out, sum(1 for k in keep if k))

    def take(self, indices: Sequence[int]) -> "Batch":
        """按行号索引抽取行，返回新 Batch。"""
        out: Dict[str, List[Any]] = {}
        for name, values in self.columns.items():
            out[name] = [values[i] for i in indices]
        return Batch(out, len(indices))

    def rows(self) -> Iterator[Dict[str, Any]]:
        """按行迭代，输出字典序列（用于导出与展示）。"""
        names = self.column_names
        arrays = [self.columns[n] for n in names]
        for i in range(self.row_count):
            yield {n: a[i] for n, a in zip(names, arrays)}

    def infer_types(self) -> Dict[str, str]:
        return {name: infer_type(values) for name, values in self.columns.items()}

    def __len__(self) -> int:
        return self.row_count

    def __bool__(self) -> bool:
        return self.row_count > 0

    def __repr__(self) -> str:  # pragma: no cover - 调试用途
        cols = ", ".join(self.column_names[:6])
        return f"<Batch rows={self.row_count} cols=[{cols}]>"


def batch_from_rows(rows: Sequence[Dict[str, Any]], columns: Optional[Sequence[str]] = None) -> Batch:
    """把行式数据（字典序列）转换为列式 Batch。"""
    if columns is None:
        columns = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
    data: Dict[str, List[Any]] = {name: [] for name in columns}
    for row in rows:
        for name in columns:
            data[name].append(row.get(name))
    return Batch(data, len(rows))


def concat_batches(batches: Sequence[Batch]) -> Batch:
    """把多个结构相同的 Batch 纵向拼接为一个。"""
    batches = [b for b in batches if b.row_count > 0]
    if not batches:
        return Batch()
    names = batches[0].column_names
    merged: Dict[str, List[Any]] = {name: [] for name in names}
    total = 0
    for batch in batches:
        for name in names:
            merged[name].extend(batch.columns.get(name, [None] * batch.row_count))
        total += batch.row_count
    return Batch(merged, total)
