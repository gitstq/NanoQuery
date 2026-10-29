"""执行引擎端到端测试（含聚合、JOIN、子查询、NULL 语义）。"""

from __future__ import annotations

import unittest

from nanoquery.types import ExecutionError, ResolveError

from helpers import TempDataMixin


class QueryBasics(TempDataMixin, unittest.TestCase):
    def test_select_star_row_count(self):
        rows = self.rows_of("SELECT * FROM people", people=self.paths["people.csv"])
        self.assertEqual(len(rows), 6)

    def test_projection_order(self):
        rows = self.rows_of("SELECT city, name FROM people", people=self.paths["people.csv"])
        self.assertEqual(list(rows[0].keys()), ["city", "name"])

    def test_where_filter(self):
        rows = self.rows_of(
            "SELECT name FROM people WHERE age > 30", people=self.paths["people.csv"]
        )
        self.assertEqual(sorted(r["name"] for r in rows), ["alice", "carol", "dave", "erin"])

    def test_group_by_aggregate(self):
        rows = self.rows_of(
            "SELECT city, COUNT(*) AS c FROM people GROUP BY city ORDER BY city",
            people=self.paths["people.csv"],
        )
        # 中文字面排序按 Unicode 码位：上海(U+4E0A) < 北京(U+5317) < 深圳(U+6DF1)
        self.assertEqual([(r["city"], r["c"]) for r in rows], [("上海", 2), ("北京", 3), ("深圳", 1)])

    def test_having(self):
        rows = self.rows_of(
            "SELECT city, COUNT(*) AS c FROM people GROUP BY city HAVING COUNT(*) > 1",
            people=self.paths["people.csv"],
        )
        self.assertEqual(sorted(r["city"] for r in rows), ["上海", "北京"])

    def test_order_by_multi_key(self):
        rows = self.rows_of(
            "SELECT name, age FROM people ORDER BY age ASC, name DESC",
            people=self.paths["people.csv"],
        )
        self.assertEqual(rows[0]["age"], 27)
        self.assertEqual(rows[0]["name"], "frank")

    def test_limit_offset(self):
        rows = self.rows_of(
            "SELECT name FROM people ORDER BY name LIMIT 2 OFFSET 1",
            people=self.paths["people.csv"],
        )
        self.assertEqual([r["name"] for r in rows], ["bob", "carol"])

    def test_distinct(self):
        rows = self.rows_of("SELECT DISTINCT city FROM people", people=self.paths["people.csv"])
        self.assertEqual(len(rows), 3)

    def test_constant_query(self):
        rows = self.rows_of("SELECT 1 AS a, 'x' AS b")
        self.assertEqual(rows, [{"a": 1, "b": "x"}])

    def test_arithmetic_and_alias(self):
        rows = self.rows_of(
            "SELECT name, score * 2 AS doubled FROM people WHERE name = 'alice'",
            people=self.paths["people.csv"],
        )
        self.assertAlmostEqual(rows[0]["doubled"], 177.0)


class AggregateFunctions(TempDataMixin, unittest.TestCase):
    def test_all_aggregates(self):
        row = self.rows_of(
            "SELECT COUNT(*) AS n, SUM(age) AS s, AVG(age) AS a, MIN(age) AS mn, "
            "MAX(age) AS mx, MEDIAN(age) AS med FROM people",
            people=self.paths["people.csv"],
        )[0]
        self.assertEqual(row["n"], 6)
        self.assertEqual(row["s"], 199)
        self.assertAlmostEqual(row["a"], 199 / 6, places=5)
        self.assertEqual(row["mn"], 27)
        self.assertEqual(row["mx"], 45)
        self.assertEqual(row["med"], 31)

    def test_count_column_ignores_null(self):
        path = self.write_csv("nulls.csv", ["v"], [["1"], ["NULL"], ["3"], ["NULL"]])
        self.assertEqual(self.scalar("SELECT COUNT(v) AS c FROM t", t=path), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) AS c FROM t", t=path), 4)

    def test_sum_of_nulls_is_null(self):
        path = self.write_csv("nulls2.csv", ["v"], [["NULL"], ["NULL"]])
        self.assertIsNone(self.scalar("SELECT SUM(v) AS s FROM t", t=path))

    def test_group_concat(self):
        row = self.rows_of(
            "SELECT city, GROUP_CONCAT(name) AS names FROM people WHERE city = '上海' GROUP BY city",
            people=self.paths["people.csv"],
        )[0]
        self.assertIn("bob", row["names"])
        self.assertIn("erin", row["names"])

    def test_stddev_variance(self):
        row = self.rows_of(
            "SELECT ROUND(STDDEV(age), 4) AS sd, ROUND(VARIANCE(age), 4) AS var FROM people",
            people=self.paths["people.csv"],
        )[0]
        self.assertGreater(row["var"], 0)
        self.assertGreater(row["sd"], 0)


