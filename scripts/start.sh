#!/usr/bin/env bash
set -euo pipefail

# 本脚本位于 <repo>/scripts/，仓库根目录是它的上一级
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python"

if [ -x "$VENV_PY" ]; then
    # 将所有传入参数传给 main.py
    cd "$REPO_ROOT"
    exec "$VENV_PY" "$REPO_ROOT/main.py" "$@"
else
    echo "❌ 未检测到虚拟环境，请先运行 scripts/setup.sh 进行初始化，或手动配置。" >&2
    exit 2
fi
