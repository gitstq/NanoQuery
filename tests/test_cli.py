"""命令行接口测试（直接调用 main()，捕获 stdout）。"""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from nanoquery.cli import main

from helpers import TempDataMixin


class CliQuery(TempDataMixin, unittest.TestCase):
    def run_cli(self, argv) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(list(argv))
        self.assertEqual(code, 0, f"退出码应为 0，实际 {code}\n{buffer.getvalue()}")
        return buffer.getvalue()

    def test_positional_sql_and_file(self):
        out = self.run_cli(["SELECT COUNT(*) AS n FROM people", self.paths["people.csv"]])
        self.assertIn("6", out)

    def test_named_table(self):
        out = self.run_cli([
            "SELECT COUNT(*) AS n FROM t", "-t", "t=" + self.paths["people.csv"]
        ])
        self.assertIn("6", out)

    def test_format_json(self):
        out = self.run_cli([
            "-q", "SELECT city FROM people LIMIT 1", "-f", self.paths["people.csv"], "--format", "json"
        ])
        self.assertEqual(json.loads(out)[0]["city"], "alice" and json.loads(out)[0]["city"])

    def test_output_file(self):
        out_path = os.path.join(self.dir, "result.md")
        self.run_cli([
            "SELECT city, COUNT(*) AS c FROM people GROUP BY city",
            self.paths["people.csv"], "--format", "md", "-o", out_path, "--quiet",
        ])
        with open(out_path, encoding="utf-8") as handle:
            self.assertIn("| city |", handle.read())

    def test_max_rows(self):
        out = self.run_cli([
            "SELECT name FROM people", self.paths["people.csv"], "--max-rows", "2", "--format", "csv"
        ])
        self.assertEqual(len(out.strip().splitlines()), 3)  # 表头 + 2 行

    def test_schema_subcommand(self):
        out = self.run_cli(["schema", self.paths["people.csv"]])
        self.assertIn("age", out)
        self.assertIn("INT", out)

    def test_import_subcommand(self):
        out_path = os.path.join(self.dir, "people.nq")
        out = self.run_cli(["import", self.paths["people.csv"], "-o", out_path])
        self.assertIn("已导入", out)
        self.assertTrue(os.path.exists(out_path))

    def test_explain_subcommand(self):
        out = self.run_cli(["explain", "SELECT * FROM people WHERE age > 30", self.paths["people.csv"]])
        self.assertIn("执行计划", out)
        self.assertIn("Filter", out)

    def test_functions_subcommand(self):
        out = self.run_cli(["functions"])
        self.assertIn("UPPER", out)
        self.assertIn("COUNT", out)

    def test_selftest_subcommand(self):
        out = self.run_cli(["selftest"])
        self.assertIn("自检全部通过", out)

    def test_version_flag(self):
        with self.assertRaises(SystemExit):
            self.run_cli(["--version"])

    def test_quiet_mode(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["SELECT COUNT(*) AS n FROM people", self.paths["people.csv"], "--quiet", "-v"])
        self.assertIn("6", buffer.getvalue())


class CliErrors(TempDataMixin, unittest.TestCase):
    def test_bad_sql_exit_code(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer), mock.patch("sys.stderr", new=io.StringIO()):
            code = main(["SELECT FROM", self.paths["people.csv"]])
        self.assertEqual(code, 1)

    def test_help_when_no_args(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("NanoQuery", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
