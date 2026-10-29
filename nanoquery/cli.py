"""NanoQuery 命令行接口。

纯标准库实现（``argparse``），零第三方依赖。命令形态::

    nanoquery "SELECT city, COUNT(*) c FROM t GROUP BY city" data.csv
    nanoquery -q "SELECT * FROM t LIMIT 5" -f data.csv --format json
    nanoquery repl data.csv
    nanoquery schema data.csv
    nanoquery import data.csv -o data.nq
    nanoquery explain "SELECT * FROM t WHERE age > 30" -f data.csv
    nanoquery selftest
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .batch import Batch
from .exporter import FORMATS, iter_render, render_rows
from .executor import Engine, Result, Scope, eval_expr, unparse
from .parser import parse
from .sources import detect_format
from .storage import write_nq
from .types import NanoQueryError, value_repr

__all__ = ["main", "build_parser", "run_query"]

BANNER = r"""
  ███╗   ██╗ █████╗ ███╗   ██╗ ██████╗ 
  ████╗  ██║██╔══██╗████╗  ██║██╔═══██╗
  ██╔██╗ ██║███████║██╔██╗ ██║██║   ██║   NanoQuery
  ██║╚██╗██║██╔══██║██║╚██╗██║██║   ██║   Embedded Columnar SQL Engine
  ██║ ╚████║██║  ██║██║ ╚████║╚██████╔╝
  ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ 
