""".nq 列存格式测试（写入 / 读取 / 编码选择 / 列裁剪）。"""

from __future__ import annotations

import os
import unittest

from nanoquery.sources import source_for_path
from nanoquery.storage import Encoding, choose_encoding, read_batches, read_column, read_header, write_nq

from helpers import TempDataMixin


class EncodingChoice(unittest.TestCase):
    def test_low_cardinality_uses_dict(self):
        self.assertEqual(choose_encoding(["a", "b", "a", "b"] * 25), Encoding.DICT)

    def test_long_runs_use_rle(self):
        self.assertEqual(choose_encoding(["x"] * 100 + ["y"] * 100), Encoding.RLE)

    def test_high_cardinality_numbers_use_raw(self):
        values = [i * 1.5 for i in range(500)]
        self.assertEqual(choose_encoding(values), Encoding.RAW)


class Roundtrip(TempDataMixin, unittest.TestCase):
    def _export(self, src_name: str) -> str:
        out = os.path.join(self.dir, src_name + ".nq")
        source = source_for_path(self.paths[src_name])
        write_nq(out, source.batches(), compress=True, source=self.paths[src_name])
        return out

    def test_header_metadata(self):
        path = self._export("people.csv")
        header = read_header(path)
        self.assertEqual(header["row_count"], 6)
        self.assertEqual([c["name"] for c in header["columns"]], ["name", "city", "age", "score"])
        self.assertEqual(header["format"], "nanoquery-columnar")
        self.assertEqual(header["version"], 1)

    def test_full_roundtrip(self):
        path = self._export("people.csv")
        rows = [r for b in read_batches(path) for r in b.rows()]
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["name"], "alice")
        self.assertEqual(rows[0]["age"], 31)
        self.assertAlmostEqual(rows[0]["score"], 88.5)

    def test_null_preserved(self):
        path = self.write_csv("withnull.csv", ["a", "b"], [["1", "NULL"], ["NULL", "2"]])
        out = os.path.join(self.dir, "withnull.nq")
        write_nq(out, source_for_path(path).batches(), compress=True, source=path)
        rows = [r for b in read_batches(out) for r in b.rows()]
        self.assertIsNone(rows[0]["b"])
        self.assertIsNone(rows[1]["a"])

    def test_column_pruning(self):
        path = self._export("people.csv")
        batches = list(read_batches(path, columns=["city"]))
        self.assertEqual(batches[0].column_names, ["city"])

    def test_read_single_column(self):
        path = self._export("people.csv")
        self.assertEqual(read_column(path, "name")[0], "alice")

    def test_query_over_nq(self):
        path = self._export("people.csv")
        rows = self.rows_of(
            "SELECT city, COUNT(*) AS c FROM people GROUP BY city HAVING COUNT(*) > 1 ORDER BY c DESC",
            people=path,
        )
        self.assertEqual(rows[0]["city"], "北京")
        self.assertEqual(rows[0]["c"], 3)

    def test_jsonl_roundtrip(self):
        path = self._export("events.jsonl")
        rows = [r for b in read_batches(path) for r in b.rows()]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["user.name"], "alice")

    def test_uncompressed_variant(self):
        out = os.path.join(self.dir, "plain.nq")
        source = source_for_path(self.paths["people.csv"])
        write_nq(out, source.batches(), compress=False, source=self.paths["people.csv"])
        rows = [r for b in read_batches(out) for r in b.rows()]
        self.assertEqual(len(rows), 6)

    def test_bad_file_rejected(self):
        bad = os.path.join(self.dir, "bad.nq")
        with open(bad, "wb") as handle:
            handle.write(b"XXXX" + b"\x00" * 32)
        with self.assertRaises(Exception):
            read_header(bad)


if __name__ == "__main__":
    unittest.main()
