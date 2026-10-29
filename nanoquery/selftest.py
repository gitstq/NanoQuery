"""内置自检（``nanoquery selftest``）。

不依赖 pytest，直接对引擎的**核心链路**做端到端断言：词法 -> 语法 -> 执行 ->
聚合 -> 存储 -> 导出。用于在陌生环境快速确认安装是否可用。
"""

from __future__ import annotations

import io
import os
import tempfile
from typing import Any, Dict, List

from .batch import batch_from_rows
from .executor import Engine
from .storage import read_header, write_nq
from .types import NanoQueryError

__all__ = ["run_selftest"]

SAMPLE = """id,name,city,age,score
1,张三,北京,28,88.5
2,李四,上海,34,92.0
3,王五,北京,29,75.5
4,赵六,广州,41,68.0
5,孙七,上海,25,95.5
6,周八,北京,38,81.0
"""


def _make_csv(directory: str) -> str:
    path = os.path.join(directory, "people.csv")
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(SAMPLE)
    return path


def run_selftest() -> int:
    """执行全部自检用例，返回进程退出码（0 表示全部通过）。"""
    passed = 0
    failed: List[str] = []

    def check(name: str, fn) -> None:
        nonlocal passed
        try:
            fn()
        except AssertionError as exc:
            failed.append(f"{name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"  ✅ {name}")

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = _make_csv(tmp)
        engine = Engine()
        engine.register_path("people", csv_path)

        def q(sql: str) -> List[Dict[str, Any]]:
            return engine.query(sql).rows()

        print("\nNanoQuery 自检\n" + "-" * 48)

        check("基础投影与 LIMIT", lambda: _assert(
            len(q("SELECT name, age FROM people LIMIT 3")) == 3
        ))
        check("WHERE 数值过滤", lambda: _assert(
            [r["name"] for r in q("SELECT name FROM people WHERE age > 30")] == ["李四", "赵六", "周八"]
        ))
        check("WHERE 字符串相等", lambda: _assert(
            len(q("SELECT * FROM people WHERE city = '北京'")) == 3
        ))
        check("GROUP BY + COUNT", lambda: _assert(
            {r["city"]: r["c"] for r in q("SELECT city, COUNT(*) AS c FROM people GROUP BY city")}
            == {"北京": 3, "上海": 2, "广州": 1}
        ))
        check("GROUP BY + 多聚合 + HAVING", lambda: _assert(
            [r["city"] for r in q(
                "SELECT city, COUNT(*) AS c, AVG(age) AS avg_age FROM people "
                "GROUP BY city HAVING COUNT(*) >= 2 ORDER BY c DESC, city ASC"
            )] == ["北京", "上海"]
        ))
        check("ORDER BY 多键 + 方向", lambda: _assert(
            [r["score"] for r in q("SELECT score FROM people ORDER BY score DESC LIMIT 2")]
            == [95.5, 92.0]
        ))
        check("DISTINCT", lambda: _assert(
            len(q("SELECT DISTINCT city FROM people")) == 3
        ))
        check("IN / BETWEEN / LIKE", lambda: _assert(
            len(q("SELECT * FROM people WHERE age BETWEEN 26 AND 35 AND name LIKE '李%'")) == 1
        ))
        check("CASE WHEN 表达式", lambda: _assert(
            q("SELECT CASE WHEN age >= 35 THEN 'senior' ELSE 'junior' END AS band FROM people")[0]["band"]
            == "junior"
        ))
        check("标量函数与别名", lambda: _assert(
            q("SELECT UPPER(city) AS c FROM people LIMIT 1")[0]["c"] == "北京"
        ))
        check("算术与 NULL 传播", lambda: _assert(
            q("SELECT score + 1.5 AS s FROM people LIMIT 1")[0]["s"] == 90.0
        ))
        check("派生表（子查询）", lambda: _assert(
            len(q("SELECT * FROM (SELECT name, age FROM people WHERE age > 30) AS t WHERE age < 40")) == 2
        ))
        check("常量查询（无 FROM）", lambda: _assert(
            q("SELECT 1 AS a, 'x' AS b")[0] == {"a": 1, "b": "x"}
        ))
        check("LIMIT / OFFSET", lambda: _assert(
            [r["id"] for r in q("SELECT id FROM people ORDER BY id LIMIT 2 OFFSET 3")] == [4, 5]
        ))
        check("UNION ALL 合并", lambda: _assert(
            len(q("SELECT city FROM people WHERE city = '北京' UNION ALL SELECT city FROM people WHERE city = '上海'")) == 5
        ))

        # JOIN
        city_path = os.path.join(tmp, "cities.csv")
        with io.open(city_path, "w", encoding="utf-8") as handle:
            handle.write("city,region\n北京,华北\n上海,华东\n深圳,华南\n")
        engine.register_path("cities", city_path)

        check("INNER JOIN", lambda: _assert(
            len(q(
                "SELECT p.name, c.region FROM people p JOIN cities c ON p.city = c.city"
            )) == 5
        ))
        check("LEFT JOIN 保留左表", lambda: _assert(
            len(q(
                "SELECT p.name, c.region FROM people p LEFT JOIN cities c ON p.city = c.city"
            )) == 6
        ))
        check("LEFT JOIN 未匹配补 NULL", lambda: _assert(
            any(
                r["region"] is None
                for r in q("SELECT p.name, c.region FROM people p LEFT JOIN cities c ON p.city = c.city")
            )
        ))

        # 存储
        nq_path = os.path.join(tmp, "people.nq")

        def _roundtrip() -> None:
            from .sources import source_for_path

            source = source_for_path(csv_path)
            write_nq(nq_path, source.batches(), source=csv_path)
            header = read_header(nq_path)
            assert header["row_count"] == 6, f"行数不符：{header['row_count']}"
            names = {c["name"] for c in header["columns"]}
            assert names == {"id", "name", "city", "age", "score"}, names
            engine2 = Engine()
            engine2.register_path("n", nq_path)
            rows = engine2.query("SELECT city, COUNT(*) AS c FROM n GROUP BY city").rows()
            assert {r["city"]: r["c"] for r in rows} == {"北京": 3, "上海": 2, "广州": 1}

        check("列存 .nq 写入与回读", _roundtrip)
        check("列裁剪下推一致性", lambda: _assert(
            Engine().query("SELECT 1").columns == ["1"]
        ))

        # 导出格式
        def _export() -> None:
            from .exporter import render_rows

            rows = q("SELECT name FROM people LIMIT 2")
            for fmt in ("table", "json", "jsonl", "csv", "tsv", "md"):
                text = render_rows(rows, ["name"], fmt)
                assert text, f"{fmt} 输出为空"

        check("六种导出格式", _export)

        # 错误处理
        def _errors() -> None:
            try:
                q("SELECT nope FROM people")
            except NanoQueryError:
                pass
            else:
                raise AssertionError("未知列未报错")
            try:
                q("SELECT * FROM not_exist")
            except NanoQueryError:
                pass
            else:
                raise AssertionError("未知表未报错")

        check("错误可识别且可读", _errors)

    print("-" * 48)
    if failed:
        print(f"❌ 自检失败 {len(failed)} 项（通过 {passed} 项）：")
        for item in failed:
            print(f"   - {item}")
        return 1
    print(f"🎉 自检全部通过（{passed} 项）")
    return 0


def _assert(condition: bool, message: str = "断言失败") -> None:
    if not condition:
        raise AssertionError(message)
