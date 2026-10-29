"""NanoQuery —— 零依赖嵌入式列式分析引擎。

直接在本地文件（CSV / JSONL / 日志 / .nq 列存）上执行 SQL，无需数据库服务、
无需导入数据、无需任何第三方依赖。

快速示例::

    from nanoquery import Engine

    engine = Engine()
    engine.register_path("people", "people.csv")
    for row in engine.query("SELECT city, COUNT(*) AS c FROM people GROUP BY city"):
        print(row)

一行式用法::

    from nanoquery import query

    rows = query("SELECT AVG(age) AS avg_age FROM t", t="people.csv").rows()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .batch import Batch
from .executor import Engine, Result, execute
from .parser import parse

__version__ = "1.0.0"
__author__ = "NanoQuery Contributors"
__license__ = "MIT"
__all__ = [
    "Engine", "Result", "Batch", "execute", "query", "connect", "__version__",
]


def query(sql: str, engine: Optional[Engine] = None, **tables) -> Result:
    """一行式入口：``query("SELECT ... FROM t", t="data.csv")``。

    Args:
        sql: SQL 查询语句。
        engine: 可选的既有引擎实例。
        **tables: 表名到文件路径的映射。

    Returns:
        :class:`~nanoquery.executor.Result`，可迭代或调用 ``.rows()``。
    """
    return execute(sql, engine=engine, **tables)


def connect(**tables) -> Engine:
    """创建引擎并批量注册文件表，返回引擎实例。"""
    engine = Engine()
    for name, path in tables.items():
        engine.register_path(name, str(path))
    return engine
