"""语法解析器测试。"""

from __future__ import annotations

import unittest

from nanoquery.parser import parse
from nanoquery.executor import unparse
from nanoquery.types import ParseError


class ParserStructure(unittest.TestCase):
    def test_select_star(self):
        query = parse("SELECT * FROM t")
        self.assertEqual(len(query.items), 1)
        self.assertEqual(query.from_table.name, "t")

    def test_alias_forms(self):
        for sql in ("SELECT a AS x FROM t", "SELECT a x FROM t"):
            self.assertEqual(parse(sql).items[0].alias, "x", sql)

    def test_where_and_group(self):
        query = parse("SELECT city, COUNT(*) AS c FROM t WHERE age > 20 GROUP BY city HAVING COUNT(*) > 1")
        self.assertIsNotNone(query.where)
        self.assertEqual(len(query.group_by), 1)
        self.assertIsNotNone(query.having)

    def test_order_nulls(self):
        query = parse("SELECT a FROM t ORDER BY a DESC NULLS LAST, b ASC NULLS FIRST")
        self.assertTrue(query.order_by[0].descending)
        self.assertTrue(query.order_by[0].nulls_last)
        self.assertFalse(query.order_by[1].nulls_last)
        # 缺省约定：NULL 排在最后（与多数分析型数据库一致）
        defaulted = parse("SELECT a FROM t ORDER BY a")
        self.assertTrue(defaulted.order_by[0].nulls_last)

    def test_limit_offset(self):
        query = parse("SELECT a FROM t LIMIT 10 OFFSET 5")
        self.assertEqual(unparse(query.limit.count), "10")
        self.assertEqual(unparse(query.limit.offset), "5")

    def test_distinct(self):
        self.assertTrue(parse("SELECT DISTINCT city FROM t").distinct)

    def test_join_kinds(self):
        for sql, kind in (
            ("SELECT * FROM a JOIN b ON a.id = b.id", "INNER"),
            ("SELECT * FROM a LEFT JOIN b ON a.id = b.id", "LEFT"),
            ("SELECT * FROM a RIGHT JOIN b ON a.id = b.id", "RIGHT"),
            ("SELECT * FROM a CROSS JOIN b", "CROSS"),
        ):
            query = parse(sql)
            self.assertEqual(query.joins[0].kind, kind, sql)

    def test_union(self):
        query = parse("SELECT a FROM t UNION ALL SELECT b FROM u")
        self.assertIsNotNone(query.union)
        self.assertTrue(query.union_all)
        self.assertFalse(parse("SELECT a FROM t UNION SELECT b FROM u").union_all)

    def test_case_expression(self):
        query = parse("SELECT CASE WHEN a > 1 THEN 'x' WHEN a > 0 THEN 'y' ELSE 'z' END AS g FROM t")
        self.assertEqual(query.items[0].alias, "g")

    def test_cast_expression(self):
        query = parse("SELECT CAST(a AS INT) AS b FROM t")
        self.assertEqual(query.items[0].alias, "b")

    def test_derived_table(self):
        query = parse("SELECT x FROM (SELECT a AS x FROM t)")
        self.assertIsNotNone(query.from_table.query)

    def test_between_and_in(self):
        parse("SELECT * FROM t WHERE a BETWEEN 1 AND 9 AND b IN (1, 2, 3)")
        parse("SELECT * FROM t WHERE a NOT IN (1, 2) AND b NOT BETWEEN 1 AND 2")

    def test_like(self):
        parse("SELECT * FROM t WHERE name LIKE '%a%' AND name NOT LIKE 'b%'")

    def test_nested_path_column(self):
        # 多级路径：首段作表别名，其余拼为列路径
        self.assertEqual(parse("SELECT user.name FROM events").items[0].expr.table, "user")
        three = parse("SELECT events.user.name FROM events").items[0].expr
        self.assertEqual((three.table, three.name), ("events", "user.name"))

    def test_scalar_subquery_rejected(self):
        with self.assertRaises(ParseError):
            parse("SELECT (SELECT 1) AS a")

    def test_dangling_operator(self):
        with self.assertRaises(ParseError):
            parse("SELECT a FROM t WHERE")

    def test_unclosed_paren(self):
        with self.assertRaises(ParseError):
            parse("SELECT UPPER(a FROM t")

    def test_unparse_roundtrip(self):
        sql = "SELECT city, COUNT(*) AS c FROM t WHERE age > 20 GROUP BY city ORDER BY c DESC LIMIT 3"
        self.assertEqual(unparse_items(sql), "city COUNT(*)")


def unparse_items(sql: str) -> str:
    """把 SELECT 列表的表达式还原为文本，用于验证 AST 可读性。"""
    return " ".join(unparse(item.expr) for item in parse(sql).items)


if __name__ == "__main__":
    unittest.main()
