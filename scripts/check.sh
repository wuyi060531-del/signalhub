#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
export SIGNALHUB_EVIDENCE_DIR="${SIGNALHUB_EVIDENCE_DIR:-.local/check}"
PYTHON_BIN="${SIGNALHUB_TEST_PYTHON:-.venv/bin/python}"
mkdir -p "$SIGNALHUB_EVIDENCE_DIR"
./scripts/mvn.sh -f backend-java/pom.xml test > "$SIGNALHUB_EVIDENCE_DIR/java-tests.txt" 2>&1
"$PYTHON_BIN" -m pytest -q data-pipeline-python/tests --junitxml="$SIGNALHUB_EVIDENCE_DIR/python-junit.xml" | tee "$SIGNALHUB_EVIDENCE_DIR/python-tests.txt"
cp backend-java/target/surefire-reports/*.txt "$SIGNALHUB_EVIDENCE_DIR/"
"$PYTHON_BIN" scripts/evaluate.py
"$PYTHON_BIN" scripts/deployment_check.py
