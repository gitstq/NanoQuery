"""数据源（CSV / JSONL / 日志 / .nq）测试。"""

from __future__ import annotations

import unittest

from nanoquery.sources import detect_format, infer_value, source_for_path
from nanoquery.types import StorageError

from helpers import TempDataMixin


class ValueInference(unittest.TestCase):
    def test_null_forms(self):
        for text in ("NULL", "null", "", "\\N", "None"):
            self.assertIsNone(infer_value(text), repr(text))

    def test_bool(self):
        self.assertIs(infer_value("true"), True)
        self.assertIs(infer_value("false"), False)

    def test_numbers(self):
        self.assertEqual(infer_value("42"), 42)
        self.assertEqual(infer_value("3.14"), 3.14)
        self.assertEqual(infer_value("-7"), -7)
        self.assertEqual(infer_value("1e3"), 1000.0)

    def test_string_fallback(self):
        self.assertEqual(infer_value("abc"), "abc")


class FormatDetection(unittest.TestCase):
    def test_by_extension(self):
        self.assertEqual(detect_format("a.csv"), "csv")
        self.assertEqual(detect_format("a.jsonl"), "jsonl")
        self.assertEqual(detect_format("a.ndjson"), "jsonl")
        self.assertEqual(detect_format("a.log"), "log")
        self.assertEqual(detect_format("a.nq"), "nq")

    def test_uppercase_extension(self):
        self.assertEqual(detect_format("A.CSV"), "csv")

    def test_unknown_extension_falls_back_to_csv(self):
        # 无法识别的扩展名按 CSV 兜底，保证任意文本文件都能被查询
        self.assertEqual(detect_format("a.unknownfmt"), "csv")

    def test_explicit_bad_format(self):
        with self.assertRaises(StorageError):
            detect_format("a.csv", fmt="parquet")


class Sources(TempDataMixin, unittest.TestCase):
    def test_csv_schema_and_types(self):
        source = source_for_path(self.paths["people.csv"])
        schema = {c["name"]: c["type"] for c in source.schema()}
        self.assertEqual(schema["name"], "STR")
        self.assertEqual(schema["age"], "INT")
        self.assertEqual(schema["score"], "FLOAT")

    def test_csv_batching(self):
        source = source_for_path(self.paths["people.csv"], batch_size=4)
        sizes = [b.row_count for b in source.batches()]
        self.assertEqual(sum(sizes), 6)
        self.assertTrue(all(s <= 4 for s in sizes))

    def test_csv_no_header(self):
        path = self.dir + "/raw.csv"
        with open(path, "w", encoding="utf-8", newline="") as handle:
            import csv as _csv
            _csv.writer(handle).writerows([["a", "1"], ["b", "2"]])
        source = source_for_path(path, has_header=False)
        names = [c["name"] for c in source.schema()]
        self.assertEqual(names[:2], ["c0", "c1"])

    def test_csv_custom_delimiter(self):
        path = self.dir + "/semi.csv"
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("a;b\n1;2\n")
        source = source_for_path(path, delimiter=";")
        self.assertEqual([c["name"] for c in source.schema()], ["a", "b"])

    def test_jsonl_flattens_nested(self):
        source = source_for_path(self.paths["events.jsonl"])
        names = [c["name"] for c in source.schema()]
        self.assertIn("user.name", names)
        self.assertIn("user.vip", names)

    def test_jsonl_rows(self):
        source = source_for_path(self.paths["events.jsonl"])
        rows = [r for b in source.batches() for r in b.rows()]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["user.name"], "alice")

    def test_log_named_groups(self):
        source = source_for_path(
            self.paths["app.log"],
            log_pattern=r"^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<svc>[\w-]+) (?P<msg>.*)$",
        )
        names = [c["name"] for c in source.schema()]
        # 引擎会额外注入 lineno 等辅助列，命名分组列紧随其后并保持声明顺序
        self.assertEqual(names[1:5], ["ts", "level", "svc", "msg"])
        rows = [r for b in source.batches() for r in b.rows()]
        self.assertEqual(len(rows), 20)
        self.assertIn(rows[0]["level"], ("INFO", "WARN", "ERROR", "DEBUG"))

    def test_log_lineno_helper_columns(self):
        source = source_for_path(self.paths["app.log"], log_pattern=r"^(?P<level>\w+)")
        names = [c["name"] for c in source.schema()]
        self.assertIn("lineno", names)


class MemoryDataSource(unittest.TestCase):
    """内存数据源：嵌入式用法的核心入口。"""

    def test_register_batch(self):
        from nanoquery import Batch, Engine

        engine = Engine()
        engine.register("p", Batch({"name": ["a", "b"], "city": ["北京", "上海"], "age": [31, 27]}))
        rows = engine.query("SELECT city, AVG(age) AS avg_age FROM p GROUP BY city").rows()
        self.assertEqual(len(rows), 2)

    def test_register_rows(self):
        from nanoquery import Engine

        engine = Engine()
        engine.register_data("t", [{"a": i, "b": f"x{i % 3}"} for i in range(10)])
        rows = engine.query("SELECT b, COUNT(*) AS c FROM t GROUP BY b ORDER BY b").rows()
        self.assertEqual([r["b"] for r in rows], ["x0", "x1", "x2"])
        self.assertEqual(sum(r["c"] for r in rows), 10)

    def test_schema_of_memory_table(self):
        from nanoquery import Engine

        engine = Engine()
        engine.register_data("t", [{"a": 1, "b": "x"}])
        schema = engine.schema("t")
        self.assertEqual([c["type"] for c in schema["t"]], ["INT", "STR"])

    def test_empty_memory_table(self):
        from nanoquery import Engine

        engine = Engine()
        engine.register_data("t", [])
        self.assertEqual(engine.query("SELECT COUNT(*) AS c FROM t").rows(), [{"c": 0}])


if __name__ == "__main__":
    unittest.main()
