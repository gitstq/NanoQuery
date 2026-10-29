# `.nq` 列存格式规范（v1）

> 用标准库 `struct` / `json` / `zlib` 就能读写，任何语言都可以实现一份解析器。

## 1. 文件整体布局

全部整数为**小端序（little-endian）**：

```
+---------------------------+
| magic  "NQ01"      4B     |
| version            1B     |  当前为 1
| flags              1B     |  bit0 = 载荷启用 zlib 压缩
| reserved           2B     |  置 0
| header_len         4B     |
| header JSON   header_len  |  UTF-8
+---------------------------+
| column chunk 0            |
| column chunk 1            |
| ...                       |
+---------------------------+
```

## 2. 文件头（JSON）

```json
{
  "format": "nanoquery-columnar",
  "version": 1,
  "row_count": 5000,
  "columns": [
    {"name": "order_id", "type": "INT",   "encoding": "RAW"},
    {"name": "city",     "type": "STR",   "encoding": "DICT"},
    {"name": "amount",   "type": "FLOAT", "encoding": "RAW"}
  ],
  "created_at": "2026-10-30T00:45:30",
  "source": "sales.csv"
}
```

`type` 取值：`NULL` / `BOOL` / `INT` / `FLOAT` / `STR`。
`encoding` 取值：`RAW` / `DICT` / `RLE`。

## 3. 列块（column chunk）

```
+---------------------------+
| name_len          2B      |
| name        name_len      |  UTF-8
| type_code         1B      |  0 NULL / 1 BOOL / 2 INT / 3 FLOAT / 4 STR
| encoding          1B      |  0 RAW / 1 DICT / 2 RLE
| payload_len       4B      |  值为压缩后的长度（若启用压缩）
| payload     payload_len   |
+---------------------------+
```

`payload` 在解压后（若 `flags & 0x01`）的结构为：

```
+---------------------------+
| null bitmap   ceil(N/8) B |  位图，bit=1 表示该行为 NULL
| value region  变长         |  编码方式见下
+---------------------------+
```

位图按行序低位在前：第 `i` 行的标志位于第 `i / 8` 字节的第 `i % 8` 位。

## 4. 三种值区编码

### RAW（encoding = 0）

按类型定长/变长顺序存放：

| 类型 | 编码 |
| --- | --- |
| BOOL | 每值 1 字节，`0` / `1` |
| INT | 每值 8 字节，有符号小端 `<q` |
| FLOAT | 每值 8 字节 IEEE-754 小端 `<d` |
| STR | 每值：4 字节长度 + UTF-8 字节 |

### DICT（encoding = 1）

```
| dict_count  4B                              |
| 重复 dict_count 次：len 4B + UTF-8 字节     |
| 每行 2B 的字典下标（小端 <H）               |
```

适合低基数列（城市、级别、状态等）。

### RLE（encoding = 2）

```
| run_count  4B                                        |
| 重复 run_count 次：value + run_length 4B             |
```

`value` 的写法与 RAW 相同。适合排序过、存在长游程的列。

## 5. 编码自动选择策略

`choose_encoding()` 按以下顺序判定：

1. **RLE**：平均游程长度 ≥ 4 → 选 RLE；
2. **DICT**：唯一值比例 ≤ 0.4 且唯一值个数 ≤ 65535 → 选 DICT；
3. 否则 **RAW**。

## 6. 实测效果

| 数据集 | CSV | .nq（含 zlib） | 压缩比 |
| --- | --- | --- | --- |
| 销售明细 5000 × 6 | 175,641 B | 39,938 B | 4.40× |

除了体积，更关键的是**列裁剪**：`SELECT city, COUNT(*) FROM sales` 只会反序列化
`city` 一列，其余列的 payload 根本不会被读取。

## 7. 生成与读取

```bash
# 生成
nanoquery import data.csv -o data.nq -v

# 读取（自动识别扩展名）
nanoquery "SELECT city, COUNT(*) c FROM data GROUP BY city" -t data=data.nq

# 只看元数据，不加载数据
python -c "from nanoquery.storage import read_header; print(read_header('data.nq'))"
```
