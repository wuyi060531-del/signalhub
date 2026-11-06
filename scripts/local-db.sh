#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
BIN="${PG_BIN:-$ROOT/.tools/postgres/bin}"
if [ ! -x "$BIN/pg_ctl" ]; then
  if command -v pg_ctl >/dev/null 2>&1; then BIN=$(dirname "$(command -v pg_ctl)");
  else echo '需要 PostgreSQL17：将其 bin 目录设置为 PG_BIN，或加入 PATH'; exit 1; fi
fi
mkdir -p .local
case "${1:-status}" in
 start)
  if [ ! -f .local/pgdata/PG_VERSION ]; then
    echo '此入口只兼容已有旧库。新库请使用 signalhub.sh start；合成演示请使用 public_demo.py。' >&2
    exit 1
  fi
  if ! "$BIN/pg_ctl" -D .local/pgdata status >/dev/null 2>&1; then
    "$BIN/pg_ctl" -D .local/pgdata -l "$ROOT/.local/postgres.log" -o '-h 127.0.0.1 -p 55432 -c unix_socket_directories= -c shared_buffers=64MB -c max_connections=20' start
  fi
  .venv/bin/python - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from local_runtime import Runtime
runtime = Runtime()
with runtime.connect('postgres') as c:
 if Path(c.execute('SHOW data_directory').fetchone()[0]).resolve()!=runtime.data.resolve():
  raise SystemExit('数据库目录不符，拒绝初始化其他实例')
 for name in ['signalhub','signalhub_test']:
  if not c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone(): c.execute('CREATE DATABASE '+name)
PY
 ;;
 stop) "$BIN/pg_ctl" -D .local/pgdata stop -m fast ;;
 status) "$BIN/pg_ctl" -D .local/pgdata status ;;
 *) echo '用法: local-db.sh start|stop|status'; exit 1 ;;
esac
