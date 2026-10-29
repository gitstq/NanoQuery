# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [1.0.0] - 2026-10-30

首个正式版本。纯 Python 标准库实现的嵌入式列式分析引擎，
可直接对本地 CSV / JSONL / 日志文件执行 SQL。

### 新增

- **SQL 引擎**
  - 查询：投影、`WHERE`、`GROUP BY` / `HAVING`、`ORDER BY`（多键 + `NULLS FIRST|LAST`）、
    `DISTINCT`、`LIMIT` / `OFFSET`、`UNION` / `UNION ALL`
  - 连接：`INNER` / `LEFT` / `RIGHT` / `CROSS JOIN`，等值谓词走哈希连接
  - 子查询：`FROM` 子句中的派生表
  - 表达式：`CASE WHEN`、`CAST`、算术 / 比较 / 逻辑运算符、`||` 拼接、
    `BETWEEN`、`IN`、`LIKE`、`IS NULL`
  - 40+ 标量函数与 10 个聚合函数（含 `MEDIAN`、`STDDEV`、`GROUP_CONCAT`，
    部分支持 `DISTINCT`）
  - SQLite 风格类型亲和与 NULL 三值逻辑
- **数据源**
  - CSV / TSV：自动嗅探分隔符、自动类型推断、支持无表头
  - JSON Lines：自动展平嵌套对象（`user.name` 直接可查）
  - 文本日志：命名分组正则抽字段，附带 `lineno` / `line` 等辅助列
  - 内存数据：`Batch` 或行字典序列可直接注册为表（嵌入式用法）
- **`.nq` 列存格式**
  - 魔数 `NQ01` + JSON 头 + 每列独立 payload
  - 自动在 `RAW` / `DICT` / `RLE` 间择优，可选 zlib 压缩
  - 读取时按 SQL 做列裁剪下推
  - 实测：5000 × 6 的销售数据由 175 KB CSV 压至 39 KB（约 4.4×）
- **CLI**
  - `nanoquery "<SQL>" file.csv` 即席查询；子命令 `repl` / `schema` / `import` /
    `explain` / `selftest` / `functions`
  - 6 种输出格式：`table`（中文宽度对齐）、`json`、`jsonl`、`csv`、`tsv`、`md`
  - 交互式 REPL：多行输入、`\dt` `\d` `\format` `\timing` 等元命令
- **工程化**
  - `pyproject.toml`（`console_scripts` 入口）、MIT 许可、`.gitignore`
  - `scripts/build.sh` 一键校验：语法编译 → 依赖纯净性 AST 检查 → 自检 → 单元测试
  - GitHub Actions CI：Python 3.8–3.12 × Linux/macOS/Windows
  - 150 个单元测试 + 22 项内置端到端自检

### 修复

- `ABS()` 未对数值取绝对值，返回原值
- `ORDER BY` 引用带表别名的列（如 `ORDER BY p.name`）时无法解析
- 流式 JSON 输出的对象分隔符位置不美观（逗号前置）

### 说明

- 不支持标量子查询、相关子查询、CTE、窗口函数与 DDL/DML；
  遇到不支持的语法会抛出带位置信息的可读错误而非崩溃。
