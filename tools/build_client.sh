#!/usr/bin/env bash
# Build the desktop worker into one executable: dist/nexus-worker (nexus-worker.exe on Windows).
# PyInstaller builds for the OS it runs on; CI builds Windows, macOS and Linux (see .github/workflows).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"; [ -x "$PY" ] || PY=python3
SEP=$("$PY" -c 'import os;print(os.pathsep)')
WIN="--windowed"; [ "$(uname)" = Darwin ] && WIN=""   # macOS: avoid the extra .app bundle
"$PY" -m PyInstaller --onefile $WIN --name nexus-worker --noconfirm \
  --collect-submodules websockets --collect-submodules webview --add-data "$PWD/web${SEP}web" --workpath build --specpath build client.py
ls -la dist/
