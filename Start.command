#!/bin/sh
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Prefer Python 3.10 (required for our LTS combo)
if command -v python3.10 >/dev/null 2>&1; then PY=python3.10; else PY=python3; fi

# venv on 3.10
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi
. ".venv/bin/activate"
python -m pip -q install -U pip || true
[ -f requirements.txt ] && pip -q install -r requirements.txt || true

# run as a module so relative imports work
exec python -m app.main
