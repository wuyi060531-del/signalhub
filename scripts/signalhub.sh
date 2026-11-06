#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo '缺少本仓库 .venv/bin/python；请按 docs/00_START_HERE.md 准备现有环境，不会自动安装。' >&2
  exit 1
fi
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/local_runtime.py" "$@"
