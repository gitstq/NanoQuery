# 贡献指南

感谢你愿意让 NanoQuery 变得更好。这份文档说明了开发流程、代码规范与提交约定。

## 1. 开发准备

```bash
git clone https://github.com/gitstq/NanoQuery.git
cd NanoQuery

# 运行时零依赖，直接就能跑
python3 -m nanoquery selftest

# 需要跑测试 / 打包时再装可选依赖
pip install -e ".[dev]"
```

一条命令完成全部校验（语法检查 → 依赖纯净性 → 自检 → 单元测试）：

```bash
./scripts/build.sh
# 需要产出 wheel / sdist 时
./scripts/build.sh dist
```

## 2. 硬性约束（会由 CI 卡住）

1. **零第三方依赖**：`nanoquery/` 包内只允许 import Python 标准库。
   `scripts/build.sh` 里的 AST 检查会扫描全部 import 语句，发现白名单外模块即失败。
2. **Python ≥ 3.8**：不要使用 3.9+ 才有的语法或标准库 API
   （例如 `dict |`、`list[str]` 注解请走 `from __future__ import annotations`）。
3. **测试必须全绿**：新增功能请同步补充 `tests/` 下的用例。
4. **不破坏流式特性**：除排序等固有需要物化的算子外，
   新增算子应尽量以生成器实现，避免整表物化。

## 3. 代码风格

- 缩进 4 空格，行宽尽量不超过 100 字符；
- 公共函数与类写中文 docstring（含 Args / Returns），关键算法写行内注释说明「为什么」；
- 模块顶部用 `"""..."""` 说明该模块的职责；
- 用户可见的错误信息以中文为主，并带上**位置/候选**信息，便于排查：
  ```python
  raise ResolveError(f"未知的列：{name}（已注册：{', '.join(sorted(self.names))}）")
  ```
- 提交前跑一遍 `./scripts/build.sh`。

## 4. 提交信息约定（Angular 规范）

```
<type>(<scope>): <subject>
```

`type` 取值：

| type | 场景 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档变更 |
| `style` | 格式调整（不影响逻辑） |
| `refactor` | 重构（既不新增功能也不修缺陷） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建 / 依赖相关 |
| `ci` | CI 配置 |
| `chore` | 其他杂项 |

`scope` 为模块名，如 `executor`、`parser`、`storage`、`cli`、`exporter`。

示例：

```
feat(executor): 支持 ORDER BY 引用未投影的输入列
fix(functions): 修正 ABS() 未取绝对值的问题
docs(readme): 补充繁体中文与 English 版本
perf(storage): 字典编码阈值由 0.35 调整为 0.40
```

## 5. Pull Request 流程

1. Fork 仓库并新建分支：`git checkout -b feat/your-feature`；
2. 开发与自测（务必 `./scripts/build.sh` 全绿）；
3. 按 Angular 规范提交；
4. 发起 PR，描述里请写清：**动机 / 改动点 / 如何验证**；
5. 若涉及 SQL 语义或文件格式变更，请同步更新
   `docs/SQL-REFERENCE.md` 或 `docs/FORMAT.md`，并考虑是否需要提升 `FORMAT.md` 的版本号。

## 6. 报告问题

提 Issue 时请附上：

- NanoQuery 版本（`python3 -m nanoquery --version`）与 Python 版本；
- 能复现的最小 SQL 与数据片段（可脱敏）；
- 期望结果与实际结果。

## 7. 行为准则

保持友善、就事论事。技术讨论欢迎分歧，人身攻击不被接受。
