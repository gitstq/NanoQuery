"""NanoQuery 核心数据类型定义。

本模块定义了 NanoQuery 的**值模型**、**列类型系统**以及贯穿全项目的异常类型。

设计原则:
    * 值直接使用 Python 原生对象表示（``None`` / ``bool`` / ``int`` / ``float`` / ``str``），
      避免额外的包装开销，使引擎在纯 CPython 下依然保持合理的执行效率。
    * 列类型用简短的字符串常量表示，便于序列化进 ``.nq`` 列存文件。
    * 所有用户可感知的错误统一继承 :class:`NanoQueryError`，便于 CLI 层统一捕获与展示。
"""

from __future__ import annotations

from typing import Any, List, Sequence

__all__ = [
    "TYPE_NULL",
    "TYPE_BOOL",
    "TYPE_INT",
    "TYPE_FLOAT",
    "TYPE_STR",
    "TYPE_NAMES",
    "NanoQueryError",
    "ParseError",
    "ResolveError",
    "ExecutionError",
    "StorageError",
    "infer_type",
    "widen_type",
    "coerce_number",
    "to_bool",
    "compare_values",
    "value_repr",
]


# --------------------------------------------------------------------------- #
# 列类型常量
# --------------------------------------------------------------------------- #

TYPE_NULL = "NULL"
TYPE_BOOL = "BOOL"
TYPE_INT = "INT"
TYPE_FLOAT = "FLOAT"
TYPE_STR = "STR"

#: 类型优先级，用于类型提升（widen）。数值类型之间可相互提升。
TYPE_RANK = {
    TYPE_NULL: 0,
    TYPE_BOOL: 1,
    TYPE_INT: 2,
    TYPE_FLOAT: 3,
    TYPE_STR: 4,
}

TYPE_NAMES = (TYPE_NULL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STR)


# --------------------------------------------------------------------------- #
# 异常体系
# --------------------------------------------------------------------------- #


class NanoQueryError(Exception):
    """NanoQuery 所有业务异常的基类。"""


class ParseError(NanoQueryError):
    """SQL 词法或语法分析失败。"""

    def __init__(self, message: str, position: int = -1) -> None:
        self.position = position
        if position >= 0:
            message = f"{message} (位置 {position})"
        super().__init__(message)


class ResolveError(NanoQueryError):
    """语义解析失败，例如引用了不存在的列或表。"""


class ExecutionError(NanoQueryError):
    """查询执行期错误，例如类型不匹配或聚合函数误用。"""


class StorageError(NanoQueryError):
    """列存文件读写错误。"""


# --------------------------------------------------------------------------- #
# 类型推断与提升
# --------------------------------------------------------------------------- #


def infer_type(values: Sequence[Any]) -> str:
    """根据一批样本值推断列类型。

    全为 ``None`` 时返回 :data:`TYPE_NULL`；数值混排时按 ``INT -> FLOAT`` 提升；
    出现任意字符串则整体降级为 :data:`TYPE_STR`。
    """
    current = TYPE_NULL
    for value in values:
        current = widen_type(current, _type_of(value))
        if current == TYPE_STR:
            break
    return current


def _type_of(value: Any) -> str:
    if value is None:
        return TYPE_NULL
    if isinstance(value, bool):
        return TYPE_BOOL
    if isinstance(value, int):
        return TYPE_INT
    if isinstance(value, float):
        return TYPE_FLOAT
    if isinstance(value, str):
        return TYPE_STR
    return TYPE_STR


def widen_type(left: str, right: str) -> str:
    """返回两个列类型的最小公共父类型（用于 UNION / CASE 结果类型推导）。"""
    if left == right:
        return left
    if left == TYPE_NULL:
        return right
    if right == TYPE_NULL:
        return left
    # BOOL 与 INT 混合时归为 INT，便于算术运算。
    if {left, right} == {TYPE_BOOL, TYPE_INT}:
        return TYPE_INT
    if left in (TYPE_INT, TYPE_FLOAT) and right in (TYPE_INT, TYPE_FLOAT):
        return TYPE_FLOAT
    return TYPE_STR


def coerce_number(value: Any, context: str = "表达式") -> float:
    """把值转换为数值，失败时抛出 :class:`ExecutionError`。"""
    if value is None:
        return None  # type: ignore[return-value]
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ExecutionError(f"{context} 需要数值类型，实际得到 {value_repr(value)}")


def to_bool(value: Any) -> Any:
    """SQL 三值逻辑下的布尔转换，``None`` 保持传播。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "t", "yes", "y", "1"):
            return True
        if lowered in ("false", "f", "no", "n", "0", ""):
            return False
    return bool(value)


def compare_values(left: Any, right: Any) -> Any:
    """比较两个标量，返回 ``-1 / 0 / 1``，任一侧为 NULL 时返回 ``None``。

    数值与字符串之间会尝试把字符串解析为数字，以贴近 SQLite 的亲和性行为。
    """
    if left is None or right is None:
        return None
    if isinstance(left, bool) or isinstance(right, bool):
        return _sign(_norm_num(left) - _norm_num(right))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return _sign(left - right)
    if isinstance(left, str) and isinstance(right, (int, float)):
        try:
            return _sign(float(left) - right)
        except ValueError:
            return _sign(_cmp_str(left, str(right)))
    if isinstance(right, str) and isinstance(left, (int, float)):
        try:
            return _sign(left - float(right))
        except ValueError:
            return _sign(_cmp_str(str(left), right))
    return _sign(_cmp_str(str(left), str(right)))


def _norm_num(value: Any) -> float:
    return 1.0 if value is True else (0.0 if value is False else float(value))


def _cmp_str(left: str, right: str) -> int:
    return (left > right) - (left < right)


def _sign(delta: float) -> int:
    if delta == 0:
        return 0
    return 1 if delta > 0 else -1


def value_repr(value: Any) -> str:
    """生成用于终端展示的值字面量。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    return str(value)


def ensure_list(values: Any) -> List[Any]:
    """把任意输入规整为列表，便于算子统一处理。"""
    if values is None:
        return []
    if isinstance(values, list):
        return values
    return list(values)
