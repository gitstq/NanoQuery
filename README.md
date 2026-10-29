<div align="center">

# 🔍 NanoQuery

**零依赖嵌入式列式分析引擎 · 直接用 SQL 查询本地文件**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-150%20passed-brightgreen)](#)

🌐 **[简体中文](#zh-cn)** ｜ **[繁體中文](#zh-tw)** ｜ **[English](#en)**

> 三种语言的内容完全一致，点击上方链接即可跳转。
> The three sections below are identical in content — just pick your language.

</div>

---

<a id="zh-cn"></a>

## 🇨🇳 简体中文

### 🎉 项目介绍

有没有过这种时刻：一个 200 MB 的 CSV 摆在面前，你只想问它一句「各城市 GMV 是多少」，
却要先装数据库、建表、写导入脚本、等它跑完——而整个过程只是为了跑一条 `GROUP BY`。

**NanoQuery** 就是为了消灭这段摩擦而生的。它是一个**嵌入式列式分析引擎**：

```bash
nanoquery "SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" sales.csv
```

没有服务进程，没有 `CREATE TABLE`，没有 `COPY FROM`，也没有 `pip install pandas`。
**文件在哪，就在哪查。**

它的几个硬指标：

| 维度 | 说明 |
| --- | --- |
| 🪶 零依赖 | 只用 Python 标准库，`pip install` 后不会拖来半个生态 |
| 🐍 兼容性 | Python 3.8+，Linux / macOS / Windows 全平台 |
| 📦 单文件起步 | 不装也能跑：`python -m nanoquery "<SQL>" data.csv` |
| 🧠 真 SQL | 完整的词法/语法/语义层，不是字符串切分的花架子 |
| ⚡ 列式执行 | 向量化批处理 + 哈希聚合 + 哈希连接，不做逐行解释 |
| 💾 自研列存 | `.nq` 格式支持字典/RLE 编码、zlib 压缩与列裁剪下推 |
| 🧩 可嵌入 | 也能当库用：`from nanoquery import Engine` |

**它不做什么**：不做 DDL/DML，不做事务，不做分布式，不替代 PostgreSQL 或
DuckDB。它专注一件事——**让「问本地数据一句话」这件事的成本降到接近零**。

---

### ✨ 核心特性

#### 🗄️ 四种数据源，开箱即用

| 类型 | 扩展名 | 能力 |
| --- | --- | --- |
| 📊 CSV / TSV | `.csv` `.tsv` `.txt` | 自动嗅探分隔符、自动类型推断、支持无表头 |
| 🧾 JSON Lines | `.jsonl` `.ndjson` | 自动展平嵌套对象，`user.name` 直接可查 |
| 📜 文本日志 | `.log` | 命名分组正则抽字段，附赠 `lineno` / `line` 辅助列 |
| 🧱 NanoQuery 列存 | `.nq` | 自研格式，体积极小、读取最快、支持列裁剪 |
| 🧠 内存数据 | — | `Batch` 或行字典序列可直接注册为表（嵌入式用法） |

#### 🧮 真正的 SQL 子集

- 投影、`WHERE`、`GROUP BY` / `HAVING`、`ORDER BY`（多键 + `NULLS FIRST|LAST`）
- `DISTINCT`、`LIMIT` / `OFFSET`、`UNION` / `UNION ALL`
- `INNER` / `LEFT` / `RIGHT` / `CROSS JOIN`（等值谓词走哈希连接）
- `FROM` 子句中的派生表（子查询）
- `CASE WHEN`、`CAST`、`BETWEEN`、`IN`、`LIKE`、`IS NULL`、算术/比较/逻辑运算
- SQLite 风格**类型亲和**与 **NULL 三值逻辑**

#### 🔧 40+ 内置函数

- 字符串：`UPPER` `LOWER` `TRIM` `SUBSTR` `REPLACE` `CONCAT_WS` `REVERSE` `INSTR` …
- 数值：`ABS` `ROUND` `CEIL` `FLOOR` `SQRT` `POWER` `EXP` `LN` `MOD` …
- 空值/选择：`COALESCE` `IFNULL` `NULLIF` `GREATEST` `LEAST` `TYPEOF`
- 聚合：`COUNT` `SUM` `AVG` `MIN` `MAX` `MEDIAN` `VARIANCE` `STDDEV` `GROUP_CONCAT`
  （部分支持 `DISTINCT`）

#### 💾 `.nq` 列存：不只是变小，更是变快

```
175,641 B  sales.csv   ──▶  39,938 B  sales.nq   （约 4.4×）
```

三种编码按数据特征自动择优：**DICT**（低基数）/ **RLE**（长游程）/ **RAW**，
每列独立决定是否启用 zlib。查询时只反序列化 SQL 真正用到的列——
`SELECT city, COUNT(*) FROM sales` 根本不会去碰 `amount` 那一列。

#### 📤 六种输出格式，覆盖「人眼看」到「机器读」

`table`（中文宽度对齐的终端表格）、`json`、`jsonl`、`csv`、`tsv`、`md`。
全部是**流式**渲染，配合管道可以边算边出，不把整张结果读进内存。

#### 🧪 自测与工程化

- `nanoquery selftest`：22 项端到端自检，一条命令证明引擎是好的
- `nanoquery explain`：查看执行计划
- `./scripts/build.sh`：语法检查 → **依赖纯净性 AST 检查** → 自检 → 单元测试

---

### 🚀 快速开始

#### 1️⃣ 安装

```bash
# 方式一：从源码安装（推荐，可得 nanoquery 命令）
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
pip install -e .

# 方式二：不安装，直接用模块方式运行
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
python3 -m nanoquery selftest
```

> 💡 运行时**零第三方依赖**；只有跑测试和打包才需要 `pip install -e ".[dev]"`。

#### 2️⃣ 三秒钟跑第一条 SQL

```bash
# 仓库自带示例数据
python3 -m nanoquery "SELECT city, COUNT(*) AS orders,
       ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" examples/sales.csv
```

```
┌──────┬────────┬───────────┐
│ city │ orders │ gmv       │
├──────┼────────┼───────────┤
│ 成都 │ 201    │ 107501.12 │
│ 北京 │ 197    │ 105536.18 │
│ 深圳 │ 198    │ 103423.98 │
│ 上海 │ 213    │ 103136.63 │
│ 杭州 │ 199    │ 99394.95  │
│ 广州 │ 192    │ 97522.91  │
└──────┴────────┴───────────┘
(6 行)
```

#### 3️⃣ 常见姿势速查

```bash
# 多个文件 + 显式表名
nanoquery "SELECT * FROM t LIMIT 5" -t t=data.csv

# 日志：用正则把一行切成列
nanoquery "SELECT level, COUNT(*) AS c FROM app GROUP BY level ORDER BY c DESC" \
  -t app=app.log --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<msg>.*)$'

# JSONL：嵌套字段直接下钻
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c FROM events GROUP BY event, user.vip" events.jsonl

# 转成 .nq 列存，再查一次（更快、更小）
nanoquery import data.csv -o data.nq -v
nanoquery "SELECT AVG(amount) AS a FROM data" -t data=data.nq

# 输出成 Markdown，直接粘进周报
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" sales.csv --format md

# 管道给 jq
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" sales.csv -f json | jq -r '.[] | .city'

# 交互式探索
nanoquery repl examples/sales.csv examples/city.csv
```

#### 4️⃣ Python 里当库用

```python
from nanoquery import Engine

engine = Engine()
engine.register_path("sales", "examples/sales.csv")

result = engine.query("""
    SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
      FROM sales GROUP BY city ORDER BY gmv DESC
""")

for row in result:          # 惰性迭代，边算边给
    print(row["city"], row["gmv"])
```

---

### 📖 详细使用指南

#### 🖥️ 命令行

```
nanoquery "<SQL>" [FILE ...] [选项]
nanoquery <子命令> [参数]
```

| 子命令 | 作用 |
| --- | --- |
| `repl` | 进入交互式 SQL 终端 |
| `schema` | 查看数据文件的 schema |
| `import` | 把数据文件转换成 `.nq` 列存 |
| `explain` | 查看查询执行计划 |
| `selftest` | 运行内置自检 |
| `functions` | 列出全部内置函数 |

常用选项：

| 选项 | 说明 |
| --- | --- |
| `-q, --sql` | 以选项形式传入 SQL（SQL 含特殊字符时更稳） |
| `-f, --file PATH` | 数据文件，可重复 |
| `-t, --table NAME=PATH` | 显式指定表名 |
| `--format FMT` | `table`/`json`/`jsonl`/`csv`/`tsv`/`md` |
| `-o, --output PATH` | 结果写入文件 |
| `--delimiter` | CSV 分隔符（默认自动嗅探） |
| `--no-header` | CSV 无表头 |
| `--log-pattern` | 日志字段抽取正则（命名分组） |
| `--batch-size N` | 批处理行数（默认 4096） |
| `--max-rows N` | 最多输出 N 行，0 表示不限 |
| `--encoding` | 文件编码（默认 utf-8） |
| `-v, --verbose` | 输出耗时等诊断信息 |
| `--quiet` | 静默模式，只输出结果 |

#### 🔤 SQL 速查

完整语法见 [docs/SQL-REFERENCE.md](./docs/SQL-REFERENCE.md)。

```sql
-- 分组 + 过滤分组 + 排序 + 分页
SELECT city, COUNT(*) AS c, ROUND(AVG(amount), 2) AS avg_amt
  FROM sales
 WHERE amount > 100
 GROUP BY city
HAVING COUNT(*) > 50
 ORDER BY avg_amt DESC
 LIMIT 10;

-- 连接
SELECT c.region, COUNT(*) AS orders, ROUND(SUM(s.amount), 2) AS gmv
  FROM sales s
  JOIN city c ON s.city = c.city
 GROUP BY c.region
 ORDER BY gmv DESC;

-- 派生表 + CASE 打标
SELECT tier, COUNT(*) AS n FROM (
  SELECT CASE WHEN amount >= 800 THEN 'high'
              WHEN amount >= 400 THEN 'mid'
              ELSE 'low' END AS tier
    FROM sales
) GROUP BY tier ORDER BY n DESC;

-- UNION
SELECT city FROM sales WHERE city = '北京'
UNION ALL
SELECT city FROM sales WHERE city = '深圳';
```

**`ORDER BY` 支持四类写法**：输出别名、`SELECT` 列表中的列名、位置序号
（`ORDER BY 2`），以及**没有出现在 SELECT 列表里的输入列**
（如 `SELECT name FROM people p JOIN city c ... ORDER BY p.age`）。

#### 📜 日志查询实战

`.log` 默认整行作为一个 `line` 列；给一条带命名分组的正则，就能把一行切成结构化的列：

```bash
nanoquery "SELECT level, COUNT(*) AS c, ROUND(AVG(cost), 1) AS avg_ms, MAX(cost) AS max_ms
  FROM app GROUP BY level ORDER BY avg_ms DESC" \
  -t app=app.log \
  --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<svc>[\w-]+) .*took (?P<cost>\d+)ms'
```

#### 🧾 JSON Lines 嵌套下钻

```json
{"id": 1, "user": {"name": "alice", "vip": true}, "event": "view", "value": 10}
```

引擎会把嵌套对象展平成 `user.name` / `user.vip`，直接写进 SQL 即可：

```bash
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c, AVG(value) AS avg_value
  FROM events GROUP BY event, user.vip ORDER BY c DESC" events.jsonl
```

#### 🧠 嵌入式 API

```python
from nanoquery import Engine, Batch

engine = Engine()
engine.register_path("sales", "examples/sales.csv")
engine.register_data("small", [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])   # 内存表
engine.register("inline", Batch({"id": [1, 2], "v": [10, 20]}))           # 内存批

print(engine.schema())            # 所有表的列与类型
print(engine.query("SELECT * FROM inline").rows())
```

更多见 [docs/PYTHON-API.md](./docs/PYTHON-API.md)。

#### 🖲️ REPL 元命令

| 命令 | 作用 |
| --- | --- |
| `\dt` | 列出已注册的表 |
| `\d NAME` | 查看指定表的 schema |
| `\format FMT` | 切换输出格式 |
| `\timing` | 开关耗时统计 |
| `\help` | 显示帮助 |
| `\quit` | 退出（Ctrl-D 亦可） |

#### ⚠️ 暂不支持

标量子查询、相关子查询、`WITH` CTE、窗口函数，以及一切 DDL/DML。
遇到不支持的语法会抛出**带位置信息**的中文错误，而不是崩溃。

---

### 💡 设计思路与迭代规划

#### 🏗️ 为什么这么设计

**1. 批处理而不是逐行。** CPython 的函数调用与属性访问开销很实在，纯 Python
逐行执行会慢到不可用。所以 NanoQuery 的最小数据单元是 `Batch`
（`Dict[str, List[Any]]`，默认 4096 行），表达式求值一次处理一整列，
把解释器开销摊薄。

**2. 火山模型 + 生成器。** `Scan → Join → Filter → Aggregate/Project →
Distinct → Sort → Limit` 全部以生成器串起来，内存占用恒定。
只有排序是必须物化的（这是排序的固有代价）。

**3. 哈希聚合是流式的。** 分组状态增量更新，不需要等全表读完，
配合 `LIMIT` 可以提前出结果。

**4. 列裁剪下推。** `.nq` 读取时只看 SQL 用到的列，其余列的 payload
连解压都不会发生。

**5. 零依赖是设计约束，不是巧合。** `scripts/build.sh` 里有一段 AST 检查，
扫描 `nanoquery/` 下所有 `import`，发现标准库白名单之外的模块就直接构建失败。

架构细节见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)，
文件格式见 [docs/FORMAT.md](./docs/FORMAT.md)。

#### 🗺️ 迭代规划

| 版本 | 主题 | 内容 |
| --- | --- | --- |
| **v1.0.x** | 稳定化 | 缺陷修复、错误信息打磨、更多边界用例测试 |
| **v1.1** | 易用性 | `WITH` CTE、`EXISTS`、标量子查询、`VALUES` 子句 |
| **v1.2** | 分析能力 | 窗口函数（`ROW_NUMBER` / `RANK` / `LAG`）、`PIVOT` 语法糖 |
| **v1.3** | 性能 | 谓词下推到 `.nq` 的字典编码层、并行扫描、`TOP-N` 优化排序 |
| **v1.4** | 生态 | Parquet / Arrow IPC 只读适配、`.nq` 追加写与分区目录 |
| **v2.0** | 形态拓展 | 可选 Rust/C 加速后端（仍保持默认零依赖） |

---

### 📦 打包与部署指南

本项目属于**库 / CLI 工具**，因此**不需要**发布带二进制产物的 GitHub Release；
按语义化版本打 tag，并提供安装与集成文档即可。

#### 📥 安装方式

```bash
# 从源码安装（最通用）
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
pip install .

# 开发模式（改动即时生效）
pip install -e ".[dev]"

# 免安装运行
PYTHONPATH=. python3 -m nanoquery selftest
```

安装后得到 `nanoquery` 控制台命令（由 `pyproject.toml` 的
`[project.scripts]` 声明）。

#### 🏗️ 本地构建

```bash
./scripts/build.sh          # 语法 + 依赖纯净性 + 自检 + 单元测试
./scripts/build.sh dist     # 额外产出 dist/ 下的 wheel 与 sdist
./scripts/build.sh clean    # 清理产物
```

也可直接用标准工具链：

```bash
python -m build
python -m twine check dist/*
```

#### 🔌 集成到你的项目

**作为 CLI 子进程：**

```python
import subprocess, json

out = subprocess.run(
    ["nanoquery", "SELECT city, COUNT(*) AS c FROM t GROUP BY city",
     "-t", "t=data.csv", "--format", "json"],
    capture_output=True, text=True, check=True,
)
rows = json.loads(out.stdout)
```

**作为嵌入式库：**

```python
from nanoquery import Engine

engine = Engine(batch_size=8192)          # 大文件可调大批尺寸
engine.register_path("sales", "sales.csv")
rows = engine.query("SELECT city, SUM(amount) AS gmv FROM sales GROUP BY city").rows()
```

#### 🔖 版本与 tag

```bash
git tag -a v1.0.0 -m "feat: NanoQuery 首个正式版本"
git push origin v1.0.0
```

#### 🧪 CI

GitHub Actions 覆盖 Python 3.8–3.12 × Linux/macOS/Windows，
每次提交都会跑「零依赖自检 → CLI 冒烟 → 单元测试 → 构建分发包」。

---

### 🤝 贡献指南

欢迎 Issue 与 PR。请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，要点如下：

1. 🪶 **零第三方依赖**是硬约束，CI 会卡；
2. 🐍 兼容 Python 3.8；
3. 🧪 新功能请同步补测试，提交前 `./scripts/build.sh` 全绿；
4. 📝 提交信息遵循 **Angular 规范**：
   `feat(executor): 支持 ORDER BY 引用未投影的输入列`
5. 📚 涉及 SQL 语义或文件格式变更，请同步更新 `docs/`。

---

### 📄 开源协议

[MIT License](./LICENSE) © 2026 gitstq —— 可自由使用、修改、分发与商用，
只需保留版权声明。

🌐 切换语言：[简体中文](#zh-cn) ｜ [繁體中文](#zh-tw) ｜ [English](#en)

---

<a id="zh-tw"></a>

## 🇹🇼 繁體中文

### 🎉 專案介紹

你有沒有過這種時刻：一個 200 MB 的 CSV 就躺在硬碟裡，你只想問它一句
「各城市的 GMV 是多少」，卻得先裝資料庫、建表、寫匯入腳本、等它跑完——
而這整段折騰，只為了跑一條 `GROUP BY`。

**NanoQuery** 就是為了消滅這段摩擦而生的。它是一個**嵌入式欄式分析引擎**：

```bash
nanoquery "SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" sales.csv
```

沒有服務行程，沒有 `CREATE TABLE`，沒有 `COPY FROM`，也不必 `pip install pandas`。
**檔案在哪裡，就在哪裡查。**

幾個硬指標：

| 面向 | 說明 |
| --- | --- |
| 🪶 零依賴 | 只用 Python 標準函式庫，安裝後不會拖來半個生態系 |
| 🐍 相容性 | Python 3.8+，Linux / macOS / Windows 全平台 |
| 📦 免安裝可跑 | `python -m nanoquery "<SQL>" data.csv` |
| 🧠 真 SQL | 完整的詞法／語法／語意層，不是字串切割的花架子 |
| ⚡ 欄式執行 | 向量化批次處理＋雜湊聚合＋雜湊連接，不做逐列直譯 |
| 💾 自研欄存 | `.nq` 格式支援字典／RLE 編碼、zlib 壓縮與欄裁剪下推 |
| 🧩 可嵌入 | 也能當函式庫用：`from nanoquery import Engine` |

**它不做什麼**：不做 DDL/DML、不做交易、不做分散式，也不打算取代 PostgreSQL
或 DuckDB。它只專注一件事——**讓「問本地資料一句話」的成本降到趨近於零**。

---

### ✨ 核心特性

#### 🗄️ 四種資料來源，開箱即用

| 類型 | 副檔名 | 能力 |
| --- | --- | --- |
| 📊 CSV / TSV | `.csv` `.tsv` `.txt` | 自動嗅探分隔符、自動型別推斷、支援無標頭 |
| 🧾 JSON Lines | `.jsonl` `.ndjson` | 自動攤平巢狀物件，`user.name` 直接可查 |
| 📜 文字日誌 | `.log` | 具名群組正則抽欄位，附贈 `lineno` / `line` 輔助欄 |
| 🧱 NanoQuery 欄存 | `.nq` | 自研格式，體積極小、讀取最快、支援欄裁剪 |
| 🧠 記憶體資料 | — | `Batch` 或列字典序列可直接註冊成表（嵌入式用法） |

#### 🧮 真正能打的 SQL 子集

- 投影、`WHERE`、`GROUP BY` / `HAVING`、`ORDER BY`（多鍵＋`NULLS FIRST|LAST`）
- `DISTINCT`、`LIMIT` / `OFFSET`、`UNION` / `UNION ALL`
- `INNER` / `LEFT` / `RIGHT` / `CROSS JOIN`（等值條件走雜湊連接）
- `FROM` 子句中的衍生表（子查詢）
- `CASE WHEN`、`CAST`、`BETWEEN`、`IN`、`LIKE`、`IS NULL`、算術／比較／邏輯運算
- SQLite 風格**型別親和**與 **NULL 三值邏輯**

#### 🔧 40+ 內建函式

- 字串：`UPPER` `LOWER` `TRIM` `SUBSTR` `REPLACE` `CONCAT_WS` `REVERSE` `INSTR` …
- 數值：`ABS` `ROUND` `CEIL` `FLOOR` `SQRT` `POWER` `EXP` `LN` `MOD` …
- 空值／選擇：`COALESCE` `IFNULL` `NULLIF` `GREATEST` `LEAST` `TYPEOF`
- 聚合：`COUNT` `SUM` `AVG` `MIN` `MAX` `MEDIAN` `VARIANCE` `STDDEV` `GROUP_CONCAT`
  （部分支援 `DISTINCT`）

#### 💾 `.nq` 欄存：不只是變小，更是變快

```
175,641 B  sales.csv   ──▶  39,938 B  sales.nq   （約 4.4×）
```

三種編碼依資料特徵自動擇優：**DICT**（低基數）／**RLE**（長遊程）／**RAW**，
每欄獨立決定是否啟用 zlib。查詢時只反序列化 SQL 真正用到的欄——
`SELECT city, COUNT(*) FROM sales` 根本不會去碰 `amount` 那一欄。

#### 📤 六種輸出格式，從「人眼看」到「機器讀」

`table`（中文寬度對齊的終端表格）、`json`、`jsonl`、`csv`、`tsv`、`md`。
全部是**串流**渲染，搭配管線可以邊算邊出，不把整份結果讀進記憶體。

#### 🧪 自檢與工程化

- `nanoquery selftest`：22 項端到端自檢，一條命令證明引擎是好的
- `nanoquery explain`：檢視執行計畫
- `./scripts/build.sh`：語法檢查 → **依賴純淨性 AST 檢查** → 自檢 → 單元測試

---

### 🚀 快速開始

#### 1️⃣ 安裝

```bash
# 方式一：從原始碼安裝（推薦，可取得 nanoquery 指令）
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
pip install -e .

# 方式二：不安裝，直接用模組方式執行
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
python3 -m nanoquery selftest
```

> 💡 執行期**零第三方依賴**；只有跑測試與打包才需要 `pip install -e ".[dev]"`。

#### 2️⃣ 三秒鐘跑第一條 SQL

```bash
python3 -m nanoquery "SELECT city, COUNT(*) AS orders,
       ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" examples/sales.csv
```

```
┌──────┬────────┬───────────┐
│ city │ orders │ gmv       │
├──────┼────────┼───────────┤
│ 成都 │ 201    │ 107501.12 │
│ 北京 │ 197    │ 105536.18 │
│ 深圳 │ 198    │ 103423.98 │
│ 上海 │ 213    │ 103136.63 │
│ 杭州 │ 199    │ 99394.95  │
│ 广州 │ 192    │ 97522.91  │
└──────┴────────┴───────────┘
(6 行)
```

#### 3️⃣ 常見姿勢速查

```bash
# 多個檔案＋明確指定表名
nanoquery "SELECT * FROM t LIMIT 5" -t t=data.csv

# 日誌：用正則把一行切成欄
nanoquery "SELECT level, COUNT(*) AS c FROM app GROUP BY level ORDER BY c DESC" \
  -t app=app.log --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<msg>.*)$'

# JSONL：巢狀欄位直接下鑽
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c FROM events GROUP BY event, user.vip" events.jsonl

# 轉成 .nq 欄存，再查一次（更快、更小）
nanoquery import data.csv -o data.nq -v
nanoquery "SELECT AVG(amount) AS a FROM data" -t data=data.nq

# 輸出成 Markdown，直接貼進週報
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" sales.csv --format md

# 管線給 jq
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" sales.csv -f json | jq -r '.[] | .city'

# 互動式探索
nanoquery repl examples/sales.csv examples/city.csv
```

#### 4️⃣ 在 Python 裡當函式庫用

```python
from nanoquery import Engine

engine = Engine()
engine.register_path("sales", "examples/sales.csv")

result = engine.query("""
    SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
      FROM sales GROUP BY city ORDER BY gmv DESC
""")

for row in result:          # 惰性迭代，邊算邊給
    print(row["city"], row["gmv"])
```

---

### 📖 詳細使用指南

#### 🖥️ 命令列

```
nanoquery "<SQL>" [FILE ...] [選項]
nanoquery <子命令> [參數]
```

| 子命令 | 作用 |
| --- | --- |
| `repl` | 進入互動式 SQL 終端 |
| `schema` | 檢視資料檔案的 schema |
| `import` | 把資料檔案轉換成 `.nq` 欄存 |
| `explain` | 檢視查詢執行計畫 |
| `selftest` | 執行內建自檢 |
| `functions` | 列出全部內建函式 |

常用選項：

| 選項 | 說明 |
| --- | --- |
| `-q, --sql` | 以選項形式帶入 SQL（SQL 含特殊字元時更穩） |
| `-f, --file PATH` | 資料檔案，可重複 |
| `-t, --table NAME=PATH` | 明確指定表名 |
| `--format FMT` | `table`/`json`/`jsonl`/`csv`/`tsv`/`md` |
| `-o, --output PATH` | 結果寫入檔案 |
| `--delimiter` | CSV 分隔符（預設自動嗅探） |
| `--no-header` | CSV 無標頭 |
| `--log-pattern` | 日誌欄位抽取正則（具名群組） |
| `--batch-size N` | 批次處理列數（預設 4096） |
| `--max-rows N` | 最多輸出 N 列，0 表示不限 |
| `--encoding` | 檔案編碼（預設 utf-8） |
| `-v, --verbose` | 輸出耗時等診斷資訊 |
| `--quiet` | 靜默模式，只輸出結果 |

#### 🔤 SQL 速查

完整語法見 [docs/SQL-REFERENCE.md](./docs/SQL-REFERENCE.md)。

```sql
-- 分組＋過濾分組＋排序＋分頁
SELECT city, COUNT(*) AS c, ROUND(AVG(amount), 2) AS avg_amt
  FROM sales
 WHERE amount > 100
 GROUP BY city
HAVING COUNT(*) > 50
 ORDER BY avg_amt DESC
 LIMIT 10;

-- 連接
SELECT c.region, COUNT(*) AS orders, ROUND(SUM(s.amount), 2) AS gmv
  FROM sales s
  JOIN city c ON s.city = c.city
 GROUP BY c.region
 ORDER BY gmv DESC;

-- 衍生表＋CASE 打標
SELECT tier, COUNT(*) AS n FROM (
  SELECT CASE WHEN amount >= 800 THEN 'high'
              WHEN amount >= 400 THEN 'mid'
              ELSE 'low' END AS tier
    FROM sales
) GROUP BY tier ORDER BY n DESC;

-- UNION
SELECT city FROM sales WHERE city = '北京'
UNION ALL
SELECT city FROM sales WHERE city = '深圳';
```

**`ORDER BY` 支援四種寫法**：輸出別名、`SELECT` 清單中的欄名、位置序號
（`ORDER BY 2`），以及**沒有出現在 SELECT 清單裡的輸入欄**
（如 `SELECT name FROM people p JOIN city c ... ORDER BY p.age`）。

#### 📜 日誌查詢實戰

`.log` 預設整行作為一個 `line` 欄；給一條帶具名群組的正則，就能把一行切成結構化欄位：

```bash
nanoquery "SELECT level, COUNT(*) AS c, ROUND(AVG(cost), 1) AS avg_ms, MAX(cost) AS max_ms
  FROM app GROUP BY level ORDER BY avg_ms DESC" \
  -t app=app.log \
  --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<svc>[\w-]+) .*took (?P<cost>\d+)ms'
```

#### 🧾 JSON Lines 巢狀下鑽

```json
{"id": 1, "user": {"name": "alice", "vip": true}, "event": "view", "value": 10}
```

引擎會把巢狀物件攤平成 `user.name` / `user.vip`，直接寫進 SQL 即可：

```bash
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c, AVG(value) AS avg_value
  FROM events GROUP BY event, user.vip ORDER BY c DESC" events.jsonl
```

#### 🧠 嵌入式 API

```python
from nanoquery import Engine, Batch

engine = Engine()
engine.register_path("sales", "examples/sales.csv")
engine.register_data("small", [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])   # 記憶體表
engine.register("inline", Batch({"id": [1, 2], "v": [10, 20]}))           # 記憶體批次

print(engine.schema())            # 所有表的欄位與型別
print(engine.query("SELECT * FROM inline").rows())
```

更多見 [docs/PYTHON-API.md](./docs/PYTHON-API.md)。

#### 🖲️ REPL 元命令

| 命令 | 作用 |
| --- | --- |
| `\dt` | 列出已註冊的表 |
| `\d NAME` | 檢視指定表的 schema |
| `\format FMT` | 切換輸出格式 |
| `\timing` | 開關耗時統計 |
| `\help` | 顯示說明 |
| `\quit` | 離開（Ctrl-D 亦可） |

#### ⚠️ 暫不支援

純量子查詢、相關子查詢、`WITH` CTE、視窗函式，以及一切 DDL/DML。
遇到不支援的語法會拋出**帶位置資訊**的中文錯誤，而不是崩潰。

---

### 💡 設計思路與迭代規劃

#### 🏗️ 為什麼這樣設計

**1. 批次處理而不是逐列。** CPython 的函式呼叫與屬性存取開銷很實在，純 Python
逐列執行會慢到不能用。所以 NanoQuery 的最小資料單元是 `Batch`
（`Dict[str, List[Any]]`，預設 4096 列），運算式求值一次處理一整欄，
把直譯器開銷攤薄。

**2. 火山模型＋生成器。** `Scan → Join → Filter → Aggregate/Project →
Distinct → Sort → Limit` 全部以生成器串起來，記憶體佔用恆定。
只有排序是必須物化的（這是排序的固有代價）。

**3. 雜湊聚合是串流的。** 分組狀態增量更新，不必等全表讀完，
搭配 `LIMIT` 可以提早出結果。

**4. 欄裁剪下推。** `.nq` 讀取時只看 SQL 用到的欄，其餘欄的 payload
連解壓都不會發生。

**5. 零依賴是設計約束，不是巧合。** `scripts/build.sh` 內有一段 AST 檢查，
掃描 `nanoquery/` 下所有 `import`，發現標準函式庫白名單之外的模組就直接建置失敗。

架構細節見 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)，
檔案格式見 [docs/FORMAT.md](./docs/FORMAT.md)。

#### 🗺️ 迭代規劃

| 版本 | 主題 | 內容 |
| --- | --- | --- |
| **v1.0.x** | 穩定化 | 缺陷修復、錯誤訊息打磨、更多邊界案例測試 |
| **v1.1** | 易用性 | `WITH` CTE、`EXISTS`、純量子查詢、`VALUES` 子句 |
| **v1.2** | 分析能力 | 視窗函式（`ROW_NUMBER` / `RANK` / `LAG`）、`PIVOT` 語法糖 |
| **v1.3** | 效能 | 謂詞下推到 `.nq` 的字典編碼層、平行掃描、`TOP-N` 最佳化排序 |
| **v1.4** | 生態 | Parquet / Arrow IPC 唯讀適配、`.nq` 追加寫與分區目錄 |
| **v2.0** | 形態拓展 | 可選 Rust/C 加速後端（仍維持預設零依賴） |

---

### 📦 打包與部署指南

本專案屬於**函式庫／CLI 工具**，因此**不需要**發布帶二進位產物的 GitHub Release；
依語意化版本打 tag，並提供安裝與整合文件即可。

#### 📥 安裝方式

```bash
# 從原始碼安裝（最通用）
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
pip install .

# 開發模式（改動即時生效）
pip install -e ".[dev]"

# 免安裝執行
PYTHONPATH=. python3 -m nanoquery selftest
```

安裝後會得到 `nanoquery` 主控台指令（由 `pyproject.toml` 的
`[project.scripts]` 宣告）。

#### 🏗️ 本地建置

```bash
./scripts/build.sh          # 語法＋依賴純淨性＋自檢＋單元測試
./scripts/build.sh dist     # 額外產出 dist/ 下的 wheel 與 sdist
./scripts/build.sh clean    # 清除產物
```

也可直接用標準工具鏈：

```bash
python -m build
python -m twine check dist/*
```

#### 🔌 整合進你的專案

**作為 CLI 子行程：**

```python
import subprocess, json

out = subprocess.run(
    ["nanoquery", "SELECT city, COUNT(*) AS c FROM t GROUP BY city",
     "-t", "t=data.csv", "--format", "json"],
    capture_output=True, text=True, check=True,
)
rows = json.loads(out.stdout)
```

**作為嵌入式函式庫：**

```python
from nanoquery import Engine

engine = Engine(batch_size=8192)          # 大檔案可調大批次大小
engine.register_path("sales", "sales.csv")
rows = engine.query("SELECT city, SUM(amount) AS gmv FROM sales GROUP BY city").rows()
```

#### 🔖 版本與 tag

```bash
git tag -a v1.0.0 -m "feat: NanoQuery 首個正式版本"
git push origin v1.0.0
```

#### 🧪 CI

GitHub Actions 涵蓋 Python 3.8–3.12 × Linux/macOS/Windows，
每次提交都會跑「零依賴自檢 → CLI 冒煙 → 單元測試 → 建置發行包」。

---

### 🤝 貢獻指南

歡迎 Issue 與 PR。請閱讀 [CONTRIBUTING.md](./CONTRIBUTING.md)，重點如下：

1. 🪶 **零第三方依賴**是硬約束，CI 會擋；
2. 🐍 相容 Python 3.8；
3. 🧪 新功能請同步補測試，提交前 `./scripts/build.sh` 全綠；
4. 📝 提交訊息遵循 **Angular 規範**：
   `feat(executor): 支援 ORDER BY 引用未投影的輸入欄`
5. 📚 涉及 SQL 語意或檔案格式變更，請同步更新 `docs/`。

---

### 📄 開源協議

[MIT License](./LICENSE) © 2026 gitstq —— 可自由使用、修改、散佈與商用，
只需保留版權聲明。

🌐 切換語言：[简体中文](#zh-cn) ｜ [繁體中文](#zh-tw) ｜ [English](#en)

---

<a id="en"></a>

## 🇺🇸 English

### 🎉 Project Introduction

We have all been there: a 200 MB CSV is sitting on disk, you want to ask it one
question — *"what is the GMV per city?"* — and somehow that requires installing a
database, creating a table, writing an import script, and waiting. All that
ceremony, for a single `GROUP BY`.

**NanoQuery** exists to delete that friction. It is an **embedded columnar
analytics engine**:

```bash
nanoquery "SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" sales.csv
```

No server process. No `CREATE TABLE`. No `COPY FROM`. No `pip install pandas`.
**Query the file where the file already is.**

The numbers that matter:

| Dimension | Detail |
| --- | --- |
| 🪶 Zero dependencies | Python standard library only — nothing else gets pulled in |
| 🐍 Portability | Python 3.8+, Linux / macOS / Windows |
| 📦 Runs uninstalled | `python -m nanoquery "<SQL>" data.csv` |
| 🧠 Real SQL | Full lexer / parser / analyzer — not string slicing in disguise |
| ⚡ Columnar execution | Vectorized batches, hash aggregation, hash joins |
| 💾 Custom columnar file | `.nq` with dictionary/RLE encoding, zlib, column pruning |
| 🧩 Embeddable | Also works as a library: `from nanoquery import Engine` |

**What it deliberately does not do:** no DDL/DML, no transactions, no
distribution, and no attempt to replace PostgreSQL or DuckDB. It does exactly one
thing — **drive the cost of asking a local file a question down to near zero**.

---

### ✨ Key Features

#### 🗄️ Four data sources, zero setup

| Kind | Extensions | Capability |
| --- | --- | --- |
| 📊 CSV / TSV | `.csv` `.tsv` `.txt` | Delimiter sniffing, type inference, headerless support |
| 🧾 JSON Lines | `.jsonl` `.ndjson` | Nested objects flattened — `user.name` is queryable |
| 📜 Text logs | `.log` | Named-group regex extraction, plus `lineno` / `line` |
| 🧱 NanoQuery columnar | `.nq` | Smallest and fastest, with column pruning |
| 🧠 In-memory | — | Register a `Batch` or a list of dicts as a table |

#### 🧮 A genuinely useful SQL subset

- Projection, `WHERE`, `GROUP BY` / `HAVING`, `ORDER BY` (multi-key, `NULLS FIRST|LAST`)
- `DISTINCT`, `LIMIT` / `OFFSET`, `UNION` / `UNION ALL`
- `INNER` / `LEFT` / `RIGHT` / `CROSS JOIN` (equi-predicates use hash joins)
- Derived tables (subqueries) in the `FROM` clause
- `CASE WHEN`, `CAST`, `BETWEEN`, `IN`, `LIKE`, `IS NULL`, arithmetic / comparison / logic
- SQLite-style **type affinity** and **three-valued NULL logic**

#### 🔧 40+ built-in functions

- String: `UPPER` `LOWER` `TRIM` `SUBSTR` `REPLACE` `CONCAT_WS` `REVERSE` `INSTR` …
- Numeric: `ABS` `ROUND` `CEIL` `FLOOR` `SQRT` `POWER` `EXP` `LN` `MOD` …
- Null / choice: `COALESCE` `IFNULL` `NULLIF` `GREATEST` `LEAST` `TYPEOF`
- Aggregate: `COUNT` `SUM` `AVG` `MIN` `MAX` `MEDIAN` `VARIANCE` `STDDEV`
  `GROUP_CONCAT` (several support `DISTINCT`)

#### 💾 `.nq`: smaller *and* faster

```
175,641 B  sales.csv   ──▶  39,938 B  sales.nq   (~4.4×)
```

One of three encodings is chosen per column based on its shape —
**DICT** (low cardinality) / **RLE** (long runs) / **RAW** — and each column
decides independently whether to use zlib. Queries only deserialize the columns
they actually touch: `SELECT city, COUNT(*) FROM sales` never looks at `amount`.

#### 📤 Six output formats, from "human" to "machine"

`table` (CJK-width-aware terminal grid), `json`, `jsonl`, `csv`, `tsv`, `md`.
All rendered **incrementally**, so piped output streams instead of buffering the
whole result.

#### 🧪 Self-checks and engineering hygiene

- `nanoquery selftest` — 22 end-to-end assertions in one command
- `nanoquery explain` — inspect the execution plan
- `./scripts/build.sh` — syntax → **dependency-purity AST check** → selftest → unit tests

---

### 🚀 Quick Start

#### 1️⃣ Install

```bash
# Option 1: install from source (recommended, gives you the `nanoquery` command)
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
pip install -e .

# Option 2: no install at all, run it as a module
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
python3 -m nanoquery selftest
```

> 💡 **Zero runtime dependencies.** `pip install -e ".[dev]"` is only needed for
> running tests and building packages.

#### 2️⃣ Your first query in three seconds

```bash
python3 -m nanoquery "SELECT city, COUNT(*) AS orders,
       ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" examples/sales.csv
```

```
┌──────┬────────┬───────────┐
│ city │ orders │ gmv       │
├──────┼────────┼───────────┤
│ 成都 │ 201    │ 107501.12 │
│ 北京 │ 197    │ 105536.18 │
│ 深圳 │ 198    │ 103423.98 │
│ 上海 │ 213    │ 103136.63 │
│ 杭州 │ 199    │ 99394.95  │
│ 广州 │ 192    │ 97522.91  │
└──────┴────────┴───────────┘
(6 行)
```

#### 3️⃣ Everyday patterns

```bash
# Multiple files with explicit table names
nanoquery "SELECT * FROM t LIMIT 5" -t t=data.csv

# Logs: turn a line into columns with a regex
nanoquery "SELECT level, COUNT(*) AS c FROM app GROUP BY level ORDER BY c DESC" \
  -t app=app.log --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<msg>.*)$'

# JSONL: drill into nested fields
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c FROM events GROUP BY event, user.vip" events.jsonl

# Convert to .nq once, then query it again (smaller and faster)
nanoquery import data.csv -o data.nq -v
nanoquery "SELECT AVG(amount) AS a FROM data" -t data=data.nq

# Markdown output, ready to paste into your weekly report
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" sales.csv --format md

# Pipe to jq
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" sales.csv -f json | jq -r '.[] | .city'

# Explore interactively
nanoquery repl examples/sales.csv examples/city.csv
```

#### 4️⃣ Use it as a library

```python
from nanoquery import Engine

engine = Engine()
engine.register_path("sales", "examples/sales.csv")

result = engine.query("""
    SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
      FROM sales GROUP BY city ORDER BY gmv DESC
""")

for row in result:          # lazy: computed as you consume it
    print(row["city"], row["gmv"])
```

---

### 📖 Detailed Usage

#### 🖥️ Command line

```
nanoquery "<SQL>" [FILE ...] [options]
nanoquery <subcommand> [args]
```

| Subcommand | Purpose |
| --- | --- |
| `repl` | Interactive SQL terminal |
| `schema` | Inspect a data file's schema |
| `import` | Convert a data file to `.nq` columnar format |
| `explain` | Show the query execution plan |
| `selftest` | Run the built-in self-check |
| `functions` | List every built-in function |

Common options:

| Option | Meaning |
| --- | --- |
| `-q, --sql` | Pass SQL as an option (safer with shell metacharacters) |
| `-f, --file PATH` | Data file, repeatable |
| `-t, --table NAME=PATH` | Explicit table name |
| `--format FMT` | `table`/`json`/`jsonl`/`csv`/`tsv`/`md` |
| `-o, --output PATH` | Write results to a file |
| `--delimiter` | CSV delimiter (sniffed by default) |
| `--no-header` | CSV has no header row |
| `--log-pattern` | Regex with named groups for log parsing |
| `--batch-size N` | Rows per batch (default 4096) |
| `--max-rows N` | Cap output at N rows, 0 = unlimited |
| `--encoding` | File encoding (default utf-8) |
| `-v, --verbose` | Timing and diagnostics |
| `--quiet` | Only print the result |

#### 🔤 SQL cheat sheet

Full grammar: [docs/SQL-REFERENCE.md](./docs/SQL-REFERENCE.md).

```sql
-- group, filter groups, sort, paginate
SELECT city, COUNT(*) AS c, ROUND(AVG(amount), 2) AS avg_amt
  FROM sales
 WHERE amount > 100
 GROUP BY city
HAVING COUNT(*) > 50
 ORDER BY avg_amt DESC
 LIMIT 10;

-- joins
SELECT c.region, COUNT(*) AS orders, ROUND(SUM(s.amount), 2) AS gmv
  FROM sales s
  JOIN city c ON s.city = c.city
 GROUP BY c.region
 ORDER BY gmv DESC;

-- derived table + CASE labelling
SELECT tier, COUNT(*) AS n FROM (
  SELECT CASE WHEN amount >= 800 THEN 'high'
              WHEN amount >= 400 THEN 'mid'
              ELSE 'low' END AS tier
    FROM sales
) GROUP BY tier ORDER BY n DESC;

-- UNION
SELECT city FROM sales WHERE city = '北京'
UNION ALL
SELECT city FROM sales WHERE city = '深圳';
```

**`ORDER BY` accepts four kinds of key**: an output alias, a column name from the
`SELECT` list, a positional number (`ORDER BY 2`), and — for non-aggregated
queries — **an input column that never made it into the `SELECT` list**
(e.g. `SELECT name FROM people p JOIN city c ... ORDER BY p.age`).

#### 📜 Log querying in practice

A `.log` file defaults to one `line` column. Give it a regex with named groups and
each line becomes structured columns:

```bash
nanoquery "SELECT level, COUNT(*) AS c, ROUND(AVG(cost), 1) AS avg_ms, MAX(cost) AS max_ms
  FROM app GROUP BY level ORDER BY avg_ms DESC" \
  -t app=app.log \
  --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<svc>[\w-]+) .*took (?P<cost>\d+)ms'
```

#### 🧾 Drilling into nested JSON Lines

```json
{"id": 1, "user": {"name": "alice", "vip": true}, "event": "view", "value": 10}
```

Nested objects are flattened into `user.name` / `user.vip`, which you can use
directly in SQL:

```bash
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c, AVG(value) AS avg_value
  FROM events GROUP BY event, user.vip ORDER BY c DESC" events.jsonl
```

#### 🧠 Embedding API

```python
from nanoquery import Engine, Batch

engine = Engine()
engine.register_path("sales", "examples/sales.csv")
engine.register_data("small", [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])   # in-memory table
engine.register("inline", Batch({"id": [1, 2], "v": [10, 20]}))           # in-memory batch

print(engine.schema())            # columns and types for every table
print(engine.query("SELECT * FROM inline").rows())
```

More in [docs/PYTHON-API.md](./docs/PYTHON-API.md).

#### 🖲️ REPL meta-commands

| Command | Purpose |
| --- | --- |
| `\dt` | List registered tables |
| `\d NAME` | Show one table's schema |
| `\format FMT` | Switch output format |
| `\timing` | Toggle timing |
| `\help` | Show help |
| `\quit` | Exit (Ctrl-D works too) |

#### ⚠️ Not supported

Scalar subqueries, correlated subqueries, `WITH` CTEs, window functions, and any
DDL/DML. Unsupported syntax raises a **readable error with a position** — it never
crashes.

---

### 💡 Design Notes & Roadmap

#### 🏗️ Why it is built this way

**1. Batches, not rows.** Function calls and attribute lookups in CPython are
genuinely expensive; row-at-a-time execution in pure Python is unusably slow. So
the unit of work in NanoQuery is a `Batch` (`Dict[str, List[Any]]`, 4096 rows by
default), and expressions are evaluated a whole column at a time, amortizing
interpreter overhead.

**2. Volcano model with generators.** `Scan → Join → Filter → Aggregate/Project →
Distinct → Sort → Limit` is wired entirely with generators, so memory stays flat.
Only sorting materializes, because sorting has to.

**3. Hash aggregation streams.** Group state updates incrementally, so results
start flowing before the scan finishes — which also makes `LIMIT` cheap.

**4. Column pruning is pushed down.** Reading `.nq` touches only the columns the
query needs; other payloads are not even decompressed.

**5. Zero dependencies is a constraint, not a coincidence.** `scripts/build.sh`
contains an AST check that walks every `import` under `nanoquery/` and fails the
build if anything outside the standard-library allowlist appears.

Architecture details: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).
File format: [docs/FORMAT.md](./docs/FORMAT.md).

#### 🗺️ Roadmap

| Version | Theme | Content |
| --- | --- | --- |
| **v1.0.x** | Hardening | Bug fixes, better error messages, more edge-case tests |
| **v1.1** | Ergonomics | `WITH` CTEs, `EXISTS`, scalar subqueries, `VALUES` |
| **v1.2** | Analytics | Window functions (`ROW_NUMBER` / `RANK` / `LAG`), `PIVOT` sugar |
| **v1.3** | Performance | Predicate pushdown into `.nq` dictionaries, parallel scan, TOP-N sort |
| **v1.4** | Ecosystem | Read-only Parquet / Arrow IPC, `.nq` appends and partition directories |
| **v2.0** | Form factor | Optional Rust/C acceleration backend (still zero-dep by default) |

---

### 📦 Packaging & Deployment

NanoQuery is a **library / CLI tool**, so it does **not** need a binary GitHub
Release. Semantic version tags plus install and integration docs are what matter.

#### 📥 Installing

```bash
# Install from source (most portable)
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery
pip install .

# Editable install for development
pip install -e ".[dev]"

# No install at all
PYTHONPATH=. python3 -m nanoquery selftest
```

Installing provides the `nanoquery` console script, declared in
`pyproject.toml` under `[project.scripts]`.

#### 🏗️ Building locally

```bash
./scripts/build.sh          # syntax + dependency purity + selftest + unit tests
./scripts/build.sh dist     # also produce wheel and sdist under dist/
./scripts/build.sh clean    # remove build artifacts
```

Or use the standard toolchain directly:

```bash
python -m build
python -m twine check dist/*
```

#### 🔌 Integrating

**As a CLI subprocess:**

```python
import subprocess, json

out = subprocess.run(
    ["nanoquery", "SELECT city, COUNT(*) AS c FROM t GROUP BY city",
     "-t", "t=data.csv", "--format", "json"],
    capture_output=True, text=True, check=True,
)
rows = json.loads(out.stdout)
```

**As an embedded library:**

```python
from nanoquery import Engine

engine = Engine(batch_size=8192)          # larger batches for big files
engine.register_path("sales", "sales.csv")
rows = engine.query("SELECT city, SUM(amount) AS gmv FROM sales GROUP BY city").rows()
```

#### 🔖 Versioning and tags

```bash
git tag -a v1.0.0 -m "feat: NanoQuery first stable release"
git push origin v1.0.0
```

#### 🧪 CI

GitHub Actions covers Python 3.8–3.12 across Linux, macOS and Windows. Every push
runs: zero-dependency selftest → CLI smoke test → unit tests → distribution build.

---

### 🤝 Contributing

Issues and pull requests are welcome. Please read
[CONTRIBUTING.md](./CONTRIBUTING.md); the essentials:

1. 🪶 **Zero third-party dependencies** is a hard rule enforced by CI;
2. 🐍 Stay compatible with Python 3.8;
3. 🧪 Add tests with new features, and keep `./scripts/build.sh` green;
4. 📝 Commit messages follow the **Angular convention**:
   `feat(executor): support ORDER BY on non-projected input columns`
5. 📚 Update `docs/` when SQL semantics or the file format change.

---

### 📄 License

[MIT License](./LICENSE) © 2026 gitstq — free to use, modify, distribute and
use commercially, as long as the copyright notice is kept.

🌐 Switch language: [简体中文](#zh-cn) ｜ [繁體中文](#zh-tw) ｜ [English](#en)

<div align="center">

**如果 NanoQuery 帮你省下了一次装数据库的时间，给它一个 ⭐ 吧。**

**If NanoQuery saved you from setting up a database, consider leaving a ⭐.**

</div>
