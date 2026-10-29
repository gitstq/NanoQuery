# Python API

除了 CLI，NanoQuery 也可以作为**嵌入式库**直接用在你的 Python 程序里。
依然零第三方依赖。

## 1. 一行式查询

```python
from nanoquery import query

result = query("SELECT city, COUNT(*) AS c FROM t GROUP BY city", t="sales.csv")
for row in result:
    print(row["city"], row["c"])
```

`query(sql, **tables)` 里的关键字参数即表名到文件路径的映射。

## 2. 复用引擎（推荐）

多次查询同一批文件时，复用 `Engine` 可以避免重复解析与类型推断：

```python
from nanoquery import Engine

engine = Engine(batch_size=4096)
engine.register_path("sales", "examples/sales.csv")
engine.register_path("city", "examples/city.csv")

top = engine.query("""
    SELECT c.region,
           COUNT(*)              AS orders,
           ROUND(SUM(s.amount),2) AS gmv
      FROM sales s
      JOIN city c ON s.city = c.city
     GROUP BY c.region
     ORDER BY gmv DESC
""")

print(top.columns)       # ['region', 'orders', 'gmv']
for row in top.rows():   # 物化成 list[dict]
    print(row)
```

`Result` 支持三种消费方式：

| 用法 | 说明 |
| --- | --- |
| `for row in result` | 惰性迭代，边算边给，适合大结果 |
| `result.rows()` | 一次性物化为 `List[Dict]` |
| `result.columns` | 输出列名列表 |

## 3. 内存数据（Batch）直接查询

```python
from nanoquery import Engine, Batch

engine = Engine()
engine.register("people", Batch({
    "name": ["alice", "bob", "carol"],
    "city": ["北京", "上海", "北京"],
    "age":  [31, 27, 45],
}))

print(engine.query("SELECT city, AVG(age) AS avg_age FROM people GROUP BY city").rows())
```

## 4. 数据源参数

```python
engine.register_path(
    "app",
    "app.log",
    log_pattern=r"^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<msg>.*)$",  # 日志字段抽取正则
)
engine.register_path("raw", "no_header.csv", no_header=True)   # 无表头
engine.register_path("semi", "semicolon.csv", delimiter=";")   # 自定义分隔符
engine.register_path("text", "weird.txt", fmt="csv")           # 显式指定格式
```

## 5. 结果导出

```python
from nanoquery.exporter import render_rows, iter_render, FORMATS

result = engine.query("SELECT city, COUNT(*) AS c FROM sales GROUP BY city")

markdown = render_rows(result.rows(), result.columns, "md")   # 全部格式：table/json/jsonl/csv/tsv/md

with open("out.jsonl", "w", encoding="utf-8") as f:           # 流式落盘，不占内存
    for chunk in iter_render(result, result.columns, "jsonl"):
        f.write(chunk + "\n")
```

## 6. 读写 `.nq` 列存

```python
from nanoquery.sources import source_for_path
from nanoquery.storage import write_nq, read_batches, read_header, read_column

# 写
source = source_for_path("sales.csv")
stats = write_nq("sales.nq", source.batches(), compress=True, source="sales.csv")
print(stats["row_count"], stats["bytes"])

# 读（可选列裁剪）
print(read_header("sales.nq")["columns"])
for batch in read_batches("sales.nq", columns=["city"]):
    print(batch.row_count, batch.column_names)

# 只读一列
print(read_column("sales.nq", "city")[:5])
```

## 7. 错误处理

```python
from nanoquery.types import NanoQueryError, ParseError, ResolveError, ExecutionError, StorageError

try:
    engine.query("SELECT nope FROM sales")
except ResolveError as exc:      # 列不存在
    print("列写错了：", exc)
except NanoQueryError as exc:    # 兜底：所有 NanoQuery 异常的父类
    print("查询失败：", exc)
```

## 8. 执行计划

```python
from nanoquery.parser import parse
from nanoquery.executor import Engine, unparse

engine = Engine()
engine.register_path("sales", "sales.csv")
plan = parse("SELECT city, COUNT(*) AS c FROM sales GROUP BY city HAVING COUNT(*) > 1")
print(plan)
```

CLI 里等价命令：`nanoquery explain "<SQL>" -t sales=sales.csv`。