"""


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #


SUBCOMMANDS = ("repl", "schema", "import", "explain", "selftest", "functions")


def build_parser() -> argparse.ArgumentParser:
    """构造查询模式参数解析器。

    说明：查询模式下第一个位置参数是 SQL 文本，与子命令名会相互干扰，
    因此 ``main()`` 会先按首参数是否为已知子命令做手动分流，
    命中子命令时使用 ``_subcommand_parser()`` 生成的独立解析器。
    """
    parser = argparse.ArgumentParser(
        prog="nanoquery",
        description="NanoQuery — 零依赖嵌入式列式分析引擎，直接对本地文件执行 SQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  nanoquery \"SELECT city, COUNT(*) c FROM t GROUP BY city ORDER BY c DESC\" data.csv\n"
            "  nanoquery -q \"SELECT * FROM app.log WHERE level = 'ERROR'\" -f app.log --log-pattern "
            "'^(?P<ts>\\S+) (?P<level>\\w+) (?P<msg>.*)'\n"
            "  nanoquery import data.csv -o data.nq && nanoquery -q \"SELECT AVG(age) FROM data\" -f data.nq\n"
            "  nanoquery repl data.csv\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"NanoQuery {__version__}")
    parser.add_argument("sql_pos", nargs="?", metavar="SQL", help="SQL 查询语句（也可通过 -q 传入）")
    parser.add_argument("files_pos", nargs="*", metavar="FILE", help="数据文件，表名默认取文件名")

    parser.add_argument("-q", "--sql", help="SQL 查询语句")
    parser.add_argument("-f", "--file", action="append", default=[], metavar="PATH", help="数据文件（可重复）")
    parser.add_argument("-t", "--table", action="append", default=[], metavar="NAME=PATH",
                        help="显式指定表名，例如 -t users=people.csv")
    parser.add_argument("--format", default="table", choices=list(FORMATS), help="输出格式（默认 table）")
    parser.add_argument("-o", "--output", metavar="PATH", help="结果写入文件而非标准输出")
    parser.add_argument("--delimiter", help="CSV 分隔符（默认自动嗅探）")
    parser.add_argument("--no-header", action="store_true", help="CSV 文件没有表头")
    parser.add_argument("--log-pattern", help="日志文件字段提取正则（使用命名分组）")
    parser.add_argument("--encoding", default="utf-8", help="文件编码（默认 utf-8）")
    parser.add_argument("--batch-size", type=int, default=4096, help="批处理行数（默认 4096）")
    parser.add_argument("--max-rows", type=int, default=0, help="最多输出行数，0 表示不限")
    parser.add_argument("--no-infer", action="store_true", help="关闭 CSV 类型自动推断，全部按字符串处理")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出执行耗时等诊断信息")
    parser.add_argument("--quiet", action="store_true", help="静默模式，只输出结果")

    return parser


def _subcommand_parser(name: str) -> argparse.ArgumentParser:
    """为子命令构造独立的参数解析器（避免与位置参数 SQL/FILE 互相干扰）。"""
    parser = argparse.ArgumentParser(
        prog=f"nanoquery {name}",
        description=_SUBCOMMAND_HELP[name],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    if name == "repl":
        parser.add_argument("files_pos", nargs="*", metavar="FILE")
        parser.add_argument("-f", "--file", action="append", default=[])
        parser.add_argument("-t", "--table", action="append", default=[])
        parser.add_argument("--delimiter")
        parser.add_argument("--no-header", action="store_true")
        parser.add_argument("--log-pattern")
        parser.add_argument("--format", default="table", choices=list(FORMATS))
        parser.add_argument("--encoding", default="utf-8")
        parser.add_argument("--batch-size", type=int, default=4096)
    elif name == "schema":
        parser.add_argument("files_pos", nargs="+", metavar="FILE")
        parser.add_argument("--format", default="table", choices=list(FORMATS))
        parser.add_argument("--delimiter")
        parser.add_argument("--no-header", action="store_true")
        parser.add_argument("--log-pattern")
        parser.add_argument("--table", "-t", action="append", default=[])
        parser.add_argument("--encoding", default="utf-8")
        parser.add_argument("--batch-size", type=int, default=4096)
    elif name == "import":
        parser.add_argument("source", metavar="SRC")
        parser.add_argument("-o", "--output", required=True, metavar="PATH")
        parser.add_argument("--delimiter")
        parser.add_argument("--no-header", action="store_true")
        parser.add_argument("--log-pattern")
        parser.add_argument("--no-compress", action="store_true", help="关闭列载荷 zlib 压缩")
        parser.add_argument("--encoding", default="utf-8")
        parser.add_argument("--batch-size", type=int, default=4096)
        parser.add_argument("-v", "--verbose", action="store_true")
    elif name == "explain":
        parser.add_argument("sql_pos", metavar="SQL")
        parser.add_argument("files_pos", nargs="*", metavar="FILE")
        parser.add_argument("-f", "--file", action="append", default=[])
        parser.add_argument("-t", "--table", action="append", default=[])
        parser.add_argument("--encoding", default="utf-8")
        parser.add_argument("--batch-size", type=int, default=4096)
    return parser


_SUBCOMMAND_HELP = {
    "repl": "进入交互式 SQL 终端",
    "schema": "查看数据文件的 schema",
    "import": "把数据文件转换为 .nq 列存格式",
    "explain": "查看查询执行计划",
    "selftest": "运行内置自检，验证引擎核心链路",
    "functions": "列出全部内置函数",
}


# --------------------------------------------------------------------------- #
# 引擎构建
# --------------------------------------------------------------------------- #


def _collect_files(args) -> List[str]:
    files = list(getattr(args, "files_pos", []) or [])
    files.extend(getattr(args, "file", []) or [])
    return files


def build_engine(args) -> Engine:
    engine = Engine(batch_size=getattr(args, "batch_size", 4096) or 4096)
    for spec in getattr(args, "table", []) or []:
        if "=" not in spec:
            raise NanoQueryError(f"-t/--table 需要 NAME=PATH 形式，收到：{spec}")
        name, path = spec.split("=", 1)
        engine.register_path(
            name.strip(),
            path.strip(),
            delimiter=getattr(args, "delimiter", None),
            no_header=getattr(args, "no_header", False),
            log_pattern=getattr(args, "log_pattern", None),
            encoding=getattr(args, "encoding", "utf-8"),
        )

    for path in _collect_files(args):
        engine.register_path(
            None,
            path,
            delimiter=getattr(args, "delimiter", None),
            no_header=getattr(args, "no_header", False),
            log_pattern=getattr(args, "log_pattern", None),
            encoding=getattr(args, "encoding", "utf-8"),
        )
    return engine


# --------------------------------------------------------------------------- #
# 查询执行与输出
# --------------------------------------------------------------------------- #


def run_query(engine: Engine, sql: str, fmt: str = "table", max_rows: int = 0) -> Result:
    result = engine.query(sql)
    return result


def _emit(result: Result, fmt: str, output: Optional[str], max_rows: int, quiet: bool) -> int:
    columns = result.columns

    if fmt in ("table", "md", "json", "csv", "tsv") and output is None:
        handle = sys.stdout
        count = 0
        for chunk in iter_render(_limited(result, max_rows), columns, fmt):
            if chunk:
                handle.write(chunk + "\n")
            count += 1
        handle.flush()
        return 0 if count or fmt != "table" else 0

    rows = _materialize(result, max_rows)
    text = render_rows(rows, columns, fmt)
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        if not quiet:
            print(f"✅ 已写入 {output}（{len(rows)} 行）")
    else:
        print(text)
    return 0


def _limited(result: Result, max_rows: int):
    if not max_rows:
        yield from result
        return
    for index, row in enumerate(result):
        if index >= max_rows:
            break
        yield row


def _materialize(result: Result, max_rows: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(result):
        if max_rows and index >= max_rows:
            break
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #


def _cmd_schema(args) -> int:
    engine = build_engine(args)
    rows: List[Dict[str, Any]] = []
    for name, source in engine.tables.items():
        schema = source.schema()
        if not schema:
            rows.append({"table": name, "column": "(空)", "type": "-", "format": source.kind})
            continue
        for col in schema:
            rows.append(
                {"table": name, "column": col["name"], "type": col["type"], "format": source.kind}
            )
    text = render_rows(rows, ["table", "column", "type", "format"], args.format)
    print(text)
    return 0


def _cmd_import(args) -> int:
    from .sources import source_for_path

    source = source_for_path(
        args.source,
        batch_size=4096,
        delimiter=args.delimiter,
        has_header=not args.no_header,
        log_pattern=args.log_pattern,
    )
    stats = write_nq(args.output, source.batches(), compress=not args.no_compress, source=args.source)
    if args.verbose or True:
        print(f"✅ 已导入 {stats['row_count']} 行 x {len(stats['columns'])} 列 -> {args.output}")
        print(f"   文件大小：{stats['bytes']} 字节")
        encodings = {}
        for col in stats["columns"]:
            encodings[col["encoding"]] = encodings.get(col["encoding"], 0) + 1
        detail = ", ".join(f"{k}x{v}" for k, v in sorted(encodings.items()))
        print(f"   列编码：{detail}")
        print(f"   列清单：{', '.join(c['name'] + ':' + c['type'] for c in stats['columns'])}")
    return 0


def _cmd_explain(args) -> int:
    engine = build_engine(args)
    sql = args.sql_pos
    query = parse(sql)
    lines = ["执行计划："]
    node = query
    depth = 0
    while node is not None:
        prefix = "  " * depth
        lines.append(f"{prefix}└─ Project: {[unparse(item.expr) + (f' AS {item.alias}' if item.alias else '') for item in node.items]}")
        if node.distinct:
            lines.append(f"{prefix}   └─ Distinct")
        if node.order_by:
            keys = ", ".join(
                f"{unparse(o.expr)}{' DESC' if o.descending else ' ASC'}" for o in node.order_by
            )
            lines.append(f"{prefix}   └─ Sort: {keys}")
        if node.limit is not None:
            limit_text = unparse(node.limit.count) if node.limit.count else "ALL"
            offset_text = unparse(node.limit.offset) if node.limit.offset else "0"
            lines.append(f"{prefix}   └─ Limit: {limit_text} OFFSET {offset_text}")
        if node.having:
            lines.append(f"{prefix}   └─ Having: {unparse(node.having)}")
        if node.group_by:
            lines.append(f"{prefix}   └─ HashAggregate: {[unparse(g) for g in node.group_by]}")
        if node.where:
            lines.append(f"{prefix}   └─ Filter: {unparse(node.where)}")
        for join in node.joins:
            target = join.table.name or join.table.path or "(subquery)"
            lines.append(f"{prefix}   └─ {join.kind} HashJoin: {target} ON {unparse(join.on)}")
        if node.from_table is not None:
            origin = node.from_table.name or node.from_table.path or "(subquery)"
            lines.append(f"{prefix}   └─ Scan: {origin}")
        else:
            lines.append(f"{prefix}   └─ Scan: (常量行)")
        node = node.union
        depth += 1
        if node is not None:
            lines.append(f"{'  ' * depth}└─ UNION {'ALL' if query.union_all else 'DISTINCT'}")
    print("\n".join(lines))
    if engine.tables:
        print("\n已注册的表：")
        for name, source in engine.tables.items():
            print(f"  - {name} ({source.kind}) <- {source.path}")
    return 0


def _cmd_functions(args) -> int:
    from .functions import AGGREGATE_FUNCTIONS, SCALAR_FUNCTIONS

    rows = []
    for name in sorted(SCALAR_FUNCTIONS):
        rows.append({"类别": "标量函数", "名称": name, "说明": _SCALAR_DOC.get(name, "")})
    for name in sorted(AGGREGATE_FUNCTIONS):
        rows.append({"类别": "聚合函数", "名称": name, "说明": _AGG_DOC.get(name, "")})
    print(render_rows(rows, ["类别", "名称", "说明"], "table"))
    return 0


_SCALAR_DOC = {
    "UPPER": "转大写", "LOWER": "转小写", "LENGTH": "字符串长度", "TRIM": "去除首尾空白",
    "SUBSTR": "子串截取（1 起始）", "REPLACE": "字符串替换", "CONCAT": "字符串拼接",
    "CONCAT_WS": "带分隔符拼接", "ABS": "绝对值", "ROUND": "四舍五入", "CEIL": "向上取整",
    "FLOOR": "向下取整", "SQRT": "平方根", "POWER": "幂运算", "MOD": "取模",
    "COALESCE": "返回首个非 NULL 值", "IFNULL": "NULL 兜底", "NULLIF": "相等则返回 NULL",
    "CAST": "类型转换（CAST(x AS INT)）", "TYPEOF": "返回值类型名",
}

_AGG_DOC = {
    "COUNT": "计数（COUNT(*) 计全部行）", "SUM": "求和", "AVG": "平均值", "MIN": "最小值",
    "MAX": "最大值", "MEDIAN": "中位数", "VARIANCE": "样本方差", "STDDEV": "样本标准差",
    "GROUP_CONCAT": "分组内字符串拼接",
}


def _cmd_selftest(args) -> int:
    from .selftest import run_selftest

    return run_selftest()


# --------------------------------------------------------------------------- #
# REPL
# --------------------------------------------------------------------------- #


def _cmd_repl(args) -> int:
    from .repl import Repl

    engine = build_engine(args)
    return Repl(engine, fmt=args.format).run()


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 主入口，返回进程退出码。"""
    argv = list(argv) if argv is not None else sys.argv[1:]

    # 子命令与「位置参数即 SQL」天然冲突，这里先按首参数手动分流，
    # 避免 argparse 把 `data.csv` 误判成子命令名。
    if argv and argv[0] in SUBCOMMANDS:
        name = argv[0]
        args = _subcommand_parser(name).parse_args(argv[1:])
        handler = {
            "repl": _cmd_repl,
            "schema": _cmd_schema,
            "import": _cmd_import,
            "explain": _cmd_explain,
            "selftest": _cmd_selftest,
            "functions": _cmd_functions,
        }[name]
        try:
            return handler(args)
        except NanoQueryError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 1
        except BrokenPipeError:  # pragma: no cover
            return 0
        except KeyboardInterrupt:  # pragma: no cover
            print("\n已取消", file=sys.stderr)
            return 130

    parser = build_parser()
    args = parser.parse_args(argv)
    sql = args.sql or args.sql_pos
    files = _collect_files(args)
    try:
        if not sql and not files:
            parser.print_help()
            return 0
        if not sql:
            from .repl import Repl

            return Repl(build_engine(args), fmt=args.format).run()

        import time

        engine = build_engine(args)
        started = time.time()
        result = engine.query(sql)
        code = _emit(result, args.format, args.output, args.max_rows, args.quiet)
        if args.verbose and not args.quiet:
            elapsed = (time.time() - started) * 1000
            print(f"⏱  耗时 {elapsed:.1f} ms｜批处理大小 {engine.batch_size}", file=sys.stderr)
        return code
    except NanoQueryError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:  # pragma: no cover
        return 0
    except KeyboardInterrupt:  # pragma: no cover
        print("\n已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
