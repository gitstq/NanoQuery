"""测试用例共享工具：临时数据文件与引擎构建。"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest

from nanoquery import Engine

FIXTURES = {
    "people.csv": (
        ["name", "city", "age", "score"],
        [
            ["alice", "北京", "31", "88.5"],
            ["bob", "上海", "27", "92.0"],
            ["carol", "北京", "45", "77.25"],
            ["dave", "深圳", "31", "61.0"],
            ["erin", "上海", "38", "95.5"],
            ["frank", "北京", "27", "83.0"],
        ],
    ),
    "city.csv": (
        ["city", "region"],
        [
            ["北京", "华北"],
            ["上海", "华东"],
            ["深圳", "华南"],
            ["广州", "华南"],
        ],
    ),
}

JSONL_ROWS = [
    {"id": 1, "user": {"name": "alice", "vip": True}, "event": "view", "value": 10},
    {"id": 2, "user": {"name": "bob", "vip": False}, "event": "click", "value": 20},
    {"id": 3, "user": {"name": "carol", "vip": True}, "event": "view", "value": 30},
    {"id": 4, "user": {"name": "dave", "vip": False}, "event": "buy", "value": 40},
]


class TempDataMixin:
    """为每个测试准备独立的临时数据目录。"""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        self.paths: dict[str, str] = {}
        for filename, (header, rows) in FIXTURES.items():
            path = os.path.join(self.dir, filename)
            with open(path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerows(rows)
            self.paths[filename] = path

        jsonl_path = os.path.join(self.dir, "events.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as handle:
            for row in JSONL_ROWS:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.paths["events.jsonl"] = jsonl_path

        log_path = os.path.join(self.dir, "app.log")
        lines = []
        for index in range(20):
            level = ("INFO", "WARN", "ERROR", "DEBUG")[index % 4]
            lines.append(f"2026-05-0{index % 9 + 1} 10:0{index % 9}:00 {level} svc-{index % 3} msg-{index}")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        self.paths["app.log"] = log_path

    def engine(self, **tables) -> Engine:
        eng = Engine(batch_size=4)  # 小批尺寸，强制走多批路径
        for name, path in tables.items():
            eng.register_path(name, path)
        return eng

    def write_csv(self, filename: str, header, rows) -> str:
        path = os.path.join(self.dir, filename)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def rows_of(self, sql: str, **tables):
        return self.engine(**tables).query(sql).rows()

    def scalar(self, sql: str, **tables):
        rows = self.rows_of(sql, **tables)
        assert len(rows) == 1, f"期望单行，实际 {len(rows)} 行"
        return list(rows[0].values())[0]


__all__ = ["TempDataMixin", "unittest"]
