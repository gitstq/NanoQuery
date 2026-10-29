"""交互式 REPL 终端。

提供类 psql 的体验：多行输入、历史命令、元命令（以反斜杠开头）。

===============  ============================================
元命令           作用
===============  ============================================
``\\dt``         列出已注册的表
``\\d NAME``     查看指定表的 schema
``\\format FMT`` 切换输出格式（table/json/csv/...）
``\\timing``     开关耗时统计
``\\help``       显示帮助
``\\quit``       退出（也可用 ``exit`` / Ctrl-D）
===============  ============================================
"""

from __future__ import annotations

import sys
import time
from typing import Dict, List, Optional

from .exporter import FORMATS, iter_render
from .types import NanoQueryError, value_repr

__all__ = ["Repl"]


class Repl:
    """NanoQuery 交互式终端。"""

    def __init__(self, engine, fmt: str = "table", show_banner: bool = True) -> None:
        self.engine = engine
        self.fmt = fmt
        self.show_banner = show_banner
        self.timing = False
        self._buffer: List[str] = []

    # ------------------------------------------------------------------ #

    def run(self) -> int:
        if self.show_banner and sys.stdin.isatty():
            from .cli import BANNER

            print(BANNER)
            print(f"  NanoQuery 交互式终端｜输出格式 {self.fmt}｜输入 \\help 查看帮助\n")

        if self.engine.tables:
            self._print_tables()

        while True:
            try:
                prompt = "nq> " if not self._buffer else "  ... "
                line = input(prompt)
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("\n（输入 \\quit 退出）")
                self._buffer.clear()
                continue

            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("\\"):
                if self._meta(stripped) == "quit":
                    break
                continue
            if stripped.lower() in ("quit", "exit", "q;"):
                break

            self._buffer.append(line)
            if not stripped.endswith(";"):
                continue

            sql = "\n".join(self._buffer).strip().rstrip(";")
            self._buffer.clear()
            self._execute(sql)

        return 0

    # ------------------------------------------------------------------ #

    def _execute(self, sql: str) -> None:
        started = time.time()
        try:
            result = self.engine.query(sql)
        except NanoQueryError as exc:
            print(f"❌ {exc}")
            return
        count = 0
        for chunk in iter_render(result, result.columns, self.fmt):
            if chunk:
                print(chunk)
            count += 1
        if count == 0 and self.fmt == "json":
            print("[]")
        if self.timing:
            print(f"⏱  {(time.time() - started) * 1000:.1f} ms")

    def _meta(self, command: str) -> Optional[str]:
        parts = command[1:].split(None, 1)
        name = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""

        if name in ("q", "quit", "exit"):
            return "quit"
        if name == "help":
            self._help()
        elif name == "dt":
            self._print_tables()
        elif name in ("d", "d+", "schema"):
            self._print_schema(arg)
        elif name == "format":
            if arg in FORMATS:
                self.fmt = arg
                print(f"输出格式已切换为 {arg}")
            else:
                print(f"可选格式：{', '.join(FORMATS)}")
        elif name == "timing":
            self.timing = not self.timing
            print(f"耗时统计：{'开' if self.timing else '关'}")
        elif name == "clear":
            self._buffer.clear()
        else:
            print(f"未知元命令：\\{name}（输入 \\help 查看帮助）")
        return None

    def _help(self) -> None:
        print(
            "\n".join(
                [
                    "元命令：",
                    "  \\dt              列出已注册的表",
                    "  \\d [NAME]        查看表 schema",
                    "  \\format FMT      切换输出格式：" + ", ".join(FORMATS),
                    "  \\timing          开关耗时统计",
                    "  \\help            显示本帮助",
                    "  \\quit            退出",
                    "",
                    "SQL 以分号结尾执行；支持多行输入。",
                ]
            )
        )

    def _print_tables(self) -> None:
        if not self.engine.tables:
            print("（尚未注册任何表，可在命令行传入文件）")
            return
        print("已注册的表：")
        for name, source in self.engine.tables.items():
            columns = source.schema()
            print(f"  {name}  [{source.kind}]  {source.path}  ({len(columns)} 列)")

    def _print_schema(self, name: str) -> None:
        if not name:
            self._print_tables()
            return
        try:
            _, source = self.engine.resolve_table(name)
        except NanoQueryError as exc:
            print(f"❌ {exc}")
            return
        rows = [{"column": c["name"], "type": c["type"]} for c in source.schema()]
        if not rows:
            print("（该表没有可识别的列）")
            return
        from .exporter import render_rows

        print(render_rows(rows, ["column", "type"], self.fmt))
