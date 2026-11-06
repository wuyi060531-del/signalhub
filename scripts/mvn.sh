#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
if [ -d "$ROOT/.tools/jdk/Contents/Home" ]; then export JAVA_HOME="$ROOT/.tools/jdk/Contents/Home"; fi
if [ -x "$ROOT/.tools/maven/bin/mvn" ]; then exec "$ROOT/.tools/maven/bin/mvn" "$@"; fi
exec mvn "$@"
