"""NanoQuery 语法分析器（递归下降）。

将 :mod:`nanoquery.lexer` 产生的 token 流转换为 :mod:`nanoquery.ast` 定义的语法树。

支持的语法子集::

    query        := select_core { UNION [ALL] select_core }
    select_core  := SELECT [DISTINCT] select_list
                    FROM table_ref { join_clause }
                    [ WHERE expr ]
                    [ GROUP BY expr_list [ HAVING expr ] ]
                    [ ORDER BY order_key { ',' order_key } ]
                    [ LIMIT expr [ OFFSET expr ] ]
    table_ref    := ident [ [AS] alias ]
                  | ident '(' string ')' [ [AS] alias ]       -- read_csv('x.csv')
                  | '(' query ')' [AS] alias
    join_clause  := [INNER|LEFT|RIGHT] [OUTER] JOIN table_ref [ON expr]
                  | CROSS JOIN table_ref
    expr         := or_expr

运算符优先级从低到高依次为：``OR`` < ``AND`` < ``NOT`` < 比较 < ``||``
< ``+ -`` < ``* / %`` < 一元 ``- +``。
"""

from __future__ import annotations

from typing import List, Optional

from .ast import (
    Between, BinaryOp, CaseExpr, CastExpr, ColumnRef, Expr, FunctionCall, InList,
    IsNull, Join, Like, LimitClause, Literal, LogicalOp, OrderKey, Query,
    SelectItem, StarExpr, TableRef, UnaryOp,
)
from .lexer import tokenize
from .types import ParseError

__all__ = ["Parser", "parse"]

# 聚合函数名集合，供解析器做 ``COUNT(*)`` 之类的特判。
_AGGREGATES = frozenset(
    {"COUNT", "SUM", "AVG", "MIN", "MAX", "MEDIAN", "STDDEV", "VARIANCE", "GROUP_CONCAT"}
)

_COMPARISON_OPS = frozenset({"=", "==", "!=", "<>", "<", "<=", ">", ">="})

_TYPE_KEYWORDS = frozenset(
    {"INT", "INTEGER", "BIGINT", "FLOAT", "DOUBLE", "REAL", "TEXT", "STRING",
     "STR", "BOOL", "BOOLEAN", "NUMERIC", "DECIMAL"}
)


