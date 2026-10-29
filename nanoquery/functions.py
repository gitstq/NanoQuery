"""内置函数库：标量函数与聚合函数。

所有函数都是**零依赖纯 Python** 实现，并遵循 SQL 的 NULL 传播语义：
除 ``COALESCE`` / ``IFNULL`` / ``CONCAT`` 等显式处理 NULL 的函数外，
任意入参为 NULL 时结果即为 NULL。
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from .types import ExecutionError, TYPE_BOOL, TYPE_FLOAT, TYPE_INT, TYPE_STR

__all__ = [
    "SCALAR_FUNCTIONS", "AGGREGATE_FUNCTIONS", "is_aggregate", "get_scalar",
    "Aggregate", "LikeMatcher",
]


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #


def _num(value: Any, name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        raise ExecutionError(f"{name}() 需要数值参数，实际得到 {value!r}")


def _int_or(value: Any, default: int) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _norm(value: Any) -> Any:
    """把浮点整数值还原为 int，让展示更自然。"""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


# --------------------------------------------------------------------------- #
# 标量函数
# --------------------------------------------------------------------------- #


def _fn_upper(value):
    s = _str(value)
    return None if s is None else s.upper()


def _fn_lower(value):
    s = _str(value)
    return None if s is None else s.lower()


def _fn_length(value):
    s = _str(value)
    return None if s is None else len(s)


def _fn_trim(value, chars=None):
    s = _str(value)
    if s is None:
        return None
    return s.strip(chars) if chars else s.strip()


def _fn_ltrim(value):
    s = _str(value)
    return None if s is None else s.lstrip()


def _fn_rtrim(value):
    s = _str(value)
    return None if s is None else s.rstrip()


def _fn_substr(value, start, length=None):
    s = _str(value)
    if s is None or start is None:
        return None
    start_i = int(start)
    # SQL 下标从 1 开始；支持负数表示从尾部倒数
    begin = start_i - 1 if start_i > 0 else (len(s) + start_i if start_i < 0 else 0)
    begin = max(0, begin)
    if length is None:
        return s[begin:]
    length_i = int(length)
    if length_i < 0:
        return ""
    return s[begin : begin + length_i]


def _fn_replace(value, old, new):
    s, o, n = _str(value), _str(old), _str(new)
    if s is None or o is None or n is None:
        return None
    return s.replace(o, n)


def _fn_concat(*args):
    if any(a is None for a in args):
        return None
    return "".join(_str(a) for a in args)


def _fn_concat_ws(sep, *args):
    if sep is None:
        return None
    parts = [_str(a) for a in args if a is not None]
    return str(sep).join(parts)


def _fn_left(value, count):
    s = _str(value)
    return None if s is None or count is None else s[: max(0, int(count))]


def _fn_right(value, count):
    s = _str(value)
    if s is None or count is None:
        return None
    n = int(count)
    return s[len(s) - n :] if n > 0 else ""


def _fn_reverse(value):
    s = _str(value)
    return None if s is None else s[::-1]


def _fn_instr(value, sub):
    s, t = _str(value), _str(sub)
    if s is None or t is None:
        return None
    return s.find(t) + 1


def _fn_abs(value):
    number = _num(value, "ABS")
    return None if number is None else _norm(abs(number))


def _fn_round(value, digits=0):
    if value is None:
        return None
    number = _num(value, "ROUND")
    if number is None:
        return None
    d = int(digits or 0)
    result = round(number, d)
    return _norm(result)


def _fn_ceil(value):
    number = _num(value, "CEIL")
    return None if number is None else int(math.ceil(number))


def _fn_floor(value):
    number = _num(value, "FLOOR")
    return None if number is None else int(math.floor(number))


def _fn_sqrt(value):
    number = _num(value, "SQRT")
    if number is None:
        return None
    if number < 0:
        raise ExecutionError("SQRT() 不接受负数")
    return _norm(math.sqrt(number))


def _fn_power(base, exponent):
    b, e = _num(base, "POWER"), _num(exponent, "POWER")
    if b is None or e is None:
        return None
    return _norm(math.pow(b, e))


def _fn_exp(value):
    number = _num(value, "EXP")
    return None if number is None else _norm(math.exp(number))


def _fn_ln(value):
    number = _num(value, "LN")
    if number is None:
        return None
    if number <= 0:
        raise ExecutionError("LN() 的参数必须大于 0")
    return math.log(number)


def _fn_log10(value):
    number = _num(value, "LOG10")
    if number is None:
        return None
    if number <= 0:
        raise ExecutionError("LOG10() 的参数必须大于 0")
    return math.log10(number)


def _fn_mod(left, right):
    a, b = _num(left, "MOD"), _num(right, "MOD")
    if a is None or b is None:
        return None
    if b == 0:
        raise ExecutionError("MOD() 的除数不能为 0")
    return _norm(math.fmod(a, b))


def _fn_coalesce(*args):
    for arg in args:
        if arg is not None:
            return arg
    return None


def _fn_nullif(left, right):
    if left is None:
        return None
    return None if left == right else left


def _fn_ifnull(left, right):
    return right if left is None else left


def _fn_greatest(*args):
    values = [a for a in args if a is not None]
    if not values:
        return None
    return max(values, key=lambda v: (str(type(v)), v) if isinstance(v, str) else (0, v))


def _fn_least(*args):
    values = [a for a in args if a is not None]
    if not values:
        return None
    return min(values, key=lambda v: (str(type(v)), v) if isinstance(v, str) else (0, v))


def _fn_typeof(value):
    from .types import TYPE_BOOL, TYPE_FLOAT, TYPE_INT, TYPE_NULL, TYPE_STR

    if value is None:
        return TYPE_NULL
    if isinstance(value, bool):
        return TYPE_BOOL
    if isinstance(value, int):
        return TYPE_INT
    if isinstance(value, float):
        return TYPE_FLOAT
    return TYPE_STR


SCALAR_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "UPPER": _fn_upper,
    "LOWER": _fn_lower,
    "LENGTH": _fn_length,
    "LEN": _fn_length,
    "CHAR_LENGTH": _fn_length,
    "TRIM": _fn_trim,
    "LTRIM": _fn_ltrim,
    "RTRIM": _fn_rtrim,
    "SUBSTR": _fn_substr,
    "SUBSTRING": _fn_substr,
    "REPLACE": _fn_replace,
    "CONCAT": _fn_concat,
    "CONCAT_WS": _fn_concat_ws,
    "LEFT": _fn_left,
    "RIGHT": _fn_right,
    "REVERSE": _fn_reverse,
    "INSTR": _fn_instr,
    "ABS": _fn_abs,
    "ROUND": _fn_round,
    "CEIL": _fn_ceil,
    "CEILING": _fn_ceil,
    "FLOOR": _fn_floor,
    "SQRT": _fn_sqrt,
    "POWER": _fn_power,
    "POW": _fn_power,
    "EXP": _fn_exp,
    "LN": _fn_ln,
    "LOG": _fn_ln,
    "LOG10": _fn_log10,
    "MOD": _fn_mod,
    "COALESCE": _fn_coalesce,
    "IFNULL": _fn_ifnull,
    "NULLIF": _fn_nullif,
    "GREATEST": _fn_greatest,
    "LEAST": _fn_least,
    "TYPEOF": _fn_typeof,
}


def get_scalar(name: str) -> Optional[Callable[..., Any]]:
    return SCALAR_FUNCTIONS.get(name.upper())


# --------------------------------------------------------------------------- #
# LIKE 匹配
# --------------------------------------------------------------------------- #


class LikeMatcher:
    """把 SQL ``LIKE`` 模式翻译成正则，并缓存编译结果。

    支持 ``%``（任意长度）与 ``_``（单个字符）。
    """

    _cache: Dict[str, "re.Pattern"] = {}

    @classmethod
    def build(cls, pattern: str, case_insensitive: bool = False) -> "re.Pattern":
        key = f"{int(case_insensitive)}:{pattern}"
        compiled = cls._cache.get(key)
        if compiled is not None:
            return compiled
        out = ["(?s)\\A"]
        for ch in pattern:
            if ch == "%":
                out.append(".*")
            elif ch == "_":
                out.append(".")
            else:
                out.append(re.escape(ch))
        out.append("\\Z")
        flags = re.IGNORECASE if case_insensitive else 0
        compiled = re.compile("".join(out), flags)
        if len(cls._cache) < 512:
            cls._cache[key] = compiled
        return compiled

    @classmethod
    def match(cls, value: Any, pattern: Any, case_insensitive: bool = False) -> Any:
        if value is None or pattern is None:
            return None
        return bool(cls.build(str(pattern), case_insensitive).match(str(value)))


# --------------------------------------------------------------------------- #
# 聚合函数
# --------------------------------------------------------------------------- #


class Aggregate:
    """聚合累加器基类。"""

    __slots__ = ()

    def update(self, value: Any) -> None:
        raise NotImplementedError

    def finalize(self) -> Any:
        raise NotImplementedError


class _CountAgg(Aggregate):
    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count = 0

    def update(self, value: Any) -> None:
        if value is not None:
            self.count += 1

    def finalize(self) -> Any:
        return self.count


class _CountAllAgg(Aggregate):
    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count = 0

    def update(self, value: Any = None) -> None:
        self.count += 1

    def finalize(self) -> Any:
        return self.count


class _DistinctCountAgg(Aggregate):
    __slots__ = ("seen",)

    def __init__(self) -> None:
        self.seen = set()

    def update(self, value: Any) -> None:
        if value is not None:
            self.seen.add(value)

    def finalize(self) -> Any:
        return len(self.seen)


class _SumAgg(Aggregate):
    __slots__ = ("total", "has_value", "all_int")

    def __init__(self) -> None:
        self.total: Any = 0
        self.has_value = False
        self.all_int = True

    def update(self, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, bool):
            value = 1 if value else 0
        elif not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ExecutionError(f"SUM() 无法累加非数值：{value!r}")
        if isinstance(value, float):
            self.all_int = False
        self.total += value
        self.has_value = True

    def finalize(self) -> Any:
        if not self.has_value:
            return None
        return int(self.total) if (self.all_int and isinstance(self.total, float) is False) else self.total


class _AvgAgg(Aggregate):
    __slots__ = ("total", "count")

    def __init__(self) -> None:
        self.total = 0.0
        self.count = 0

    def update(self, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, bool):
            value = 1.0 if value else 0.0
        elif not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ExecutionError(f"AVG() 无法处理非数值：{value!r}")
        self.total += float(value)
        self.count += 1

    def finalize(self) -> Any:
        if self.count == 0:
            return None
        return _norm(self.total / self.count)


class _MinMaxAgg(Aggregate):
    __slots__ = ("best", "is_max")

    def __init__(self, is_max: bool) -> None:
        self.best: Any = None
        self.is_max = is_max

    def update(self, value: Any) -> None:
        if value is None:
            return
        if self.best is None:
            self.best = value
            return
        try:
            better = value > self.best if self.is_max else value < self.best
        except TypeError:
            better = str(value) > str(self.best) if self.is_max else str(value) < str(self.best)
        if better:
            self.best = value

    def finalize(self) -> Any:
        return self.best


class _NumericCollectAgg(Aggregate):
    __slots__ = ("values",)

    def __init__(self) -> None:
        self.values: List[float] = []

    def update(self, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, bool):
            value = 1.0 if value else 0.0
        elif not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return
        self.values.append(float(value))


class _MedianAgg(_NumericCollectAgg):
    def finalize(self) -> Any:
        if not self.values:
            return None
        ordered = sorted(self.values)
        n = len(ordered)
        mid = n // 2
        result = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        return _norm(result)


class _VarianceAgg(_NumericCollectAgg):
    __slots__ = ("sample",)

    def __init__(self, sample: bool = True) -> None:
        super().__init__()
        self.sample = sample

    def finalize(self) -> Any:
        n = len(self.values)
        if n == 0:
            return None
        if self.sample and n < 2:
            return None
        mean = sum(self.values) / n
        divisor = (n - 1) if self.sample else n
        return sum((v - mean) ** 2 for v in self.values) / divisor


class _StdDevAgg(_VarianceAgg):
    def finalize(self) -> Any:
        variance = super().finalize()
        return None if variance is None else math.sqrt(variance)


class _GroupConcatAgg(Aggregate):
    __slots__ = ("parts", "sep")

    def __init__(self, sep: str = ",") -> None:
        self.parts: List[str] = []
        self.sep = sep

    def update(self, value: Any) -> None:
        if value is not None:
            self.parts.append(value if isinstance(value, str) else str(value))

    def finalize(self) -> Any:
        return self.sep.join(self.parts) if self.parts else None


#: 聚合函数名 -> 构造函数。``COUNT(*)`` 会走 :class:`_CountAllAgg`。
AGGREGATE_FUNCTIONS: Dict[str, Callable[[], Aggregate]] = {
    "COUNT": _CountAgg,
    "SUM": _SumAgg,
    "AVG": _AvgAgg,
    "MIN": lambda: _MinMaxAgg(is_max=False),
    "MAX": lambda: _MinMaxAgg(is_max=True),
    "MEDIAN": _MedianAgg,
    "VARIANCE": lambda: _VarianceAgg(sample=True),
    "VARIANCE_POP": lambda: _VarianceAgg(sample=False),
    "STDDEV": _StdDevAgg,
    "GROUP_CONCAT": lambda: _GroupConcatAgg(),
}

DISTINCT_AGGREGATES = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT"})


def is_aggregate(name: str) -> bool:
    return name.upper() in AGGREGATE_FUNCTIONS
