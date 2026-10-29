"""词法分析器测试。"""

from __future__ import annotations

import unittest

from nanoquery.lexer import tokenize
from nanoquery.types import ParseError


def tokens(sql: str) -> list:
    return [t for t in tokenize(sql) if t.kind != "EOF"]


def kinds(sql: str) -> list:
    return [t.kind for t in tokens(sql)]


def values(sql: str) -> list:
    return [t.value for t in tokens(sql)]


class LexerBasics(unittest.TestCase):
    def test_simple_select(self):
        self.assertEqual(values("SELECT a FROM t"), ["SELECT", "a", "FROM", "t"])

    def test_keywords_case_insensitive(self):
        self.assertEqual(values("select a from t where a > 1")[0], "SELECT")
        self.assertEqual(kinds("select"), ["KEYWORD"])

    def test_identifiers_and_numbers(self):
        # 负号由语法层的一元运算符处理，词法层只产出无符号数字
        nums = [t.value for t in tokens("SELECT 12, 3.5, -2, 1e3 FROM t") if t.kind == "NUMBER"]
        self.assertEqual(nums, ["12", "3.5", "2", "1e3"])

    def test_string_literal(self):
        self.assertIn("北京", values("SELECT '北京'"))

    def test_string_escape_by_doubling(self):
        self.assertIn("a'b", values("SELECT 'a''b'"))

    def test_quoted_identifier(self):
        self.assertIn("user.name", [t.value for t in tokens('SELECT "user.name" FROM t')])

    def test_operators(self):
        for op in ("<=", "<>", "!=", "||", ">=", "=", "%"):
            self.assertIn(op, values(f"SELECT a {op} b"))

    def test_line_comment(self):
        self.assertEqual(values("SELECT a -- 注释\nFROM t"), ["SELECT", "a", "FROM", "t"])

    def test_block_comment(self):
        self.assertEqual(values("SELECT /* 注释 */ a FROM t"), ["SELECT", "a", "FROM", "t"])

    def test_positions_monotonic(self):
        positions = [t.pos for t in tokens("SELECT a, b FROM t WHERE a > 1")]
        self.assertEqual(positions, sorted(positions))

    def test_unterminated_string(self):
        with self.assertRaises(ParseError):
            tokenize("SELECT 'abc")

    def test_unterminated_block_comment(self):
        with self.assertRaises(ParseError):
            tokenize("SELECT /* abc")


if __name__ == "__main__":
    unittest.main()