class Parser:
    """递归下降解析器。一般通过 :func:`parse` 便捷函数使用。"""

    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.tokens = tokenize(sql)
        self.pos = 0

    # ------------------------------------------------------------------ #
    # token 辅助
    # ------------------------------------------------------------------ #

    @property
    def current(self):
        return self.tokens[self.pos]

    def _peek(self, offset: int = 0):
        index = self.pos + offset
        if index >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[index]

    def _advance(self):
        token = self.tokens[self.pos]
        if token.kind != "EOF":
            self.pos += 1
        return token

    def _accept(self, kind: str, value: Optional[str] = None) -> bool:
        token = self.current
        if token.kind != kind:
            return False
        if value is not None and token.value != value:
            return False
        self._advance()
        return True

    def _accept_keyword(self, *keywords: str) -> Optional[str]:
        token = self.current
        if token.kind == "KEYWORD" and token.value in keywords:
            self._advance()
            return token.value
        if token.kind == "IDENT" and token.value.upper() in keywords:
            self._advance()
            return token.value.upper()
        return None

    def _expect(self, kind: str, value: Optional[str] = None):
        token = self.current
        if token.kind != kind or (value is not None and token.value != value):
            raise ParseError(
                f"期望 {value or kind}，实际得到 {token.value or '<结束>'!r}".replace("!'", "'"),
                token.pos,
            )
        return self._advance()

    def _expect_keyword(self, *keywords: str) -> str:
        result = self._accept_keyword(*keywords)
        if result is None:
            token = self.current
            raise ParseError(
                f"期望关键字 {'/'.join(keywords)}，实际得到 {token.value or '<结束>'}",
                token.pos,
            )
        return result

    # ------------------------------------------------------------------ #
    # 顶层入口
    # ------------------------------------------------------------------ #

    def parse(self) -> Query:
        query = self._parse_select_core()
        while True:
            if self._accept_keyword("UNION"):
                union_all = bool(self._accept_keyword("ALL"))
                right = self._parse_select_core()
                # 左深拼接，保证多段 UNION 顺序执行。
                node = query
                while node.union is not None:
                    node = node.union
                node.union = right
                node.union_all = union_all
                continue
            break
        if self.current.kind != "EOF":
            raise ParseError(f"语句结束后存在多余内容：{self.current.value!r}", self.current.pos)
        return query

    def _parse_select_core(self) -> Query:
        self._expect_keyword("SELECT")
        query = Query(pos=self.tokens[max(self.pos - 1, 0)].pos)
        query.distinct = bool(self._accept_keyword("DISTINCT"))

        query.items = self._parse_select_list()

        if self._accept_keyword("FROM"):
            query.from_table = self._parse_table_ref()
            query.joins = self._parse_joins()
        else:
            # 允许 SELECT 1 这类无 FROM 的表达式查询。
            query.from_table = None

        if self._accept_keyword("WHERE"):
            query.where = self.parse_expr()

        if self._accept_keyword("GROUP"):
            self._expect_keyword("BY")
            query.group_by = self._parse_expr_list()

        if self._accept_keyword("HAVING"):
            query.having = self.parse_expr()

        if self._accept_keyword("ORDER"):
            self._expect_keyword("BY")
            query.order_by = self._parse_order_list()

        if self._accept_keyword("LIMIT"):
            clause = LimitClause(pos=self.current.pos)
            clause.count = self.parse_expr()
            if self._accept_keyword("OFFSET"):
                clause.offset = self.parse_expr()
            query.limit = clause
        elif self._accept_keyword("OFFSET"):
            clause = LimitClause(pos=self.current.pos)
            clause.offset = self.parse_expr()
            query.limit = clause

        return query

    # ------------------------------------------------------------------ #
    # 选择列表 / FROM / JOIN
    # ------------------------------------------------------------------ #

    def _parse_select_list(self) -> List[SelectItem]:
        items: List[SelectItem] = []
        while True:
            pos = self.current.pos
            if self._accept("OP", "*"):
                items.append(SelectItem(expr=StarExpr(pos=pos), pos=pos))
            else:
                expr = self.parse_expr()
                alias = None
                if self._accept_keyword("AS"):
                    token = self.current
                    if token.kind not in ("IDENT", "KEYWORD"):
                        raise ParseError(f"AS 之后需要别名，实际得到 {token.value!r}", token.pos)
                    alias = self._advance().value
                elif self.current.kind == "IDENT":
                    # 隐式别名：SELECT price amount
                    alias = self._advance().value
                items.append(SelectItem(expr=expr, alias=alias, pos=pos))
            if not self._accept("PUNCT", ","):
                break
        return items

    def _parse_table_ref(self) -> TableRef:
        pos = self.current.pos
        if self._accept("PUNCT", "("):
            inner = self._parse_select_core()
            self._expect("PUNCT", ")")
            ref = TableRef(name="", query=inner, pos=pos)
            ref.alias = self._parse_optional_alias()
            return ref

        token = self.current
        if token.kind not in ("IDENT", "KEYWORD"):
            raise ParseError(f"FROM 之后需要表名，实际得到 {token.value or '<结束>'!r}", token.pos)
        name = self._advance().value

        ref = TableRef(name=name, pos=pos)
        # 文件函数形式：read_csv('path') / csv('path')
        if self._accept("PUNCT", "("):
            fmt = name.upper()
            if fmt.startswith("READ_"):
                fmt = fmt[5:]
            path_token = self.current
            if path_token.kind != "STRING":
                raise ParseError(f"{name}(...) 需要一个文件路径字符串", path_token.pos)
            self._advance()
            self._expect("PUNCT", ")")
            ref.fmt = fmt.lower()
            ref.path = path_token.value
            ref.name = ""
        ref.alias = self._parse_optional_alias()
        if ref.alias is None and ref.query is not None:
            raise ParseError("子查询必须指定别名", pos)
        return ref

    def _parse_optional_alias(self) -> Optional[str]:
        if self._accept_keyword("AS"):
            token = self.current
            if token.kind not in ("IDENT", "KEYWORD"):
                raise ParseError(f"AS 之后需要别名，实际得到 {token.value!r}", token.pos)
            return self._advance().value
        token = self.current
        # 保留字（WHERE/JOIN/...）不能作为隐式别名
        if token.kind == "IDENT":
            return self._advance().value
        return None

    def _parse_joins(self) -> List[Join]:
        joins: List[Join] = []
        while True:
            kind: Optional[str] = None
            if self._accept_keyword("INNER"):
                kind = "INNER"
            elif self._accept_keyword("LEFT"):
                kind = "LEFT"
            elif self._accept_keyword("RIGHT"):
                kind = "RIGHT"
            elif self._accept_keyword("CROSS"):
                kind = "CROSS"

            if kind == "CROSS":
                self._expect_keyword("JOIN")
                joins.append(Join(kind="CROSS", table=self._parse_table_ref(), pos=self.current.pos))
                continue

            if self._accept_keyword("JOIN"):
                joins.append(
                    Join(kind=kind or "INNER", table=self._parse_table_ref(), pos=self.current.pos)
                )
                if self._accept_keyword("ON"):
                    joins[-1].on = self.parse_expr()
                continue

            if self._accept_keyword("OUTER"):
                if not self._accept_keyword("JOIN"):
                    raise ParseError("OUTER 之后需要 JOIN", self.current.pos)
                joins.append(
                    Join(kind=kind or "LEFT", table=self._parse_table_ref(), pos=self.current.pos)
                )
                if self._accept_keyword("ON"):
                    joins[-1].on = self.parse_expr()
                continue
            break
        return joins

    def _parse_order_list(self) -> List[OrderKey]:
        keys: List[OrderKey] = []
        while True:
            pos = self.current.pos
            expr = self.parse_expr()
            descending = bool(self._accept_keyword("DESC"))
            if not descending:
                self._accept_keyword("ASC")
            nulls_last = True
            if self._accept_keyword("NULLS"):
                if self._accept_keyword("LAST"):
                    nulls_last = True
                elif self._accept_keyword("FIRST"):
                    nulls_last = False
                else:
                    raise ParseError("NULLS 之后需要 FIRST 或 LAST", self.current.pos)
            keys.append(OrderKey(expr=expr, descending=descending, nulls_last=nulls_last, pos=pos))
            if not self._accept("PUNCT", ","):
                break
        return keys

    def _parse_expr_list(self) -> List[Expr]:
        exprs = [self.parse_expr()]
        while self._accept("PUNCT", ","):
            exprs.append(self.parse_expr())
        return exprs

    # ------------------------------------------------------------------ #
    # 表达式
    # ------------------------------------------------------------------ #

    def parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        operands = [left]
        while self._accept_keyword("OR"):
            operands.append(self._parse_and())
        if len(operands) == 1:
            return left
        return LogicalOp(op="OR", operands=operands, pos=left.pos)

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        operands = [left]
        while self._accept_keyword("AND"):
            operands.append(self._parse_not())
        if len(operands) == 1:
            return left
        return LogicalOp(op="AND", operands=operands, pos=left.pos)

    def _parse_not(self) -> Expr:
        pos = self.current.pos
        if self._accept_keyword("NOT"):
            return UnaryOp(op="NOT", operand=self._parse_not(), pos=pos)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_concat()
        pos = self.current.pos

        token = self.current
        if token.kind == "OP" and token.value in _COMPARISON_OPS:
            self._advance()
            op = "==" if token.value == "=" else token.value
            right = self._parse_concat()
            return BinaryOp(op=op if op != "==" else "=", left=left, right=right, pos=pos)

        if self._accept_keyword("IS"):
            negated = bool(self._accept_keyword("NOT"))
            self._expect_keyword("NULL")
            return IsNull(operand=left, negated=negated, pos=pos)

        negated = False
        save = self.pos
        if self._accept_keyword("NOT"):
            negated = True

        if self._accept_keyword("IN"):
            self._expect("PUNCT", "(")
            items = self._parse_expr_list()
            self._expect("PUNCT", ")")
            return InList(operand=left, items=items, negated=negated, pos=pos)

        if self._accept_keyword("LIKE", "ILIKE"):
            ci = self.tokens[self.pos - 1].value == "ILIKE"
            pattern = self._parse_concat()
            return Like(operand=left, pattern=pattern, negated=negated, case_insensitive=ci, pos=pos)

        if self._accept_keyword("BETWEEN"):
            low = self._parse_concat()
            self._expect_keyword("AND")
            high = self._parse_concat()
            return Between(operand=left, low=low, high=high, negated=negated, pos=pos)

        if negated:
            self.pos = save  # NOT 属于更高优先级，回退交给 _parse_not
        return left

    def _parse_concat(self) -> Expr:
        left = self._parse_add()
        while self._accept("OP", "||"):
            pos = self.current.pos
            right = self._parse_add()
            left = BinaryOp(op="||", left=left, right=right, pos=pos)
        return left

    def _parse_add(self) -> Expr:
        left = self._parse_mul()
        while True:
            pos = self.current.pos
            if self._accept("OP", "+"):
                left = BinaryOp(op="+", left=left, right=self._parse_mul(), pos=pos)
            elif self._accept("OP", "-"):
                left = BinaryOp(op="-", left=left, right=self._parse_mul(), pos=pos)
            else:
                return left

    def _parse_mul(self) -> Expr:
        left = self._parse_unary()
        while True:
            pos = self.current.pos
            if self._accept("OP", "*"):
                left = BinaryOp(op="*", left=left, right=self._parse_unary(), pos=pos)
            elif self._accept("OP", "/"):
                left = BinaryOp(op="/", left=left, right=self._parse_unary(), pos=pos)
            elif self._accept("OP", "%"):
                left = BinaryOp(op="%", left=left, right=self._parse_unary(), pos=pos)
            else:
                return left

    def _parse_unary(self) -> Expr:
        pos = self.current.pos
        if self._accept("OP", "-"):
            return UnaryOp(op="-", operand=self._parse_unary(), pos=pos)
        if self._accept("OP", "+"):
            return self._parse_unary()
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        token = self.current
        pos = token.pos

        if token.kind == "NUMBER":
            self._advance()
            text = token.value
            if "." in text or "e" in text or "E" in text:
                return Literal(value=float(text), pos=pos)
            return Literal(value=int(text), pos=pos)

        if token.kind == "STRING":
            self._advance()
            return Literal(value=token.value, pos=pos)

        if token.kind == "KEYWORD":
            if token.value == "NULL":
                self._advance()
                return Literal(value=None, pos=pos)
            if token.value == "TRUE":
                self._advance()
                return Literal(value=True, pos=pos)
            if token.value == "FALSE":
                self._advance()
                return Literal(value=False, pos=pos)
            if token.value == "CASE":
                return self._parse_case()
            if token.value == "CAST":
                return self._parse_cast()
            if token.value == "EXISTS" or token.value == "WITH":
                raise ParseError(f"暂不支持 {token.value} 语法", pos)

        if token.kind == "PUNCT" and token.value == "(":
            self._advance()
            if self.current.kind == "KEYWORD" and self.current.value == "SELECT":
                raise ParseError(
                    "暂不支持标量子查询；FROM 子句中的派生表（子查询）已受支持", pos
                )
            expr = self.parse_expr()
            self._expect("PUNCT", ")")
            return expr

        if token.kind == "IDENT":
            self._advance()
            name = token.value
            if self._accept("PUNCT", "("):
                return self._parse_function_args(name, pos)
            if self._accept("PUNCT", "."):
                column_token = self.current
                if column_token.kind == "OP" and column_token.value == "*":
                    self._advance()
                    return StarExpr(table=name, pos=pos)
                if column_token.kind not in ("IDENT", "KEYWORD"):
                    raise ParseError(f"'.' 之后需要列名，实际得到 {column_token.value!r}", column_token.pos)
                # 支持多级限定名 / 嵌套字段（如 t.user.name）：首段作表别名，
                # 其余按字面量拼成列名，交由 Scope 做后缀匹配。
                parts: List[str] = []
                while True:
                    token = self.current
                    if token.kind not in ("IDENT", "KEYWORD"):
                        raise ParseError(f"'.' 之后需要列名，实际得到 {token.value!r}", token.pos)
                    parts.append(token.value)
                    self._advance()
                    if self._accept("PUNCT", "."):
                        continue
                    break
                return ColumnRef(name=".".join(parts), table=name, pos=pos)
            return ColumnRef(name=name, pos=pos)

        raise ParseError(f"无法解析的表达式：{token.value or '<结束>'!r}", pos)

    def _parse_function_args(self, name: str, pos: int) -> Expr:
        distinct = False
        star = False
        args: List[Expr] = []
        upper = name.upper()

        if upper in _AGGREGATES:
            if self._accept("OP", "*"):
                star = True
                self._expect("PUNCT", ")")
                return FunctionCall(name=upper, args=[], star=True, pos=pos)
            if self._accept_keyword("DISTINCT"):
                distinct = True

        if not self._accept("PUNCT", ")"):
            args = self._parse_expr_list()
            self._expect("PUNCT", ")")
        return FunctionCall(name=upper, args=args, distinct=distinct, pos=pos)

    def _parse_case(self) -> Expr:
        pos = self.current.pos
        self._expect_keyword("CASE")
        operand: Optional[Expr] = None
        if not self._accept_keyword("WHEN"):
            operand = self.parse_expr()
            self._expect_keyword("WHEN")
        whens = []
        while True:
            when_expr = self.parse_expr()
            self._expect_keyword("THEN")
            then_expr = self.parse_expr()
            whens.append((when_expr, then_expr))
            if self._accept_keyword("WHEN"):
                continue
            break
        default = None
        if self._accept_keyword("ELSE"):
            default = self.parse_expr()
        self._expect_keyword("END")
        return CaseExpr(operand=operand, whens=whens, default=default, pos=pos)

    def _parse_cast(self) -> Expr:
        pos = self.current.pos
        self._expect_keyword("CAST")
        self._expect("PUNCT", "(")
        operand = self.parse_expr()
        self._expect_keyword("AS")
        token = self.current
        if token.kind not in ("IDENT", "KEYWORD") or token.value.upper() not in _TYPE_KEYWORDS:
            raise ParseError(f"不支持的 CAST 目标类型 {token.value!r}", token.pos)
        self._advance()
        self._expect("PUNCT", ")")
        return CastExpr(operand=operand, target=token.value.upper(), pos=pos)


def parse(sql: str) -> Query:
    """把 SQL 文本解析为 :class:`~nanoquery.ast.Query`。"""
    if not sql or not sql.strip():
        raise ParseError("SQL 语句为空")
    return Parser(sql).parse()