class Predicates(TempDataMixin, unittest.TestCase):
    def test_between_inclusive(self):
        self.assertEqual(
            self.scalar("SELECT COUNT(*) AS c FROM people WHERE age BETWEEN 27 AND 31",
                        people=self.paths["people.csv"]), 4)

    def test_in_list(self):
        self.assertEqual(
            self.scalar("SELECT COUNT(*) AS c FROM people WHERE city IN ('北京', '深圳')",
                        people=self.paths["people.csv"]), 4)

    def test_not_in(self):
        self.assertEqual(
            self.scalar("SELECT COUNT(*) AS c FROM people WHERE city NOT IN ('北京')",
                        people=self.paths["people.csv"]), 3)

    def test_like(self):
        self.assertEqual(
            self.scalar("SELECT COUNT(*) AS c FROM people WHERE name LIKE 'a%'",
                        people=self.paths["people.csv"]), 1)

    def test_null_predicate(self):
        path = self.write_csv("n3.csv", ["v"], [["1"], ["NULL"]])
        self.assertEqual(self.scalar("SELECT COUNT(*) AS c FROM t WHERE v IS NULL", t=path), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) AS c FROM t WHERE v IS NOT NULL", t=path), 1)

    def test_case_expression(self):
        rows = self.rows_of(
            "SELECT name, CASE WHEN score >= 90 THEN 'A' WHEN score >= 80 THEN 'B' ELSE 'C' END AS grade "
            "FROM people ORDER BY name",
            people=self.paths["people.csv"],
        )
        grades = {r["name"]: r["grade"] for r in rows}
        self.assertEqual(grades["bob"], "A")
        self.assertEqual(grades["alice"], "B")
        self.assertEqual(grades["dave"], "C")


class Joins(TempDataMixin, unittest.TestCase):
    def test_inner_join(self):
        rows = self.rows_of(
            "SELECT p.name, c.region FROM people p JOIN city c ON p.city = c.city ORDER BY p.name",
            people=self.paths["people.csv"], city=self.paths["city.csv"],
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["region"], "华北")

    def test_left_join_keeps_unmatched(self):
        rows = self.rows_of(
            "SELECT c.city, COUNT(p.name) AS n FROM city c LEFT JOIN people p ON c.city = p.city "
            "GROUP BY c.city ORDER BY c.city",
            people=self.paths["people.csv"], city=self.paths["city.csv"],
        )
        by_city = {r["city"]: r["n"] for r in rows}
        self.assertEqual(by_city["广州"], 0)
        self.assertEqual(by_city["北京"], 3)

    def test_right_join(self):
        rows = self.rows_of(
            "SELECT c.city, p.name FROM people p RIGHT JOIN city c ON p.city = c.city ORDER BY c.city",
            people=self.paths["people.csv"], city=self.paths["city.csv"],
        )
        self.assertEqual({r["city"] for r in rows}, {"北京", "上海", "深圳", "广州"})

    def test_cross_join(self):
        self.assertEqual(
            self.scalar("SELECT COUNT(*) AS c FROM people CROSS JOIN city",
                        people=self.paths["people.csv"], city=self.paths["city.csv"]), 24)

    def test_join_with_extra_predicate(self):
        rows = self.rows_of(
            "SELECT p.name FROM people p JOIN city c ON p.city = c.city AND c.region = '华南' ORDER BY p.name",
            people=self.paths["people.csv"], city=self.paths["city.csv"],
        )
        self.assertEqual([r["name"] for r in rows], ["dave"])


class Subqueries(TempDataMixin, unittest.TestCase):
    def test_derived_table(self):
        rows = self.rows_of(
            "SELECT city, c FROM (SELECT city, COUNT(*) AS c FROM people GROUP BY city) WHERE c >= 2 "
            "ORDER BY city",
            people=self.paths["people.csv"],
        )
        self.assertEqual(sorted(r["city"] for r in rows), ["上海", "北京"])

    def test_union_all(self):
        rows = self.rows_of(
            "SELECT city FROM people WHERE city = '北京' UNION ALL SELECT city FROM people WHERE city = '深圳'",
            people=self.paths["people.csv"],
        )
        self.assertEqual(len(rows), 4)

    def test_union_distinct(self):
        rows = self.rows_of(
            "SELECT city FROM people WHERE city = '北京' UNION SELECT city FROM people WHERE city = '北京'",
            people=self.paths["people.csv"],
        )
        self.assertEqual(len(rows), 1)


class ErrorHandling(TempDataMixin, unittest.TestCase):
    def test_unknown_table(self):
        with self.assertRaises(ResolveError):
            self.rows_of("SELECT * FROM nope")

    def test_unknown_column(self):
        with self.assertRaises(ResolveError):
            self.rows_of("SELECT nope FROM people", people=self.paths["people.csv"])

    def test_ambiguous_column(self):
        with self.assertRaises(ResolveError):
            self.rows_of(
                "SELECT city FROM people p JOIN city c ON p.city = c.city",
                people=self.paths["people.csv"], city=self.paths["city.csv"],
            )

    def test_non_aggregate_column_in_group(self):
        with self.assertRaises(ExecutionError):
            self.rows_of("SELECT name, COUNT(*) FROM people GROUP BY city",
                         people=self.paths["people.csv"])


if __name__ == "__main__":
    unittest.main()
