#!/bin/bash
cd "$(dirname "$0")"
./.venv/bin/python -m black app/
echo "✅ Formatted. Press any key to close."
read -n 1
