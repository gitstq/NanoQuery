"""内置函数测试（标量函数与聚合函数）。"""

from __future__ import annotations

import unittest

from nanoquery.functions import (
    AGGREGATE_FUNCTIONS,
    DISTINCT_AGGREGATES,
    SCALAR_FUNCTIONS,
    LikeMatcher,
)


class ScalarFunctions(unittest.TestCase):
    def _call(self, name: str, *args):
        return SCALAR_FUNCTIONS[name](*args)

    def test_string_functions(self):
        self.assertEqual(self._call("UPPER", "abc"), "ABC")
        self.assertEqual(self._call("LOWER", "ABC"), "abc")
        self.assertEqual(self._call("LENGTH", "中文ab"), 4)
        self.assertEqual(self._call("TRIM", "  a  "), "a")
        self.assertEqual(self._call("SUBSTR", "abcdef", 2, 3), "bcd")
        self.assertEqual(self._call("REPLACE", "a-b", "-", "+"), "a+b")
        self.assertEqual(self._call("CONCAT", "a", "b"), "ab")
        self.assertEqual(self._call("CONCAT_WS", "-", "a", "b"), "a-b")
        self.assertEqual(self._call("REVERSE", "abc"), "cba")
        self.assertEqual(self._call("LEFT", "abcdef", 3), "abc")

    def test_numeric_functions(self):
        self.assertEqual(self._call("ABS", -3), 3)
        self.assertEqual(self._call("ROUND", 3.14159, 2), 3.14)
        self.assertEqual(self._call("CEIL", 3.2), 4)
        self.assertEqual(self._call("FLOOR", 3.8), 3)
        self.assertAlmostEqual(self._call("SQRT", 9), 3.0)
        self.assertEqual(self._call("POWER", 2, 10), 1024)
        self.assertEqual(self._call("MOD", 7, 3), 1)

    def test_null_handling(self):
        self.assertIsNone(self._call("UPPER", None))
        self.assertIsNone(self._call("ABS", None))
        self.assertEqual(self._call("COALESCE", None, None, 5), 5)
        self.assertEqual(self._call("IFNULL", None, 9), 9)
        self.assertIsNone(self._call("NULLIF", 3, 3))
        self.assertEqual(self._call("NULLIF", 3, 4), 3)

    def test_extremes(self):
        self.assertEqual(self._call("GREATEST", 1, 5, 3), 5)
        self.assertEqual(self._call("LEAST", 1, 5, 3), 1)

    def test_typeof(self):
        self.assertEqual(self._call("TYPEOF", 1), "INT")
        self.assertEqual(self._call("TYPEOF", "a"), "STR")


class LikeMatching(unittest.TestCase):
    def test_wildcards(self):
        self.assertTrue(LikeMatcher.match("xax", "%a%"))
        self.assertTrue(LikeMatcher.match("abc", "a%"))
        self.assertFalse(LikeMatcher.match("ba", "a%"))
        self.assertTrue(LikeMatcher.match("ab", "a_"))
        self.assertFalse(LikeMatcher.match("abc", "a_"))

    def test_case_sensitive_by_default(self):
        self.assertFalse(LikeMatcher.match("abc", "ABC"))
        self.assertTrue(LikeMatcher.match("abc", "ABC", True))

    def test_null_returns_unknown(self):
        self.assertIsNone(LikeMatcher.match(None, "%"))
        self.assertIsNone(LikeMatcher.match("a", None))


class AggregateFunctions(unittest.TestCase):
    def _agg(self, name: str, values):
        agg = AGGREGATE_FUNCTIONS[name]()
        for value in values:
            agg.update(value)
        return agg.finalize()

    def test_basic(self):
        self.assertEqual(self._agg("COUNT", [1, 2, 3]), 3)
        self.assertEqual(self._agg("SUM", [1, 2, 3]), 6)
        self.assertAlmostEqual(self._agg("AVG", [1, 2, 3]), 2.0)
        self.assertEqual(self._agg("MIN", [3, 1, 2]), 1)
        self.assertEqual(self._agg("MAX", [3, 1, 2]), 3)

    def test_empty(self):
        self.assertEqual(self._agg("COUNT", []), 0)
        self.assertIsNone(self._agg("SUM", []))
        self.assertIsNone(self._agg("AVG", []))

    def test_nulls_ignored(self):
        self.assertEqual(self._agg("SUM", [1, None, 3]), 4)
        self.assertEqual(self._agg("COUNT", [1, None, 3]), 2)

    def test_median(self):
        self.assertEqual(self._agg("MEDIAN", [3, 1, 2]), 2)
        self.assertEqual(self._agg("MEDIAN", [4, 1, 3, 2]), 2.5)

    def test_group_concat(self):
        self.assertEqual(self._agg("GROUP_CONCAT", ["a", "b"]), "a,b")

    def test_registry_complete(self):
        for name in ("COUNT", "SUM", "AVG", "MIN", "MAX", "MEDIAN", "VARIANCE", "STDDEV", "GROUP_CONCAT"):
            self.assertIn(name, AGGREGATE_FUNCTIONS)
        for name in ("UPPER", "LOWER", "ROUND", "COALESCE", "TYPEOF"):
            self.assertIn(name, SCALAR_FUNCTIONS)
        self.assertIn("COUNT", DISTINCT_AGGREGATES)


if __name__ == "__main__":
    unittest.main()
