# NanoQuery 架构设计

> 目标：用**纯 Python 标准库**做出一个能真正跑起来的列式分析引擎，
> 而不是一个 SQL 解析器玩具。

## 1. 整体分层

```
      SQL 文本
         │
         ▼
   ┌───────────┐   lexer.py    词法：字符流 → Token 流（含位置偏移）
   │  Lexer    │
   └───────────┘
         ▼
   ┌───────────┐   parser.py   语法：递归下降 → AST（ast.py 的 dataclass）
   │  Parser   │
   └───────────┘
         ▼
   ┌───────────┐   executor.py 语义 + 执行：火山模型 / 向量化批处理
   │ Executor  │   ├─ Scope        列名解析（限定名 / 裸名 / 歧义检测）
   └───────────┘   ├─ eval_expr    表达式按列向量求值
         │         └─ 各算子：Scan/Filter/Project/HashAgg/HashJoin/Sort/Limit
         ▼
   ┌───────────┐   sources.py   数据源：CSV / JSONL / LOG / NQ
   │  Sources  │
   └───────────┘
         ▼
   ┌───────────┐   storage.py   .nq 列存：编码 + 压缩 + 列裁剪
   │  Storage  │
   └───────────┘
         ▼
   ┌───────────┐   exporter.py  结果渲染：table/json/jsonl/csv/tsv/md
   │ Exporter  │
   └───────────┘
```

## 2. 为什么是「批处理」而不是「一行一行」

CPython 里每次属性访问、函数调用都有固定开销，纯 Python 做逐行（row-at-a-time）
执行会慢到不可用。NanoQuery 采用 **向量化批处理（batch-at-a-time）**：

```python
class Batch:
    columns: Dict[str, List[Any]]   # 列名 -> 该批次的整列数组
    row_count: int
```

- 默认批大小 `4096` 行（可用 `--batch-size` 调整）；
- 表达式求值一次处理一整列（`eval_expr` 返回 `List[Any]`），
  摊薄了解释器开销；
- 数据以批为单位在算子间流动，内存占用恒定，**不会整表物化**。

## 3. 算子与流水线

`_execute_select()` 把一条 SELECT 组装成如下流水线（全部是生成器，惰性求值）：

```
Scan ──▶ Join ──▶ Filter ──▶ Aggregate/Project ──▶ Distinct ──▶ Sort ──▶ Limit
```

| 算子 | 实现要点 |
| --- | --- |
| Scan | 对 `.nq` 会做**列裁剪下推**：只反序列化 SQL 真正用到的列 |
| Filter | `eval_expr(where)` 得到 `List[bool|None]`，`Batch.mask()` 保留为真的行 |
| Project | 按 SELECT 列表求值，输出列名去重（`_dedupe_names`） |
| HashAgg | 增量累加器（`Aggregate.update/finalize`），流式分组，**不等全表** |
| HashJoin | 等值谓词拆分成 hash 键；非等值退化为带谓词的嵌套循环；小表常驻内存 |
| Sort | 唯一需要物化的算子（排序的固有代价），多键稳定排序 |
| Limit | 提前终止，配合 `--max-rows` 可做「抽样看一眼」 |

`RIGHT JOIN` 通过交换左右表并反转输出顺序实现，避免重复实现一套逻辑。

## 4. 类型系统

只有 5 种类型（`types.py`），但有三处关键设计：

1. **类型推断**：CSV 读入时先采样推断列类型，全 NULL 降级为 `NULL`，混排按
   `INT → FLOAT → STR` 提升；
2. **类型亲和**：比较数值与字符串时尝试把字符串解析成数字，贴近 SQLite 行为，
   避免用户在 `'10' > 9` 上踩坑；
3. **三值逻辑**：`compare_values()` 任一侧为 NULL 时返回 `None`（未知），
   由调用方决定「未知即过滤」。

## 5. `.nq` 列存格式

自研的极简列式文件（详见 [FORMAT.md](./FORMAT.md)）：

- 魔数 `NQ01` + JSON 头（行数、列 schema、来源）+ 每列独立 payload；
- 三种编码按数据特征自动选择：`DICT`（低基数）/ `RLE`（长游程）/ `RAW`；
- 每列可选 zlib 压缩，独立于编码开关；
- NULL 用位图保存，不占值空间。

实测 5000 行 × 6 列的销售数据：`175 KB CSV → 39 KB .nq`（约 4.4×）。

## 6. 流式输出

`exporter.iter_render()` 边查询边输出：

- `jsonl` / `csv` / `tsv`：逐行产出，天然流式；
- `table` / `md`：按 500 行分批渲染（每批独立对齐，牺牲跨批对齐换取首屏延迟）；
- `json`：逗号后置（缓存上一行）以保证输出始终是合法 JSON。

配合 `Result` 的迭代协议，`SELECT * FROM huge.csv | head` 这类管道用法
不会把整个结果读进内存。

## 7. 错误处理

异常层次清晰，且都携带**位置信息**：

```
NanoQueryError
├── ParseError      语法/词法错误（给出 Token 位置）
├── ResolveError    表/列解析失败（给出已注册的候选）
├── ExecutionError  执行期语义错误（如非聚合列出现在 GROUP BY 查询里）
└── StorageError    文件/格式错误
```

CLI 捕获后统一以 `❌ <消息>` 输出到 stderr 并返回退出码 `1`，
便于在 shell 脚本里判断成败。

## 8. 零依赖是怎么保证的

- 运行时只 `import` 标准库：`argparse`、`csv`、`json`、`re`、`zlib`、`struct`、
  `math`、`time`、`io`、`os`、`sys`、`typing`、`dataclasses`…
- `scripts/build.sh` 内含一段 AST 静态检查：扫描 `nanoquery/` 下所有
  `import` 语句，发现非白名单模块即构建失败；
- `pyproject.toml` 的 `dependencies = []` 与空的 `requirements.txt` 双重声明。
