"""结果导出与格式化。

支持六种输出格式，覆盖从"人眼看"到"机器读"的全部场景：

=========  ==================================================
格式       用途
=========  ==================================================
``table``  终端友好对齐表格（默认），自动按终端宽度裁剪
``json``   标准 JSON 数组，便于管道给 jq / 其他程序
``jsonl``  每行一个 JSON 对象，适合流式落盘
``csv``    RFC 4180 CSV，可直接进 Excel
``tsv``    制表符分隔
``md``     Markdown 表格，可直接粘进 README / Issue
=========  ==================================================
"""

from __future__ import annotations

import csv
import io
import json
import sys
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .types import value_repr

__all__ = ["FORMATS", "render_rows", "iter_render", "default_value", "width_of"]

FORMATS = ("table", "json", "jsonl", "csv", "tsv", "md")

# CJK 字符在终端中占两个西文字符宽度
def _is_wide(char: str) -> bool:
    code = ord(char)
    return (
        0x1100 <= code <= 0x115F
        or 0x2E80 <= code <= 0xA4CF
        or 0xAC00 <= code <= 0xD7A3
        or 0xF900 <= code <= 0xFAFF
        or 0xFE30 <= code <= 0xFE6F
        or 0xFF00 <= code <= 0xFF60
        or 0xFFE0 <= code <= 0xFFE6
        or 0x20000 <= code <= 0x3FFFD
    )


def width_of(text: str) -> int:
    """计算字符串的终端显示宽度（中文按 2 列计）。"""
    return sum(2 if _is_wide(ch) else 1 for ch in text)


def default_value(value: Any) -> Any:
    """把引擎内部值转换为可序列化的展示值。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return value


def _cell(value: Any, max_width: int) -> str:
    text = value_repr(value)
    text = text.replace("\n", "\\n").replace("\t", "\\t")
    if max_width > 0 and width_of(text) > max_width:
        clipped = []
        used = 0
        for ch in text:
            w = 2 if _is_wide(ch) else 1
            if used + w > max_width - 1:
                clipped.append("…")
                break
            clipped.append(ch)
            used += w
        text = "".join(clipped)
    return text


def _table(rows: List[Dict[str, Any]], columns: Sequence[str], max_width: int = 60) -> str:
    if not rows:
        return "(0 行)"
    widths: List[int] = []
    for name in columns:
        w = width_of(str(name))
        for row in rows:
            w = max(w, width_of(_cell(row.get(name), max_width)))
        widths.append(min(w, max_width))
    total = sum(widths) + 3 * len(widths) + 1
    if total > 200:
        widths = [max(6, int(w * 180 / total)) for w in widths]

    def line(left: str, mid: str, right: str) -> str:
        return left + mid.join("─" * (w + 2) for w in widths) + right

    out = [line("┌", "┬", "┐")]
    header = "│" + "│".join(f" {_pad(str(name), w)} " for name, w in zip(columns, widths)) + "│"
    out.append(header)
    out.append(line("├", "┼", "┤"))
    for row in rows:
        out.append(
            "│" + "│".join(f" {_pad(_cell(row.get(name), max_width), w)} " for name, w in zip(columns, widths)) + "│"
        )
    out.append(line("└", "┴", "┘"))
    out.append(f"({len(rows)} 行)")
    return "\n".join(out)


def _pad(text: str, width: int) -> str:
    gap = width - width_of(text)
    return text + " " * max(0, gap)


def _markdown(rows: List[Dict[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "_（无数据）_"
    head = "| " + " | ".join(str(c) for c in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(value_repr(row.get(c)).replace("|", "\\|") for c in columns) + " |"
        for row in rows
    ]
    return "\n".join([head, sep] + body)


def _csv(rows: List[Dict[str, Any]], columns: Sequence[str], delimiter: str = ",") -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(c) is None else value_repr(row.get(c)) for c in columns])
    return buffer.getvalue().rstrip("\n")


def render_rows(rows: List[Dict[str, Any]], columns: Sequence[str], fmt: str = "table") -> str:
    """把结果行渲染为指定格式的字符串。"""
    fmt = fmt.lower()
    if fmt == "table":
        return _table(rows, columns)
    if fmt == "md" or fmt == "markdown":
        return _markdown(rows, columns)
    if fmt == "csv":
        return _csv(rows, columns, ",")
    if fmt == "tsv":
        return _csv(rows, columns, "\t")
    if fmt == "json":
        return json.dumps(
            [{c: default_value(row.get(c)) for c in columns} for row in rows],
            ensure_ascii=False,
            indent=2,
        )
    if fmt == "jsonl":
        return "\n".join(
            json.dumps({c: default_value(row.get(c)) for c in columns}, ensure_ascii=False)
            for row in rows
        )
    raise ValueError(f"不支持的输出格式：{fmt}（可选：{', '.join(FORMATS)}）")


def iter_render(
    rows: Iterable[Dict[str, Any]],
    columns: Sequence[str],
    fmt: str = "table",
    chunk: int = 500,
) -> Iterator[str]:
    """流式渲染：边查询边输出，避免整表物化。

    对 ``table`` / ``md`` 等需要对齐的格式，会按 ``chunk`` 分批渲染（每批独立对齐）；
    对 ``jsonl`` / ``csv`` 这类天然流式的格式则逐行产出。
    """
    fmt = fmt.lower()
    if fmt == "jsonl":
        for row in rows:
            yield json.dumps({c: default_value(row.get(c)) for c in columns}, ensure_ascii=False)
        return

    if fmt in ("csv", "tsv"):
        delimiter = "," if fmt == "csv" else "\t"
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
        writer.writerow(columns)
        yield buffer.getvalue().rstrip("\n")
        pending: List[str] = []
        for row in rows:
            buf = io.StringIO()
            csv.writer(buf, delimiter=delimiter, lineterminator="\n").writerow(
                ["" if row.get(c) is None else value_repr(row.get(c)) for c in columns]
            )
            pending.append(buf.getvalue().rstrip("\n"))
            if len(pending) >= chunk:
                yield "\n".join(pending)
                pending = []
        if pending:
            yield "\n".join(pending)
        return

    if fmt == "json":
        # 逗号后置（先缓存上一行），保证输出是合法且美观的 JSON 数组。
        pending: Optional[str] = None
        started = False
        for row in rows:
            body = json.dumps(
                {c: default_value(row.get(c)) for c in columns}, ensure_ascii=False, indent=2
            )
            indented = "  " + body.replace("\n", "\n  ")
            if not started:
                yield "["
                started = True
            if pending is not None:
                yield pending + ","
            pending = indented
        if not started:
            yield "[]"
            return
        if pending is not None:
            yield pending
        yield "]"
        return

    buffer: List[Dict[str, Any]] = []
    for row in rows:
        buffer.append(row)
        if len(buffer) >= chunk:
            yield _table(buffer, columns) if fmt == "table" else _markdown(buffer, columns)
            buffer = []
    if buffer:
        yield _table(buffer, columns) if fmt == "table" else _markdown(buffer, columns)
    elif fmt == "table":
        yield "(0 行)"
    else:
        yield "_（无数据）_"
