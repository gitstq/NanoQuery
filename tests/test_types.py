"""类型系统与值语义测试。"""

from __future__ import annotations

import unittest

from nanoquery.types import (
    TYPE_BOOL,
    TYPE_FLOAT,
    TYPE_INT,
    TYPE_NULL,
    TYPE_STR,
    compare_values,
    infer_type,
    to_bool,
    value_repr,
    widen_type,
)


class TypeInference(unittest.TestCase):
    def test_infer_type(self):
        self.assertEqual(infer_type([None]), TYPE_NULL)
        self.assertEqual(infer_type([True]), TYPE_BOOL)
        self.assertEqual(infer_type([7]), TYPE_INT)
        self.assertEqual(infer_type([7.5]), TYPE_FLOAT)
        self.assertEqual(infer_type(["x"]), TYPE_STR)

    def test_infer_type_widening(self):
        self.assertEqual(infer_type([1, 2, 3]), TYPE_INT)
        self.assertEqual(infer_type([1, 2.5]), TYPE_FLOAT)
        self.assertEqual(infer_type([1, "a"]), TYPE_STR)
        self.assertEqual(infer_type([None, None, 5]), TYPE_INT)

    def test_widen_type(self):
        self.assertEqual(widen_type(TYPE_INT, TYPE_INT), TYPE_INT)
        self.assertEqual(widen_type(TYPE_INT, TYPE_FLOAT), TYPE_FLOAT)
        self.assertEqual(widen_type(TYPE_INT, TYPE_STR), TYPE_STR)
        self.assertEqual(widen_type(TYPE_NULL, TYPE_INT), TYPE_INT)
        self.assertEqual(widen_type(TYPE_STR, TYPE_BOOL), TYPE_STR)


class Comparison(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(compare_values(1, 2), -1)
        self.assertEqual(compare_values(2, 2), 0)
        self.assertEqual(compare_values(3, 2), 1)

    def test_numeric_string_affinity(self):
        # SQLite 风格亲和：'10' 与 10 按数值比较
        self.assertEqual(compare_values("10", 9), 1)
        self.assertEqual(compare_values(10, "9"), 1)

    def test_string_order(self):
        self.assertEqual(compare_values("a", "b"), -1)

    def test_null_propagates_as_unknown(self):
        # SQL 三值逻辑：与 NULL 的比较结果未知（None），而非大小关系
        self.assertIsNone(compare_values(None, 1))
        self.assertIsNone(compare_values(1, None))
        self.assertIsNone(compare_values(None, None))

    def test_bool_ordering(self):
        self.assertEqual(compare_values(False, True), -1)


class Coercion(unittest.TestCase):
    def test_to_bool(self):
        for truthy in (1, 1.0, "true", "TRUE", "1", "yes", "y", "t"):
            self.assertTrue(to_bool(truthy), repr(truthy))
        for falsy in (0, 0.0, "false", "0", "no", "n", "", None):
            self.assertFalse(to_bool(falsy), repr(falsy))


class Repr(unittest.TestCase):
    def test_value_repr(self):
        self.assertEqual(value_repr(None), "NULL")
        self.assertEqual(value_repr(True), "true")
        self.assertEqual(value_repr(7), "7")
        self.assertEqual(value_repr("a"), "a")


if __name__ == "__main__":
    unittest.main()
