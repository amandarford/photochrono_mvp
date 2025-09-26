#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

source .venv/bin/activate

# Discover PySide6 paths
PY6_DIR=$(.venv/bin/python - <<'PY'
import PySide6, pathlib
print(pathlib.Path(PySide6.__file__).parent)
PY
)

# De-quarantine (harmless if already clean)
xattr -dr com.apple.quarantine "$PY6_DIR" 2>/dev/null || true

export QT_PLUGIN_PATH="$PY6_DIR/Qt/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$PY6_DIR/Qt/plugins/platforms"
export DYLD_FRAMEWORK_PATH="$PY6_DIR/Qt/lib"
export DYLD_LIBRARY_PATH="$PY6_DIR/Qt/lib:${DYLD_LIBRARY_PATH:-}"
export QT_MAC_WANTS_LAYER=1

python -m app.main
