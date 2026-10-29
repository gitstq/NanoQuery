"""NanoQuery 词法分析器。

把 SQL 文本切分为 token 流。支持：

* 标准标识符与双引号引用标识符（``"order date"``）
* 单引号字符串字面量（``''`` 转义）
* 整数 / 浮点 / 科学计数法数字
* 行注释（``--``）与块注释（``/* */``）
* 全部保留关键字的大小写不敏感匹配

分析器同时保留每个 token 在源码中的**字符偏移**，用于生成高可读性的报错信息。
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional

from .types import ParseError

__all__ = ["Token", "KEYWORDS", "tokenize"]


class Token(NamedTuple):
    """一个词法单元。"""

    kind: str  # KEYWORD | IDENT | NUMBER | STRING | OP | PUNCT | EOF
    value: str
    pos: int


KEYWORDS = frozenset(
    {
        "SELECT", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "LIMIT",
        "OFFSET", "AS", "AND", "OR", "NOT", "NULL", "IS", "IN", "LIKE",
        "BETWEEN", "DISTINCT", "JOIN", "INNER", "LEFT", "RIGHT", "OUTER", "CROSS",
        "ON", "CASE", "WHEN", "THEN", "ELSE", "END", "ASC", "DESC", "TRUE",
        "FALSE", "CAST", "UNION", "ALL", "EXISTS", "WITH", "NULLS", "LAST",
        "FIRST", "ILIKE", "GLOB", "REGEXP",
    }
)

# 多字符运算符优先匹配，顺序很重要。
_OPERATORS = ("<=", ">=", "<>", "!=", "||", "==", "=", "<", ">", "+", "-", "*", "/", "%")

_PUNCT = set("(),.;")

_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_BODY = _IDENT_START | set("0123456789$")
_DIGITS = set("0123456789")


def tokenize(sql: str) -> List[Token]:
    """把 SQL 字符串转换为 token 列表（末尾追加 EOF token）。"""
    tokens: List[Token] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # 空白
        if ch.isspace():
            i += 1
            continue

        # 行注释
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
            continue

        # 块注释
        if ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                raise ParseError("块注释未闭合", i)
            i = end + 2
            continue

        # 字符串字面量
        if ch == "'":
            start = i
            i += 1
            buf: List[str] = []
            while True:
                if i >= n:
                    raise ParseError("字符串字面量未闭合", start)
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(Token("STRING", "".join(buf), start))
            continue

        # 引用标识符
        if ch == '"':
            start = i
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise ParseError("引用标识符未闭合", start)
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            tokens.append(Token("IDENT", "".join(buf), start))
            continue

        # 数字
        if ch in _DIGITS or (ch == "." and i + 1 < n and sql[i + 1] in _DIGITS):
            start = i
            seen_dot = False
            seen_exp = False
            while i < n:
                c = sql[i]
                if c in _DIGITS:
                    i += 1
                elif c == "." and not seen_dot and not seen_exp:
                    seen_dot = True
                    i += 1
                elif c in "eE" and not seen_exp:
                    if i + 1 < n and (sql[i + 1] in _DIGITS or sql[i + 1] in "+-"):
                        seen_exp = True
                        i += 2
                    else:
                        break
                elif c in "+-" and seen_exp and sql[i - 1] in "eE":
                    i += 1
                else:
                    break
            tokens.append(Token("NUMBER", sql[start:i], start))
            continue

        # 标识符 / 关键字
        if ch in _IDENT_START:
            start = i
            while i < n and sql[i] in _IDENT_BODY:
                i += 1
            word = sql[start:i]
            kind = "KEYWORD" if word.upper() in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word.upper() if kind == "KEYWORD" else word, start))
            continue

        # 运算符
        matched: Optional[str] = None
        for op in _OPERATORS:
            if sql.startswith(op, i):
                matched = op
                break
        if matched:
            tokens.append(Token("OP", matched, i))
            i += len(matched)
            continue

        if ch in _PUNCT:
            tokens.append(Token("PUNCT", ch, i))
            i += 1
            continue

        raise ParseError(f"无法识别的字符 {ch!r}", i)

    tokens.append(Token("EOF", "", n))
    return tokens
