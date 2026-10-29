"""NanoQuery 抽象语法树（AST）节点定义。

所有节点都是轻量数据类，仅承载结构与源码位置信息，不含任何求值逻辑——
求值统一在 :mod:`nanoquery.executor` 中完成，从而让解析器保持纯粹。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

__all__ = [
    "Node", "Expr", "Literal", "ColumnRef", "StarExpr", "UnaryOp", "BinaryOp",
    "LogicalOp", "IsNull", "Between", "InList", "Like", "FunctionCall",
    "CaseExpr", "CastExpr", "SelectItem", "TableRef", "Join", "OrderKey",
    "Query", "LimitClause",
]


@dataclass
class Node:
    """AST 节点基类。"""

    pos: int = -1


# --------------------------------------------------------------------------- #
# 表达式
# --------------------------------------------------------------------------- #


@dataclass
class Expr(Node):
    pass


@dataclass
class Literal(Expr):
    """字面量：数字、字符串、布尔、NULL。"""

    value: Any = None


@dataclass
class ColumnRef(Expr):
    """列引用，可带表限定符（``t.col``）。"""

    name: str = ""
    table: Optional[str] = None


@dataclass
class StarExpr(Expr):
    """``*`` 或 ``t.*``。"""

    table: Optional[str] = None


@dataclass
class UnaryOp(Expr):
    """一元运算：``-``、``+``、``NOT``。"""

    op: str = ""
    operand: Optional[Expr] = None


@dataclass
class BinaryOp(Expr):
    """二元运算，包括比较、算术与字符串连接。"""

    op: str = ""
    left: Optional[Expr] = None
    right: Optional[Expr] = None


@dataclass
class LogicalOp(Expr):
    """``AND`` / ``OR``，支持多操作数以便短路优化。"""

    op: str = ""
    operands: List[Expr] = field(default_factory=list)


@dataclass
class IsNull(Expr):
    operand: Optional[Expr] = None
    negated: bool = False


@dataclass
class Between(Expr):
    operand: Optional[Expr] = None
    low: Optional[Expr] = None
    high: Optional[Expr] = None
    negated: bool = False


@dataclass
class InList(Expr):
    operand: Optional[Expr] = None
    items: List[Expr] = field(default_factory=list)
    negated: bool = False


@dataclass
class Like(Expr):
    operand: Optional[Expr] = None
    pattern: Optional[Expr] = None
    negated: bool = False
    case_insensitive: bool = False


@dataclass
class FunctionCall(Expr):
    """标量函数或聚合函数调用。"""

    name: str = ""
    args: List[Expr] = field(default_factory=list)
    distinct: bool = False
    star: bool = False


@dataclass
class CaseExpr(Expr):
    """``CASE ... WHEN ... THEN ... ELSE ... END``，同时覆盖简单 CASE 形式。"""

    operand: Optional[Expr] = None
    whens: List[tuple] = field(default_factory=list)  # [(when_expr, then_expr)]
    default: Optional[Expr] = None


@dataclass
class CastExpr(Expr):
    operand: Optional[Expr] = None
    target: str = ""


# --------------------------------------------------------------------------- #
# 查询结构
# --------------------------------------------------------------------------- #


@dataclass
class SelectItem(Node):
    expr: Optional[Expr] = None
    alias: Optional[str] = None


@dataclass
class TableRef(Node):
    """FROM 子句中的表来源：物理表、文件函数或子查询。"""

    name: str = ""
    alias: Optional[str] = None
    query: Optional["Query"] = None
    path: Optional[str] = None  # 形如 read_csv('x.csv') 中的路径
    fmt: Optional[str] = None  # csv / jsonl / log / nq


@dataclass
class Join(Node):
    kind: str = "INNER"  # INNER | LEFT | RIGHT | CROSS
    table: Optional[TableRef] = None
    on: Optional[Expr] = None


@dataclass
class OrderKey(Node):
    expr: Optional[Expr] = None
    descending: bool = False
    nulls_last: bool = True


@dataclass
class LimitClause(Node):
    count: Optional[Expr] = None
    offset: Optional[Expr] = None


@dataclass
class Query(Node):
    """完整的 SELECT 查询。"""

    distinct: bool = False
    items: List[SelectItem] = field(default_factory=list)
    from_table: Optional[TableRef] = None
    joins: List[Join] = field(default_factory=list)
    where: Optional[Expr] = None
    group_by: List[Expr] = field(default_factory=list)
    having: Optional[Expr] = None
    order_by: List[OrderKey] = field(default_factory=list)
    limit: Optional[LimitClause] = None
    union: Optional["Query"] = None
    union_all: bool = False
