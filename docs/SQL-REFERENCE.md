# NanoQuery SQL 参考

NanoQuery 实现的是 **SQL 的一个实用子集**：覆盖日常分析所需的查询、过滤、分组、
排序、连接与子查询，但不涉及 DDL / DML / 事务 / 索引（它是只读的查询引擎）。

## 1. 语句形态

```sql
SELECT [DISTINCT] <选择项> [, ...]
  FROM <表引用>
  [ (INNER|LEFT|RIGHT|CROSS) JOIN <表引用> [ON <条件>] [, ...] ]
  [WHERE <条件>]
  [GROUP BY <表达式> [, ...]]
  [HAVING <条件>]
  [ORDER BY <键> [ASC|DESC] [NULLS FIRST|NULLS LAST] [, ...]]
  [LIMIT <n>] [OFFSET <n>]
  [UNION [ALL] SELECT ...]
```

`<表引用>` 可以是：

| 形态 | 示例 | 说明 |
| --- | --- | --- |
| 已注册表名 | `FROM sales` | 由 `-t name=path` 或引擎 `register_path()` 注册 |
| 文件函数 | `FROM read_csv('data.csv')` | 直接在 SQL 里挂载文件 |
| 派生表 | `FROM (SELECT ...)` | 子查询，必须能在 FROM 中独立求值 |

## 2. 数据类型

内部只有 5 种类型，展示时由 `TYPEOF()` 返回其名称：

| 类型 | 说明 | 字面量示例 |
| --- | --- | --- |
| `NULL` | 空值 | `NULL` |
| `BOOL` | 布尔 | `true` / `false` |
| `INT` | 整数 | `42` |
| `FLOAT` | 浮点 | `3.14`、`1e3` |
| `STR` | 字符串 | `'北京'` |

**类型亲和（SQLite 风格）**：比较 INT/FLOAT 与 STR 时，会先尝试把字符串解析成数字，
因此 `'10' > 9` 成立。字符串字面量中用两个单引号表示一个单引号：`'a''b'`。

## 3. 运算符

| 类别 | 运算符 |
| --- | --- |
| 算术 | `+` `-` `*` `/` `%` |
| 比较 | `=` `!=` `<>` `<` `<=` `>` `>=` |
| 逻辑 | `AND` `OR` `NOT` |
| 字符串 | `\|\|`（拼接） |
| 判空 | `IS NULL` / `IS NOT NULL` |
| 范围 | `BETWEEN a AND b` / `NOT BETWEEN` |
| 集合 | `IN (...)` / `NOT IN (...)` |
| 模糊 | `LIKE` / `NOT LIKE`（`%` 任意长度，`_` 单字符） |

### NULL 的三值逻辑

与 SQL 标准一致：`NULL` 参与的比较结果为 **未知**，而 `WHERE` 只保留结果为真的行。

```sql
SELECT * FROM t WHERE v > 10;   -- v 为 NULL 的行不会出现
SELECT * FROM t WHERE v IS NULL;-- 显式判空才能捞到
```

聚合函数（`COUNT(列)`、`SUM`、`AVG`…）**忽略 NULL**；`COUNT(*)` 统计全部行。

## 4. 表达式

### CASE

```sql
SELECT CASE WHEN score >= 90 THEN 'A'
            WHEN score >= 80 THEN 'B'
            ELSE 'C' END AS grade
  FROM t;
```

### CAST

```sql
SELECT CAST(amount AS INT) AS i,
       CAST(amount AS STR) AS s,
       CAST('123' AS FLOAT) AS f
  FROM t;
```

### 列引用

- 裸列名：`amount`
- 限定名：`sales.amount`、别名 `s.amount`
- 嵌套字段（JSONL 展平）：`user.name` 或 `events.user.name`
- 引号标识符：`"user.name"`（当字段名本身含特殊字符时使用）

## 5. 内置函数

完整清单可运行 `nanoquery functions` 查看。常用如下：

**字符串**：`UPPER` `LOWER` `LENGTH` `TRIM` `LTRIM` `RTRIM` `SUBSTR` `SUBSTRING`
`REPLACE` `CONCAT` `CONCAT_WS` `LEFT` `RIGHT` `REVERSE` `INSTR`

**数值**：`ABS` `ROUND` `CEIL` `CEILING` `FLOOR` `SQRT` `POWER` `POW` `EXP` `LN` `LOG` `LOG10` `MOD`

**空值 / 选择**：`COALESCE` `IFNULL` `NULLIF` `GREATEST` `LEAST` `TYPEOF`

**聚合**：`COUNT` `SUM` `AVG` `MIN` `MAX` `MEDIAN` `VARIANCE` `VARIANCE_POP`
`STDDEV` `GROUP_CONCAT`，其中 `COUNT` `SUM` `AVG` `MIN` `MAX` `GROUP_CONCAT`
支持 `DISTINCT`：

```sql
SELECT COUNT(DISTINCT city) AS city_cnt FROM sales;
```

## 6. 排序键的解析规则

`ORDER BY` 允许四类写法，按以下顺序解析：

1. **输出别名**：`SELECT SUM(v) AS s ... ORDER BY s`
2. **输出列名**：`SELECT city ... ORDER BY city`
3. **位置序号**：`ORDER BY 2`（表示第二列）
4. **输入列**：即使没出现在 SELECT 列表里也能排，例如
   `SELECT name FROM people p JOIN city c ON ... ORDER BY p.age`

聚合查询只支持前三种；非聚合查询四种都支持。

## 7. 暂不支持的能力

| 能力 | 现状 |
| --- | --- |
| 标量子查询 `SELECT (SELECT ...)` | ❌ 不支持，会给出明确报错 |
| 相关子查询 / `WITH` CTE | ❌ 不支持 |
| 窗口函数 `OVER (...)` | ❌ 不支持（可用派生表 + JOIN 等价改写） |
| `UPDATE` / `DELETE` / `CREATE TABLE` | ❌ 引擎只读 |
| 标量子查询之外的 `EXISTS` | ❌ 不支持 |

遇到不支持的语法，引擎会抛出带**位置信息**的可读错误，而不是崩溃。
