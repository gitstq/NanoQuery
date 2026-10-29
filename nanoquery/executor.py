"""NanoQuery 执行引擎。

执行流程遵循经典的火山模型 + 向量化批处理::

    Scan -> Filter(WHERE) -> [ HashJoin ] -> Aggregate(GROUP BY/HAVING)
         -> Project(SELECT) -> Distinct -> Order -> Limit/Offset

与教科书式实现的两点差异（也是本引擎的差异化亮点）：

1. **真正的流式执行**：除聚合、排序这类必须看到全量数据的算子外，其余算子
   均为增量产出，因此可以对远大于内存的文件执行 ``SELECT ... WHERE ... LIMIT 10``。
2. **列裁剪下推**：当数据源是 ``.nq`` 列存时，引擎会把查询真正用到的列推导到
   扫描层，只解码这些列，避免无谓 I/O 与解压开销。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .ast import (
    Between, BinaryOp, CaseExpr, CastExpr, ColumnRef, Expr, FunctionCall, InList,
    IsNull, Like, Literal, LogicalOp, Query, SelectItem, StarExpr, TableRef, UnaryOp,
)
from .batch import Batch, batch_from_rows, concat_batches
from .functions import (
    AGGREGATE_FUNCTIONS, DISTINCT_AGGREGATES, Aggregate, LikeMatcher, get_scalar,
    is_aggregate,
)
from .sources import Source, source_for_path
from .types import (
    ExecutionError, ResolveError, compare_values, coerce_number, to_bool,
)

__all__ = ["Engine", "Result", "execute", "unparse", "contains_aggregate"]


# --------------------------------------------------------------------------- #
# 表达式工具
# --------------------------------------------------------------------------- #


def unparse(expr: Optional[Expr]) -> str:
    """把表达式还原成可读的 SQL 片段（用于默认输出列名与 EXPLAIN）。"""
    if expr is None:
        return ""
    if isinstance(expr, Literal):
        if expr.value is None:
            return "NULL"
        if isinstance(expr.value, str):
            return f"'{expr.value}'"
        return str(expr.value)
    if isinstance(expr, ColumnRef):
        return f"{expr.table}.{expr.name}" if expr.table else expr.name
    if isinstance(expr, StarExpr):
        return f"{expr.table}.*" if expr.table else "*"
    if isinstance(expr, UnaryOp):
        return f"{expr.op} {unparse(expr.operand)}"
    if isinstance(expr, BinaryOp):
        return f"({unparse(expr.left)} {expr.op} {unparse(expr.right)})"
    if isinstance(expr, LogicalOp):
        return f"({f' {expr.op} '.join(unparse(o) for o in expr.operands)})"
    if isinstance(expr, IsNull):
        return f"{unparse(expr.operand)} IS {'NOT ' if expr.negated else ''}NULL"
    if isinstance(expr, InList):
        items = ", ".join(unparse(i) for i in expr.items)
        return f"{unparse(expr.operand)}{' NOT' if expr.negated else ''} IN ({items})"
    if isinstance(expr, Between):
        base = unparse(expr.operand)
        return f"{base}{' NOT' if expr.negated else ''} BETWEEN {unparse(expr.low)} AND {unparse(expr.high)}"
    if isinstance(expr, Like):
        op = "ILIKE" if expr.case_insensitive else "LIKE"
        return f"{unparse(expr.operand)}{' NOT' if expr.negated else ''} {op} {unparse(expr.pattern)}"
    if isinstance(expr, FunctionCall):
        if expr.star:
            return f"{expr.name}(*)"
        inner = "DISTINCT " if expr.distinct else ""
        return f"{expr.name}({inner}{', '.join(unparse(a) for a in expr.args)})"
    if isinstance(expr, CaseExpr):
        parts = " ".join(f"WHEN {unparse(w)} THEN {unparse(t)}" for w, t in expr.whens)
        return f"CASE {parts} ELSE {unparse(expr.default)} END"
    if isinstance(expr, CastExpr):
        return f"CAST({unparse(expr.operand)} AS {expr.target})"
    return "expr"


def contains_aggregate(expr: Optional[Expr]) -> bool:
    """判断表达式树中是否包含聚合函数。"""
    found = []
    collect_aggregates(expr, found)
    return bool(found)


def collect_aggregates(expr: Optional[Expr], out: List[FunctionCall]) -> None:
    """按求值顺序收集表达式中的聚合调用（同一节点只登记一次）。"""
    if expr is None:
        return
    if isinstance(expr, FunctionCall):
        if is_aggregate(expr.name):
            if not any(existing is expr for existing in out):
                out.append(expr)
            return
        for arg in expr.args:
            collect_aggregates(arg, out)
        return
    if isinstance(expr, (UnaryOp, IsNull, CastExpr)):
        collect_aggregates(getattr(expr, "operand", None), out)
    elif isinstance(expr, BinaryOp):
        collect_aggregates(expr.left, out)
        collect_aggregates(expr.right, out)
    elif isinstance(expr, LogicalOp):
        for operand in expr.operands:
            collect_aggregates(operand, out)
    elif isinstance(expr, InList):
        collect_aggregates(expr.operand, out)
        for item in expr.items:
            collect_aggregates(item, out)
    elif isinstance(expr, Between):
        for node in (expr.operand, expr.low, expr.high):
            collect_aggregates(node, out)
    elif isinstance(expr, Like):
        collect_aggregates(expr.operand, out)
        collect_aggregates(expr.pattern, out)
    elif isinstance(expr, CaseExpr):
        collect_aggregates(expr.operand, out)
        collect_aggregates(expr.default, out)
        for when, then in expr.whens:
            collect_aggregates(when, out)
            collect_aggregates(then, out)


def collect_columns(expr: Optional[Expr], out: List[ColumnRef]) -> None:
    """收集表达式引用的所有列（用于列裁剪下推）。"""
    if expr is None:
        return
    if isinstance(expr, ColumnRef):
        out.append(expr)
    elif isinstance(expr, (UnaryOp, IsNull, CastExpr)):
        collect_columns(getattr(expr, "operand", None), out)
    elif isinstance(expr, BinaryOp):
        collect_columns(expr.left, out)
        collect_columns(expr.right, out)
    elif isinstance(expr, LogicalOp):
        for operand in expr.operands:
            collect_columns(operand, out)
    elif isinstance(expr, InList):
        collect_columns(expr.operand, out)
        for item in expr.items:
            collect_columns(item, out)
    elif isinstance(expr, Between):
        for node in (expr.operand, expr.low, expr.high):
            collect_columns(node, out)
    elif isinstance(expr, Like):
        collect_columns(expr.operand, out)
        collect_columns(expr.pattern, out)
    elif isinstance(expr, FunctionCall):
        for arg in expr.args:
            collect_columns(arg, out)
    elif isinstance(expr, CaseExpr):
        collect_columns(expr.operand, out)
        collect_columns(expr.default, out)
        for when, then in expr.whens:
            collect_columns(when, out)
            collect_columns(then, out)


# --------------------------------------------------------------------------- #
# 列解析作用域
# --------------------------------------------------------------------------- #


class Scope:
    """列解析上下文。

    Batch 内部统一使用**限定列名**（``别名.列名``）。用户 SQL 里既可以写限定名，
    也可以写裸名——裸名通过后缀匹配解析；匹配到多列时判定为歧义并报错。
    """

    __slots__ = ("names", "_lower")

    def __init__(self, names: Sequence[str]) -> None:
        self.names = list(names)
        self._lower = {n.lower(): n for n in self.names}

    def resolve(self, name: str, table: Optional[str] = None) -> str:
        candidates = [f"{table}.{name}"] if table else [name]
        for cand in candidates:
            if cand in self.names:
                return cand
        for cand in candidates:
            if cand.lower() in self._lower:
                return self._lower[cand.lower()]
        if table:
            # 限定名可能带有嵌套前缀（例如 JSONL 展平出的 events.user.name），
            # 先做「表别名 + 列路径」的后缀匹配，再退回严格的别名匹配。
            suffix = f"{table.lower()}.{name.lower()}"
            matches = [
                n for n in self.names
                if n.lower() == suffix or n.lower().endswith("." + suffix)
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ResolveError(f"列名歧义：{table}.{name}（可匹配 {'/'.join(matches)}）")
            for existing in self.names:
                left, _, right = existing.partition(".")
                if right.lower() == name.lower() and left.lower() == table.lower():
                    return existing
            raise ResolveError(f"未知的列：{table}.{name}")
        matches = [n for n in self.names if n.split(".", 1)[-1].lower() == name.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ResolveError(f"列名歧义：{name}（可匹配 {'/'.join(matches)}）")
        raise ResolveError(f"未知的列：{name}")

    def has(self, name: str, table: Optional[str] = None) -> bool:
        try:
            self.resolve(name, table)
            return True
        except ResolveError:
            return False

    def __repr__(self) -> str:  # pragma: no cover - 调试用途
        return f"<Scope {self.names}>"


# --------------------------------------------------------------------------- #
# 表达式求值（向量化）
# --------------------------------------------------------------------------- #


def eval_expr(
    expr: Expr,
    batch: Batch,
    scope: Scope,
    agg_values: Optional[Dict[int, Any]] = None,
) -> List[Any]:
    """在给定 Batch 上求值表达式，返回长度为 ``batch.row_count`` 的数组。

    Args:
        expr: 待求值表达式。
        batch: 输入数据批。
        scope: 列解析上下文。
        agg_values: 聚合结果映射（``id(FunctionCall) -> 标量``），用于聚合后置阶段。
    """
    n = batch.row_count

    if isinstance(expr, Literal):
        return [expr.value] * n

    if isinstance(expr, ColumnRef):
        return batch.columns[scope.resolve(expr.name, expr.table)]

    if isinstance(expr, FunctionCall):
        if is_aggregate(expr.name):
            if agg_values is None or id(expr) not in agg_values:
                raise ExecutionError(f"聚合函数 {expr.name} 不能出现在该位置")
            return [agg_values[id(expr)]] * n
        func = get_scalar(expr.name)
        if func is None:
            raise ResolveError(f"未知的函数：{expr.name}")
        arg_arrays = [eval_expr(a, batch, scope, agg_values) for a in expr.args]
        if not arg_arrays:
            return [func()] * n
        return [func(*row) for row in zip(*arg_arrays)]

    if isinstance(expr, UnaryOp):
        values = eval_expr(expr.operand, batch, scope, agg_values)
        if expr.op == "NOT":
            return [None if v is None else (not to_bool(v)) for v in values]
        if expr.op == "-":
            return [None if v is None else -coerce_number(v, "一元负号") for v in values]
        return values

    if isinstance(expr, BinaryOp):
        left = eval_expr(expr.left, batch, scope, agg_values)
        right = eval_expr(expr.right, batch, scope, agg_values)
        return [_binary_scalar(expr.op, a, b) for a, b in zip(left, right)]

    if isinstance(expr, LogicalOp):
        return _logical_op(expr, batch, scope, agg_values)

    if isinstance(expr, IsNull):
        values = eval_expr(expr.operand, batch, scope, agg_values)
        if expr.negated:
            return [v is not None for v in values]
        return [v is None for v in values]

    if isinstance(expr, Between):
        values = eval_expr(expr.operand, batch, scope, agg_values)
        low = eval_expr(expr.low, batch, scope, agg_values)
        high = eval_expr(expr.high, batch, scope, agg_values)
        out = []
        for v, lo, hi in zip(values, low, high):
            if v is None or lo is None or hi is None:
                out.append(None)
                continue
            low_cmp = compare_values(v, lo)
            high_cmp = compare_values(v, hi)
            inside = low_cmp is not None and high_cmp is not None and low_cmp >= 0 and high_cmp <= 0
            out.append((not inside) if expr.negated else inside)
        return out

    if isinstance(expr, InList):
        values = eval_expr(expr.operand, batch, scope, agg_values)
        if all(isinstance(item, Literal) for item in expr.items):
            pool = {item.value for item in expr.items if item.value is not None}
            has_null = any(item.value is None for item in expr.items)
            out = []
            for v in values:
                if v is None:
                    out.append(None if has_null else None)
                    continue
                found = v in pool
                out.append((not found) if expr.negated else found)
            return out
        item_values = [eval_expr(item, batch, scope, agg_values) for item in expr.items]
        rows = list(zip(*item_values)) if item_values else [()] * n
        out = []
        for v, row in zip(values, rows):
            if v is None:
                out.append(None)
                continue
            found = any(compare_values(v, candidate) == 0 for candidate in row)
            out.append((not found) if expr.negated else found)
        return out

    if isinstance(expr, Like):
        values = eval_expr(expr.operand, batch, scope, agg_values)
        patterns = eval_expr(expr.pattern, batch, scope, agg_values)
        out = []
        for v, p in zip(values, patterns):
            result = LikeMatcher.match(v, p, expr.case_insensitive)
            if result is None:
                out.append(None)
            else:
                out.append((not result) if expr.negated else result)
        return out

    if isinstance(expr, CaseExpr):
        operand_values = eval_expr(expr.operand, batch, scope, agg_values) if expr.operand else None
        when_arrays = [
            (eval_expr(w, batch, scope, agg_values), eval_expr(t, batch, scope, agg_values))
            for w, t in expr.whens
        ]
        default_values = (
            eval_expr(expr.default, batch, scope, agg_values)
            if expr.default is not None
            else [None] * n
        )
        out = []
        for i in range(n):
            result = default_values[i]
            if operand_values is not None:
                base = operand_values[i]
                for when_arr, then_arr in when_arrays:
                    if base is not None and compare_values(base, when_arr[i]) == 0:
                        result = then_arr[i]
                        break
            else:
                for when_arr, then_arr in when_arrays:
                    if to_bool(when_arr[i]) is True:
                        result = then_arr[i]
                        break
            out.append(result)
        return out

    if isinstance(expr, CastExpr):
        values = eval_expr(expr.operand, batch, scope, agg_values)
        return [_cast_value(v, expr.target) for v in values]

    raise ExecutionError(f"无法求值的表达式：{expr!r}")


def _cast_value(value: Any, target: str) -> Any:
    if value is None:
        return None
    target = target.upper()
    try:
        if target in ("INT", "INTEGER", "BIGINT"):
            return int(float(value)) if isinstance(value, str) else int(value)
        if target in ("FLOAT", "DOUBLE", "REAL", "NUMERIC", "DECIMAL"):
            return float(value)
        if target in ("BOOL", "BOOLEAN"):
            return to_bool(value)
        return value if isinstance(value, str) else str(value)
    except (TypeError, ValueError):
        raise ExecutionError(f"CAST 失败：无法把 {value!r} 转为 {target}")


def _binary_scalar(op: str, a: Any, b: Any) -> Any:
    if op in ("=", "==", "!=", "<>", "<", "<=", ">", ">="):
        if a is None or b is None:
            return None
        cmp = compare_values(a, b)
        if cmp is None:
            return None
        return {
            "=": cmp == 0, "==": cmp == 0, "!=": cmp != 0, "<>": cmp != 0,
            "<": cmp < 0, "<=": cmp <= 0, ">": cmp > 0, ">=": cmp >= 0,
        }[op]

    if op == "||":
        if a is None or b is None:
            return None
        return (a if isinstance(a, str) else str(a)) + (b if isinstance(b, str) else str(b))

    if a is None or b is None:
        return None

    if isinstance(a, str) or isinstance(b, str):
        if op == "+":
            return str(a) + str(b)
        raise ExecutionError(f"字符串不支持 {op} 运算")

    if op == "+":
        return _norm_result(a + b)
    if op == "-":
        return _norm_result(a - b)
    if op == "*":
        return _norm_result(a * b)
    if op == "/":
        if b == 0:
            raise ExecutionError("除数为 0")
        return _norm_result(a / b)
    if op == "%":
        if b == 0:
            raise ExecutionError("模运算的除数为 0")
        return _norm_result(a % b)
    raise ExecutionError(f"不支持的运算符：{op}")


def _norm_result(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def _logical_op(expr: LogicalOp, batch: Batch, scope: Scope, agg_values) -> List[Any]:
    n = batch.row_count
    arrays = [eval_expr(operand, batch, scope, agg_values) for operand in expr.operands]
    result: List[Any] = [None] * n
    if expr.op == "AND":
        for i in range(n):
            value: Any = True
            for arr in arrays:
                flag = to_bool(arr[i])
                if flag is False:
                    value = False
                    break
                if flag is None:
                    value = None
            result[i] = value
    else:
        for i in range(n):
            value: Any = False
            for arr in arrays:
                flag = to_bool(arr[i])
                if flag is True:
                    value = True
                    break
                if flag is None:
                    value = None
            result[i] = value
    return result


# --------------------------------------------------------------------------- #
# 引擎与结果
# --------------------------------------------------------------------------- #


def _safe_ident(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]", "_", name)
    if cleaned and cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or "data"


class Result:
    """查询结果：列名 + 惰性行迭代器。"""

    def __init__(self, columns: List[str], batches: Iterator[Batch]) -> None:
        self.columns = columns
        self._batches = batches
        self._materialized: Optional[List[Dict[str, Any]]] = None

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        for batch in self._batches:
            yield from batch.rows()

    def batches(self) -> Iterator[Batch]:
        return self._batches

    def rows(self) -> List[Dict[str, Any]]:
        """物化并返回全部结果行。"""
        if self._materialized is None:
            self._materialized = list(self.__iter__())
        return self._materialized

    @property
    def row_count(self) -> int:
        return len(self.rows())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Result columns={self.columns}>"


def _as_source(source, name: str, batch_size: int):
    """把任意可注册对象（Source / Batch / 行字典序列）规整为 :class:`Source`。"""
    if hasattr(source, "batches"):
        return source
    from .batch import Batch
    from .sources import MemorySource

    if isinstance(source, Batch):
        return MemorySource(source, name=name, batch_size=batch_size)
    return MemorySource(source, name=name, batch_size=batch_size)


class Engine:
    """NanoQuery 引擎：管理表注册与查询执行。"""

    def __init__(self, batch_size: int = 4096) -> None:
        self.batch_size = batch_size
        self.tables: Dict[str, Source] = {}
        self._lower: Dict[str, str] = {}

    # ---------------- 表管理 ---------------- #

    def register(self, name: str, source) -> None:
        """注册一张表（数据源）。同名注册会覆盖。

        除 :class:`Source` 外，也接受内存数据：一个 :class:`Batch`，
        或由行字典组成的可迭代对象——后者会被包装为 :class:`MemorySource`。
        """
        self.tables[name] = _as_source(source, name, self.batch_size)
        self._lower[name.lower()] = name

    def register_data(self, name: str, data, columns: Optional[Sequence[str]] = None) -> None:
        """注册内存数据为表（``Batch`` 或行字典序列）。"""
        from .sources import MemorySource

        self.tables[name] = MemorySource(
            data, name=name, batch_size=self.batch_size, columns=columns
        )
        self._lower[name.lower()] = name

    def register_path(
        self,
        name: Optional[str],
        path: str,
        fmt: Optional[str] = None,
        delimiter: Optional[str] = None,
        has_header: bool = True,
        no_header: bool = False,
        log_pattern: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> str:
        """注册一个文件为表，返回实际使用的表名。"""
        source = source_for_path(
            path,
            fmt=fmt,
            batch_size=self.batch_size,
            delimiter=delimiter,
            has_header=has_header and not no_header,
            log_pattern=log_pattern,
            encoding=encoding,
        )
        table_name = _safe_ident(name or source.name)
        self.register(table_name, source)
        return table_name

    def resolve_table(self, name: str) -> Tuple[str, Source]:
        if name in self.tables:
            return name, self.tables[name]
        key = self._lower.get(name.lower())
        if key:
            return key, self.tables[key]
        raise ResolveError(
            f"未知的表：{name}（已注册：{', '.join(sorted(self.tables)) or '无'}）"
        )

    def schema(self, name: Optional[str] = None) -> Dict[str, List[Dict[str, str]]]:
        """返回已注册表（或指定表）的 schema。"""
        if name:
            _, source = self.resolve_table(name)
            return {name: source.schema()}
        return {key: source.schema() for key, source in self.tables.items()}

    # ---------------- 执行 ---------------- #

    def execute(self, query: Query) -> Result:
        """执行查询，返回惰性 :class:`Result`。"""
        return _execute_query(self, query)

    def query(self, sql: str) -> Result:
        from .parser import parse

        return self.execute(parse(sql))


# --------------------------------------------------------------------------- #
# 顶层：UNION 合并
# --------------------------------------------------------------------------- #


def _execute_query(engine: Engine, query: Query) -> Result:
    node: Optional[Query] = query
    columns: List[str] = []
    streams: List[Iterator[Batch]] = []

    while node is not None:
        cols, stream = _execute_select(engine, node)
        if not columns:
            columns = cols
        streams.append(_align_stream(stream, cols, columns))
        node = node.union

    if len(streams) == 1:
        return Result(columns, streams[0])

    if query.union_all:
        return Result(columns, _concat_streams(streams))
    return Result(columns, _distinct_stream(_concat_streams(streams), columns))


def _concat_streams(streams: Sequence[Iterator[Batch]]) -> Iterator[Batch]:
    for stream in streams:
        yield from stream


def _align_stream(stream: Iterator[Batch], source: Sequence[str], target: Sequence[str]) -> Iterator[Batch]:
    if list(source) == list(target):
        yield from stream
        return
    mapping = {src: tgt for src, tgt in zip(source, target)}
    for batch in stream:
        yield Batch({mapping.get(k, k): v for k, v in batch.columns.items()}, batch.row_count)


# --------------------------------------------------------------------------- #
# 单条 SELECT 执行
# --------------------------------------------------------------------------- #


def _execute_select(engine: Engine, query: Query) -> Tuple[List[str], Iterator[Batch]]:
    # 1) FROM
    if query.from_table is None:
        names: List[str] = []
        stream: Iterator[Batch] = iter([Batch({}, 1)])
    else:
        names, stream = _build_scan(engine, query)

    # 2) JOIN
    for join in query.joins:
        names, stream = _join_stream(engine, names, stream, join)

    scope = Scope(names)

    # 3) 聚合判定
    aggregates: List[FunctionCall] = []
    for item in query.items:
        collect_aggregates(item.expr, aggregates)
    collect_aggregates(query.having, aggregates)
    for key in query.group_by:
        collect_aggregates(key, aggregates)
    is_grouped = bool(aggregates) or bool(query.group_by)

    # 4) WHERE
    if query.where is not None:
        stream = _filter_stream(stream, scope, query.where)

    # 5) 输出列名 + 排序键计划
    #    SQL 语义：排序键可以是输出别名、输出列名、序号，也可以是未出现在 SELECT
    #    列表中的输入列。前三类直接复用投影结果；最后一类必须在投影前求值，以
    #    隐藏列的形式穿过投影，排序完成后丢弃。
    columns = _output_columns(query, scope, grouped=is_grouped)
    order_keys: List[str] = []
    carry: List[Tuple[str, Expr]] = []
    if query.order_by:
        out_scope = Scope(columns)
        for index, order in enumerate(query.order_by):
            name = _order_key_name(order.expr, out_scope)
            if name is None:
                position = _literal_int(order.expr)
                if position is not None and 1 <= position <= len(columns):
                    name = columns[position - 1]
            if name is None:
                if is_grouped:
                    raise ResolveError(
                        f"ORDER BY 无法解析：{unparse(order.expr)}"
                        "（聚合查询只能按分组列、聚合表达式或输出别名排序）"
                    )
                name = f"__orderkey{index}"
                carry.append((name, order.expr))
            order_keys.append(name)

    # 6) 聚合 / 投影
    if is_grouped:
        stream = _aggregate_stream(stream, scope, query, columns, aggregates)
    else:
        if carry:
            stream = _append_columns_stream(stream, scope, carry)
        stream = _project_stream(stream, scope, query, columns, carry=[n for n, _ in carry])

    # 7) DISTINCT
    if query.distinct and not is_grouped:
        stream = _distinct_stream(stream, columns)

    # 8) ORDER BY
    if query.order_by:
        hidden = {n for n, _ in carry}
        stream = _order_stream(stream, columns + [n for n, _ in carry], query, order_keys)
        if hidden:
            stream = (
                Batch({k: v for k, v in batch.columns.items() if k not in hidden}, batch.row_count)
                for batch in stream
            )

    # 8) LIMIT / OFFSET
    if query.limit is not None:
        stream = _limit_stream(stream, query, columns)

    return columns, stream


# ---------------------------- 列名推导 ---------------------------- #


def _output_columns(query: Query, scope: Scope, grouped: bool) -> List[str]:
    """计算 SELECT 列表的输出列名（不含 LIMIT 等后处理影响）。"""
    if grouped and any(isinstance(item.expr, StarExpr) for item in query.items):
        raise ExecutionError("聚合查询不支持 SELECT *，请显式列出分组列与聚合表达式")

    displays: List[str] = []
    if not grouped:
        for item in query.items:
            if isinstance(item.expr, StarExpr):
                star = item.expr
                for name in scope.names:
                    if star.table and not name.lower().startswith(f"{star.table.lower()}."):
                        continue
                    displays.append(name.split(".", 1)[-1])
            else:
                displays.append(_item_display(item, scope))
    else:
        for item in query.items:
            displays.append(_item_display(item, scope))
    return _dedupe_names(displays)


def _item_display(item: SelectItem, scope: Scope) -> str:
    if item.alias:
        return item.alias
    expr = item.expr
    if isinstance(expr, ColumnRef):
        try:
            return scope.resolve(expr.name, expr.table).split(".", 1)[-1]
        except ResolveError:
            return expr.name
    return unparse(expr)


def _dedupe_names(names: Sequence[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for name in names:
        if name in seen:
            seen[name] += 1
            out.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 1
            out.append(name)
    return out


def _select_plan(query: Query, scope: Scope, columns: Sequence[str]) -> List[Tuple[Expr, str]]:
    """把 SELECT 列表展开成 ``(表达式, 输出列名)`` 序列。"""
    plan: List[Tuple[Expr, str]] = []
    index = 0
    for item in query.items:
        if isinstance(item.expr, StarExpr):
            star = item.expr
            for name in scope.names:
                if star.table and not name.lower().startswith(f"{star.table.lower()}."):
                    continue
                plan.append((ColumnRef(name=name), columns[index]))
                index += 1
        else:
            plan.append((item.expr, columns[index]))
            index += 1
    return plan


# ---------------------------- 扫描 ---------------------------- #


def _build_scan(engine: Engine, query: Query) -> Tuple[List[str], Iterator[Batch]]:
    ref = query.from_table
    assert ref is not None

    if ref.query is not None:
        columns, stream = _execute_select(engine, ref.query)
        alias = ref.alias or "sub"
        return (
            [f"{alias}.{c}" for c in columns],
            _prefix_stream(stream, alias),
        )

    if ref.path:
        source = source_for_path(ref.path, fmt=ref.fmt, batch_size=engine.batch_size)
        alias = ref.alias or source.name
    else:
        _, source = engine.resolve_table(ref.name)
        alias = ref.alias or ref.name

    needed = _needed_columns(query, alias)
    try:
        column_names = [col["name"] for col in source.schema()]
    except Exception:  # pragma: no cover - schema 探测失败时退化为空
        column_names = []

    qualified = [f"{alias}.{name}" for name in column_names]
    return qualified, _scan_stream(source, alias, needed)


def _scan_stream(source: Source, alias: str, needed: Optional[List[str]]) -> Iterator[Batch]:
    if source.__class__.__name__ == "NqSource":
        from .storage import read_batches

        iterator = read_batches(source.path, source.batch_size, columns=needed)
    else:
        iterator = source.batches()
    for batch in iterator:
        yield Batch({f"{alias}.{name}": values for name, values in batch.columns.items()}, batch.row_count)


def _prefix_stream(stream: Iterator[Batch], alias: str) -> Iterator[Batch]:
    for batch in stream:
        yield Batch({f"{alias}.{name}": values for name, values in batch.columns.items()}, batch.row_count)


def _needed_columns(query: Query, alias: str) -> Optional[List[str]]:
    """推导该表真正被用到的列，用于 ``.nq`` 列裁剪下推。"""
    for item in query.items:
        if isinstance(item.expr, StarExpr):
            return None

    refs: List[ColumnRef] = []
    for item in query.items:
        collect_columns(item.expr, refs)
    collect_columns(query.where, refs)
    for key in query.group_by:
        collect_columns(key, refs)
    collect_columns(query.having, refs)
    for order in query.order_by:
        collect_columns(order.expr, refs)
    for join in query.joins:
        collect_columns(join.on, refs)

    needed = {r.name for r in refs if r.table is None or r.table.lower() == alias.lower()}
    return sorted(needed) if needed else None


# ---------------------------- 过滤 ---------------------------- #


def _filter_stream(stream: Iterator[Batch], scope: Scope, where: Expr) -> Iterator[Batch]:
    for batch in stream:
        if batch.row_count == 0:
            continue
        keep = [to_bool(v) is True for v in eval_expr(where, batch, scope)]
        if all(keep):
            yield batch
            continue
        filtered = batch.mask(keep)
        if filtered.row_count:
            yield filtered


# ---------------------------- 投影 ---------------------------- #


def _project_stream(
    stream: Iterator[Batch],
    scope: Scope,
    query: Query,
    columns: Sequence[str],
    carry: Sequence[str] = (),
) -> Iterator[Batch]:
    """投影出 SELECT 列表；``carry`` 中的列会被原样保留（供后续 ORDER BY 使用）。"""
    plan = _select_plan(query, scope, columns)
    for batch in stream:
        if batch.row_count == 0:
            continue
        out = {name: eval_expr(expr, batch, scope) for expr, name in plan}
        for name in carry:
            if name in batch.columns:
                out[name] = batch.columns[name]
        yield Batch(out, batch.row_count)


# ---------------------------- 聚合 ---------------------------- #


def _aggregate_stream(
    stream: Iterator[Batch],
    scope: Scope,
    query: Query,
    columns: Sequence[str],
    aggregates: List[FunctionCall],
) -> Iterator[Batch]:
    group_exprs = list(query.group_by)
    _validate_grouping(query, group_exprs, aggregates)

    groups: Dict[tuple, List[Aggregate]] = {}
    group_order: List[tuple] = []
    group_keys: Dict[tuple, Tuple[Any, ...]] = {}

    for batch in stream:
        if batch.row_count == 0:
            continue
        key_arrays = [eval_expr(g, batch, scope) for g in group_exprs]
        arg_cache: Dict[int, List[List[Any]]] = {}
        for agg in aggregates:
            if agg.star:
                arg_cache[id(agg)] = []
            elif agg.args:
                arg_cache[id(agg)] = [eval_expr(a, batch, scope) for a in agg.args]

        rows = list(zip(*key_arrays)) if key_arrays else [()] * batch.row_count
        for i, key in enumerate(rows):
            hkey = _hash_key(key)
            if hkey not in groups:
                groups[hkey] = _new_aggregates(aggregates)
                group_order.append(hkey)
                group_keys[hkey] = key
            state = groups[hkey]
            for pos, agg in enumerate(aggregates):
                if agg.star:
                    state[pos].update(1)
                elif agg.args:
                    args = arg_cache[id(agg)]
                    state[pos].update(*[a[i] for a in args])
                else:
                    state[pos].update(None)

    if not group_order and aggregates and not group_exprs:
        group_order = [()]
        groups[()] = _new_aggregates(aggregates)
        group_keys[()] = ()

    key_names = _dedupe_names([unparse(g) for g in group_exprs])
    plan = _select_plan(query, scope, columns)

    buffer: List[Dict[str, Any]] = []

    def flush() -> Iterator[Batch]:
        if buffer:
            yield batch_from_rows(buffer, list(columns))
            buffer.clear()

    for hkey in group_order:
        key = group_keys.get(hkey, ())
        values = {id(agg): groups[hkey][pos].finalize() for pos, agg in enumerate(aggregates)}
        row_batch = Batch({name: [value] for name, value in zip(key_names, key)}, 1) if group_exprs else Batch({}, 1)
        row_scope = Scope(key_names)

        if query.having is not None:
            if to_bool(eval_expr(query.having, row_batch, row_scope, values)[0]) is not True:
                continue

        row: Dict[str, Any] = {}
        for expr, name in plan:
            row[name] = eval_expr(expr, row_batch, row_scope, values)[0]
        buffer.append(row)
        if len(buffer) >= 4096:
            yield from flush()

    yield from flush()


def _validate_grouping(query: Query, group_exprs: Sequence[Expr], aggregates: Sequence[FunctionCall]) -> None:
    """校验：出现聚合时，SELECT 中的裸列必须出现在 GROUP BY 中。"""
    if not aggregates or not group_exprs:
        return
    group_texts = {unparse(g) for g in group_exprs}
    for item in query.items:
        if contains_aggregate(item.expr):
            continue
        refs: List[ColumnRef] = []
        collect_columns(item.expr, refs)
        for ref in refs:
            text = unparse(ref)
            if text not in group_texts and ref.name not in group_texts:
                raise ExecutionError(f"列 {text} 既不在聚合函数中，也不在 GROUP BY 子句里")


def _new_aggregates(aggregates: Sequence[FunctionCall]) -> List[Aggregate]:
    state: List[Aggregate] = []
    for agg in aggregates:
        if agg.star:
            state.append(_CountAllAgg())
            continue
        factory = AGGREGATE_FUNCTIONS.get(agg.name)
        if factory is None:
            raise ResolveError(f"未知的聚合函数：{agg.name}")
        if agg.distinct:
            if agg.name not in DISTINCT_AGGREGATES:
                raise ExecutionError(f"{agg.name}(DISTINCT ...) 暂不支持")
            state.append(_make_distinct(agg.name))
        else:
            state.append(factory())
    return state


def _make_distinct(name: str) -> Aggregate:
    if name == "COUNT":
        return _DistinctCountAgg()
    if name == "SUM":
        return _DistinctSumAgg()
    if name == "AVG":
        return _DistinctAvgAgg()
    if name == "MIN":
        return _DistinctMinMaxAgg(is_max=False)
    return _DistinctMinMaxAgg(is_max=True)


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


class _DistinctSumAgg(Aggregate):
    __slots__ = ("seen",)

    def __init__(self) -> None:
        self.seen = set()

    def update(self, value: Any) -> None:
        if value is not None:
            self.seen.add(value)

    def finalize(self) -> Any:
        return _norm_result(sum(self.seen)) if self.seen else None


class _DistinctAvgAgg(Aggregate):
    __slots__ = ("seen",)

    def __init__(self) -> None:
        self.seen = set()

    def update(self, value: Any) -> None:
        if value is not None:
            self.seen.add(value)

    def finalize(self) -> Any:
        return _norm_result(sum(self.seen) / len(self.seen)) if self.seen else None


class _DistinctMinMaxAgg(Aggregate):
    __slots__ = ("best", "is_max")

    def __init__(self, is_max: bool) -> None:
        self.best = None
        self.is_max = is_max

    def update(self, value: Any) -> None:
        if value is None:
            return
        if self.best is None or (value > self.best if self.is_max else value < self.best):
            self.best = value

    def finalize(self) -> Any:
        return self.best


# ---------------------------- JOIN ---------------------------- #


def _join_stream(engine: Engine, left_names: List[str], left_stream: Iterator[Batch], join) -> Tuple[List[str], Iterator[Batch]]:
    kind = (join.kind or "INNER").upper()

    if join.table.query is not None:
        right_columns, right_stream = _execute_select(engine, join.table.query)
        right_alias = join.table.alias or "sub"
        right_names = [f"{right_alias}.{c}" for c in right_columns]
        right_batches = list(_prefix_stream(right_stream, right_alias))
    elif join.table.path:
        source = source_for_path(join.table.path, fmt=join.table.fmt, batch_size=engine.batch_size)
        right_alias = join.table.alias or source.name
        right_names = [f"{right_alias}.{c['name']}" for c in source.schema()]
        right_batches = list(_scan_stream(source, right_alias, None))
    else:
        _, source = engine.resolve_table(join.table.name)
        right_alias = join.table.alias or join.table.name
        right_names = [f"{right_alias}.{c['name']}" for c in source.schema()]
        right_batches = list(_scan_stream(source, right_alias, None))

    if kind == "RIGHT":
        # RIGHT JOIN 通过交换左右两侧实现，输出时再恢复原有列顺序。
        mirrored = _JoinSpec(kind="LEFT", on=join.on)
        out_names, out_stream = _run_join(
            right_names, iter(right_batches), left_names, left_stream, mirrored, swapped=True
        )
        target = left_names + right_names
        return target, _reorder_stream(out_stream, out_names, target)

    out_names, out_stream = _run_join(
        left_names, left_stream, right_names, iter(right_batches), join, swapped=False
    )
    return out_names, out_stream


class _JoinSpec:
    __slots__ = ("kind", "on")

    def __init__(self, kind: str, on: Optional[Expr]) -> None:
        self.kind = kind
        self.on = on


def _reorder_stream(stream: Iterator[Batch], current: Sequence[str], target: Sequence[str]) -> Iterator[Batch]:
    if list(current) == list(target):
        yield from stream
        return
    for batch in stream:
        yield Batch({name: batch.columns[name] for name in target}, batch.row_count)


def _run_join(left_names, left_stream, right_names, right_stream, join, swapped: bool) -> Tuple[List[str], Iterator[Batch]]:
    kind = (join.kind or "INNER").upper()
    right_materialized = concat_batches(list(right_stream))
    left_scope = Scope(left_names)
    right_scope = Scope(right_names)
    out_names = left_names + right_names

    eq_left: List[Expr] = []
    eq_right: List[Expr] = []
    residual: Optional[Expr] = join.on
    if join.on is not None:
        eq_left, eq_right, residual = _split_equi_predicate(join.on, left_scope, right_scope)

    def generate() -> Iterator[Batch]:
        if kind == "CROSS" or join.on is None:
            for lbatch in left_stream:
                if lbatch.row_count == 0:
                    continue
                yield _cross_product(lbatch, left_names, right_materialized, right_names)
            return

        if eq_left:
            key_arrays = [eval_expr(expr, right_materialized, right_scope) for expr in eq_right]
            table: Dict[tuple, List[int]] = {}
            keys = list(zip(*key_arrays)) if key_arrays else [()] * right_materialized.row_count
            for idx, key in enumerate(keys):
                table.setdefault(_hash_key(key), []).append(idx)

            for lbatch in left_stream:
                if lbatch.row_count == 0:
                    continue
                lkeys = [eval_expr(expr, lbatch, left_scope) for expr in eq_left]
                left_idx: List[int] = []
                right_idx: List[Optional[int]] = []
                rows = list(zip(*lkeys)) if lkeys else [()] * lbatch.row_count
                for i, key in enumerate(rows):
                    matches = table.get(_hash_key(key), [])
                    if matches:
                        for j in matches:
                            left_idx.append(i)
                            right_idx.append(j)
                    elif kind == "LEFT":
                        left_idx.append(i)
                        right_idx.append(None)
                if not left_idx:
                    continue
                yield _materialize_join(
                    lbatch, left_names, right_materialized, right_names,
                    left_idx, right_idx, residual, kind,
                )
            return

        # 退化路径：嵌套循环 + ON 过滤
        for lbatch in left_stream:
            if lbatch.row_count == 0:
                continue
            if right_materialized.row_count == 0:
                if kind == "LEFT":
                    yield _pad_left(lbatch, left_names, right_names, list(range(lbatch.row_count)))
                continue
            product = _cross_product(lbatch, left_names, right_materialized, right_names)
            scope = Scope(out_names)
            keep = [to_bool(v) is True for v in eval_expr(join.on, product, scope)]
            kept = product.mask(keep)
            if kind == "LEFT":
                matched = _mark_matched(keep, lbatch.row_count, right_materialized.row_count)
                missing = [i for i, flag in enumerate(matched) if not flag]
                if missing:
                    kept = concat_batches([kept, _pad_left(lbatch, left_names, right_names, missing)])
            if kept.row_count:
                yield kept

    return out_names, generate()


def _split_equi_predicate(on: Expr, left_scope: Scope, right_scope: Scope):
    conjunctions: List[Expr] = []
    _flatten_and(on, conjunctions)

    eq_left: List[Expr] = []
    eq_right: List[Expr] = []
    residuals: List[Expr] = []
    for cond in conjunctions:
        if isinstance(cond, BinaryOp) and cond.op == "=":
            if _only_refs(cond.left, left_scope) and _only_refs(cond.right, right_scope):
                eq_left.append(cond.left)
                eq_right.append(cond.right)
                continue
            if _only_refs(cond.right, left_scope) and _only_refs(cond.left, right_scope):
                eq_left.append(cond.right)
                eq_right.append(cond.left)
                continue
        residuals.append(cond)

    if not eq_left:
        return [], [], on

    residual: Optional[Expr] = None
    for cond in residuals:
        residual = cond if residual is None else LogicalOp(op="AND", operands=[residual, cond])
    return eq_left, eq_right, residual


def _flatten_and(expr: Expr, out: List[Expr]) -> None:
    if isinstance(expr, LogicalOp) and expr.op == "AND":
        for operand in expr.operands:
            _flatten_and(operand, out)
    else:
        out.append(expr)


def _only_refs(expr: Expr, scope: Scope) -> bool:
    refs: List[ColumnRef] = []
    collect_columns(expr, refs)
    if not refs:
        return False
    return all(scope.has(r.name, r.table) for r in refs)


def _hash_key(values: Sequence[Any]) -> tuple:
    key = []
    for value in values:
        if value is None:
            key.append((0, 0))
        elif isinstance(value, bool):
            key.append((1, int(value)))
        elif isinstance(value, (int, float)):
            key.append((2, float(value)))
        else:
            key.append((3, str(value)))
    return tuple(key)


def _cross_product(lbatch: Batch, left_names, rbatch: Batch, right_names) -> Batch:
    ln, rn = lbatch.row_count, rbatch.row_count
    if ln == 0 or rn == 0:
        return Batch({name: [] for name in list(left_names) + list(right_names)}, 0)
    out: Dict[str, List[Any]] = {}
    for name in left_names:
        values = lbatch.columns[name]
        out[name] = [v for v in values for _ in range(rn)]
    for name in right_names:
        values = rbatch.columns[name]
        out[name] = [v for _ in range(ln) for v in values]
    return Batch(out, ln * rn)


def _materialize_join(lbatch, left_names, rbatch, right_names, left_idx, right_idx, residual, kind):
    out: Dict[str, List[Any]] = {}
    for name in left_names:
        values = lbatch.columns[name]
        out[name] = [values[i] for i in left_idx]
    for name in right_names:
        values = rbatch.columns[name]
        out[name] = [values[j] if j is not None else None for j in right_idx]

    batch = Batch(out, len(left_idx))
    if residual is None:
        return batch

    scope = Scope(list(left_names) + list(right_names))
    keep = [to_bool(v) is True for v in eval_expr(residual, batch, scope)]
    filtered = batch.mask(keep)

    if kind == "LEFT":
        dropped: Dict[int, bool] = {}
        for i, (li, rj) in enumerate(zip(left_idx, right_idx)):
            if not keep[i] and rj is not None:
                dropped[li] = True
        if dropped:
            filtered = concat_batches([filtered, _pad_left(lbatch, left_names, right_names, sorted(dropped))])
    return filtered


def _mark_matched(keep, ln, rn) -> List[bool]:
    flags = [False] * ln
    if rn == 0:
        return flags
    for i in range(ln):
        for j in range(rn):
            if keep[i * rn + j]:
                flags[i] = True
                break
    return flags


def _pad_left(lbatch, left_names, right_names, indices) -> Batch:
    out: Dict[str, List[Any]] = {}
    for name in left_names:
        values = lbatch.columns[name]
        out[name] = [values[i] for i in indices]
    for name in right_names:
        out[name] = [None] * len(indices)
    return Batch(out, len(indices))


# ---------------------------- 去重 / 排序 / 分页 ---------------------------- #


def _distinct_stream(stream: Iterator[Batch], columns: Sequence[str]) -> Iterator[Batch]:
    seen = set()
    buffer: List[Dict[str, Any]] = []
    for batch in stream:
        for row in batch.rows():
            key = _hash_key([row.get(c) for c in columns])
            if key in seen:
                continue
            seen.add(key)
            buffer.append(row)
            if len(buffer) >= 4096:
                yield batch_from_rows(buffer, list(columns))
                buffer = []
    if buffer:
        yield batch_from_rows(buffer, list(columns))


def _literal_int(expr: Optional[Expr]) -> Optional[int]:
    """若表达式是整数字面量则返回其值（用于 ``ORDER BY 2`` 这类序号）。"""
    if isinstance(expr, Literal) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return expr.value
    return None


def _order_key_name(expr: Expr, out_scope: Scope) -> Optional[str]:
    """尝试把 ORDER BY 表达式映射到已有输出列名。"""
    if isinstance(expr, ColumnRef):
        try:
            return out_scope.resolve(expr.name, expr.table)
        except ResolveError:
            pass
        if expr.table:
            # 输出列已去掉限定名（如 p.name -> name），退化为裸名匹配
            try:
                return out_scope.resolve(expr.name, None)
            except ResolveError:
                return None
    return None


def _append_columns_stream(
    stream: Iterator[Batch], scope: Scope, extra: Sequence[Tuple[str, Expr]]
) -> Iterator[Batch]:
    """在流上追加若干表达式列（用于 ORDER BY 引用未投影的输入列）。"""
    for batch in stream:
        if batch.row_count == 0:
            continue
        columns = dict(batch.columns)
        for name, expr in extra:
            columns[name] = eval_expr(expr, batch, scope)
        yield Batch(columns, batch.row_count)


def _order_stream(
    stream: Iterator[Batch],
    columns: Sequence[str],
    query: Query,
    key_names: Optional[Sequence[str]] = None,
) -> Iterator[Batch]:
    merged = concat_batches(list(stream))
    if merged.row_count == 0:
        return iter(())
    scope = Scope(merged.column_names)
    if key_names is None:
        key_names = []
    key_specs = []
    for index, order in enumerate(query.order_by):
        if index < len(key_names) and key_names[index] in merged.columns:
            values = merged.columns[key_names[index]]
        else:
            values = eval_expr(order.expr, merged, scope)
        key_specs.append((values, order.descending, order.nulls_last))

    indices = list(range(merged.row_count))
    for values, descending, nulls_last in reversed(key_specs):
        indices.sort(key=_sort_key_builder(values, descending, nulls_last))

    ordered = merged.take(indices)
    ordered_columns = [c for c in columns if c in ordered.columns] or ordered.column_names
    return iter([Batch({c: ordered.columns[c] for c in ordered_columns}, ordered.row_count)])


def _sort_key_builder(values: Sequence[Any], descending: bool, nulls_last: bool) -> Callable[[int], tuple]:
    def key(index: int) -> tuple:
        value = values[index]
        if value is None:
            return (1 if nulls_last else -1, 0.0, "")
        if isinstance(value, bool):
            number = float(int(value))
        elif isinstance(value, (int, float)):
            number = float(value)
        else:
            return (0, 0.0, _invert_str(str(value), descending))
        return (0, -number if descending else number, "")

    return key


def _invert_str(text: str, descending: bool) -> str:
    if not descending:
        return text
    return "".join(chr(0x10FFFF - ord(c)) if ord(c) < 0x10FFFF else c for c in text)


def _limit_stream(stream: Iterator[Batch], query: Query, columns: Sequence[str]) -> Iterator[Batch]:
    clause = query.limit
    limit: Optional[int] = None
    offset = 0
    if clause is not None:
        if clause.count is not None:
            value = eval_expr(clause.count, Batch({}, 1), Scope([]))[0]
            limit = int(coerce_number(value, "LIMIT"))
        if clause.offset is not None:
            offset = int(coerce_number(eval_expr(clause.offset, Batch({}, 1), Scope([]))[0], "OFFSET"))
    if limit is None and offset == 0:
        yield from stream
        return

    emitted = 0
    skipped = 0
    produced = False
    for batch in stream:
        if batch.row_count == 0:
            continue
        start = 0
        if skipped < offset:
            skip = min(offset - skipped, batch.row_count)
            start = skip
            skipped += skip
            if start >= batch.row_count:
                continue
        stop = batch.row_count
        if limit is not None:
            remaining = limit - emitted
            if remaining <= 0:
                break
            stop = min(batch.row_count, start + remaining)
        sliced = batch.slice_rows(start, stop)
        if sliced.row_count:
            produced = True
            yield sliced
            emitted += sliced.row_count
        if limit is not None and emitted >= limit:
            break
    if not produced:
        yield Batch({name: [] for name in columns}, 0)


# --------------------------------------------------------------------------- #
# 便捷入口
# --------------------------------------------------------------------------- #


def execute(sql: str, engine: Optional[Engine] = None, **paths) -> Result:
    """一行代码执行 SQL。

    Example:
        >>> result = execute("SELECT city, COUNT(*) AS c FROM t GROUP BY city", t="data.csv")
        >>> result.rows()
    """
    from .parser import parse

    eng = engine or Engine()
    for name, path in paths.items():
        eng.register_path(name, str(path))
    return eng.execute(parse(sql))
