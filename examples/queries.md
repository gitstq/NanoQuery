# 可以直接复制粘贴运行的示例查询

配套数据在 `examples/` 目录下，先把当前目录切到仓库根目录。

## 1. CSV：城市维度 GMV 排行

```bash
nanoquery "SELECT city,
       COUNT(*)                AS orders,
       ROUND(SUM(amount), 2)   AS gmv,
       ROUND(AVG(amount), 2)   AS avg_ticket
  FROM sales
 GROUP BY city
 ORDER BY gmv DESC" examples/sales.csv
```

## 2. 渠道 × 城市交叉分析 + HAVING 过滤

```bash
nanoquery "SELECT channel, city, COUNT(*) AS c, ROUND(SUM(amount), 2) AS gmv
  FROM sales
 GROUP BY channel, city
HAVING SUM(amount) > 20000
 ORDER BY gmv DESC
 LIMIT 10" examples/sales.csv
```

## 3. JOIN：把订单表和城市维表关联

```bash
nanoquery "SELECT c.region, COUNT(*) AS orders, ROUND(SUM(s.amount), 2) AS gmv
  FROM sales s
  JOIN city c ON s.city = c.city
 GROUP BY c.region
 ORDER BY gmv DESC" -t sales=examples/sales.csv -t city=examples/city.csv
```

## 4. 日志：按正则抽字段后统计错误级别

```bash
nanoquery "SELECT level, COUNT(*) AS c
  FROM app
 GROUP BY level
 ORDER BY c DESC" \
  -t app=examples/app.log \
  --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<svc>[\w-]+) took (?P<cost>\d+)ms'
```

用引擎自带的 `took (\d+)ms` 提取耗时后，还能直接算 P99 之外的均值与最大值：

```bash
nanoquery "SELECT level, COUNT(*) AS c, ROUND(AVG(cost), 1) AS avg_ms, MAX(cost) AS max_ms
  FROM app
 GROUP BY level
 ORDER BY avg_ms DESC" \
  -t app=examples/app.log \
  --log-pattern '^(?P<ts>\S+ \S+) (?P<level>\w+) (?P<svc>[\w-]+) took (?P<cost>\d+)ms'
```

> 注意：示例日志里耗时写作 `request took 435ms`，正则末尾写 `took (?P<cost>\d+)ms` 即可命中。

## 5. JSONL：嵌套字段直接下钻

```bash
nanoquery "SELECT event, user.vip AS vip, COUNT(*) AS c, AVG(value) AS avg_value
  FROM events
 GROUP BY event, user.vip
 ORDER BY c DESC" examples/events.jsonl
```

## 6. 派生表 + CASE WHEN 打标

```bash
nanoquery "SELECT tier, COUNT(*) AS n FROM (
  SELECT CASE WHEN amount >= 800 THEN 'high'
              WHEN amount >= 400 THEN 'mid'
              ELSE 'low' END AS tier
    FROM sales
) GROUP BY tier ORDER BY n DESC" examples/sales.csv
```

## 7. 转成列存，再查一次（体会加速与列裁剪）

```bash
nanoquery import examples/sales.csv -o /tmp/sales.nq -v
nanoquery "SELECT product, SUM(qty) AS q FROM sales GROUP BY product ORDER BY q DESC LIMIT 5" \
  -t sales=/tmp/sales.nq -v
```

## 8. 输出成 Markdown 直接粘进周报

```bash
nanoquery "SELECT city, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS gmv
  FROM sales GROUP BY city ORDER BY gmv DESC" examples/sales.csv --format md
```

## 9. 管道给 jq

```bash
nanoquery "SELECT city, COUNT(*) AS c FROM sales GROUP BY city" \
  examples/sales.csv --format json | jq -r '.[] | "\(.city)\t\(.c)"'
```

## 10. 交互式探索

```bash
nanoquery repl examples/sales.csv examples/city.csv
```
