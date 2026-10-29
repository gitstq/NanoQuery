"""结果导出与格式化测试。"""

from __future__ import annotations

import json
import unittest

from nanoquery.exporter import FORMATS, iter_render, render_rows, width_of

ROWS = [
    {"city": "北京", "c": 3},
    {"city": "上海", "c": 2},
]
COLUMNS = ["city", "c"]


class Width(unittest.TestCase):
    def test_cjk_counts_double(self):
        self.assertEqual(width_of("北京"), 4)
        self.assertEqual(width_of("ab"), 2)
        self.assertEqual(width_of("a京"), 3)


class RenderRows(unittest.TestCase):
    def test_table_contains_header(self):
        text = render_rows(ROWS, COLUMNS, "table")
        self.assertIn("city", text)
        self.assertIn("北京", text)
        self.assertIn("(2 行)", text)

    def test_empty_table(self):
        self.assertIn("0", render_rows([], COLUMNS, "table"))

    def test_json_is_parseable(self):
        data = json.loads(render_rows(ROWS, COLUMNS, "json"))
        self.assertEqual(data[0]["city"], "北京")

    def test_jsonl_lines(self):
        lines = render_rows(ROWS, COLUMNS, "jsonl").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["c"], 3)

    def test_csv(self):
        text = render_rows(ROWS, COLUMNS, "csv")
        self.assertEqual(text.splitlines()[0], "city,c")
        self.assertIn("北京,3", text)

    def test_tsv(self):
        self.assertIn("\t", render_rows(ROWS, COLUMNS, "tsv"))

    def test_markdown(self):
        lines = render_rows(ROWS, COLUMNS, "md").splitlines()
        self.assertTrue(lines[0].startswith("| city"))
        self.assertEqual(lines[1].strip(), "| --- | --- |")

    def test_null_renders_as_null(self):
        self.assertIn("NULL", render_rows([{"a": None}], ["a"], "table"))

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            render_rows(ROWS, COLUMNS, "xml")


class Streaming(unittest.TestCase):
    def _collect(self, fmt: str) -> str:
        return "\n".join(iter_render(iter(ROWS), COLUMNS, fmt))

    def test_formats_supported(self):
        self.assertEqual(set(FORMATS), {"table", "json", "jsonl", "csv", "tsv", "md"})

    def test_stream_json_valid(self):
        data = json.loads(self._collect("json"))
        self.assertEqual(len(data), 2)

    def test_stream_json_empty(self):
        self.assertEqual("\n".join(iter_render(iter([]), COLUMNS, "json")), "[]")

    def test_stream_csv(self):
        text = self._collect("csv")
        self.assertEqual(text.splitlines()[0], "city,c")

    def test_stream_table(self):
        self.assertIn("北京", self._collect("table"))

    def test_stream_empty_table(self):
        self.assertIn("0", "\n".join(iter_render(iter([]), COLUMNS, "table")))

    def test_stream_jsonl(self):
        self.assertEqual(len(self._collect("jsonl").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
