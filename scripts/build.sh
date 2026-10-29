#!/usr/bin/env bash
#
# NanoQuery 一键构建 / 校验脚本
#
# 用法：
#   ./scripts/build.sh           # 语法检查 + 依赖确认 + 自检 + 单元测试
#   ./scripts/build.sh dist      # 额外产出 dist/ 下的 wheel / sdist
#   ./scripts/build.sh clean     # 清理构建产物
#
# 设计原则：零第三方依赖，脚本只用 Bash + Python 标准库完成全部校验。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
MODE="${1:-check}"

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✅\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m  ❌\033[0m %s\n' "$*" >&2; exit 1; }

case "$MODE" in
  clean)
    log "清理构建产物"
    rm -rf build dist ./*.egg-info .pytest_cache
    find . -type d -name __pycache__ -prune -exec rm -rf {} +
    ok "已清理"
    exit 0
    ;;
  check|dist) ;;
  *)
    echo "未知模式：$MODE（可选 check / dist / clean）" >&2
    exit 2
    ;;
esac

command -v "$PYTHON" >/dev/null 2>&1 || fail "未找到解释器：$PYTHON"
PYVER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "Python $PYVER（要求 >= 3.8）"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || fail "Python 版本过低，请升级到 3.8+"

log "语法编译检查"
"$PYTHON" -m compileall -q nanoquery >/dev/null || fail "源码存在语法错误"
ok "全部模块编译通过"

log "依赖自检（运行时应为零第三方依赖）"
BAD="$("$PYTHON" - <<'PY'
import ast, pathlib, sys
# 相对导入（from . import x / from .batch import y）指向包内模块，天然合规；
# __future__ 是语言特性开关，也不算外部依赖。
allow_prefixes = {"nanoquery", "__future__"}
stdlibish = {
    "argparse", "ast", "base64", "csv", "dataclasses", "datetime", "io", "json",
    "math", "os", "re", "struct", "sys", "time", "typing", "zlib", "collections",
    "functools", "itertools", "heapq", "unicodedata", "enum", "abc", "contextlib",
    "operator", "string", "textwrap", "types", "warnings", "statistics",
    "tempfile", "shutil", "subprocess", "unittest", "pathlib", "random",
}
bad = []
for path in sorted(pathlib.Path("nanoquery").rglob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:          # 相对导入：包内模块
                continue
            mods = [node.module or ""]
        else:
            continue
        for m in mods:
            root = m.split(".")[0]
            if not root or root in stdlibish or root in allow_prefixes:
                continue
            bad.append(f"{path}:{getattr(node, 'lineno', '?')} -> {m}")
print("\n".join(bad))
PY
)"
if [ -n "$BAD" ]; then
  echo "$BAD" >&2
  fail "检测到非标准库依赖，NanoQuery 必须保持零第三方依赖"
fi
ok "仅使用标准库"

log "内置自检（端到端核心链路）"
"$PYTHON" -m nanoquery selftest || fail "内置自检未通过"
ok "内置自检通过"

log "单元测试"
if "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  "$PYTHON" -m pytest tests -q || fail "单元测试未通过"
  ok "单元测试通过（pytest）"
else
  "$PYTHON" -m unittest discover -s tests -v 2>&1 | tail -n 3
  ok "单元测试通过（unittest 兜底，安装 pytest 体验更佳：pip install -e \".[dev]\"）"
fi

if [ "$MODE" = "dist" ]; then
  log "构建分发包"
  if "$PYTHON" -c 'import build' >/dev/null 2>&1; then
    "$PYTHON" -m build || fail "打包失败"
  else
    "$PYTHON" -m pip install --quiet build || fail "安装 build 失败"
    "$PYTHON" -m build || fail "打包失败"
  fi
  ok "产物见 dist/"
  ls -1 dist
fi

log "全部完成 🎉（版本 $("$PYTHON" -c 'import nanoquery; print(nanoquery.__version__)')）"
