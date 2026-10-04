#!/bin/bash
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../Program"
VENV_DIR="$SCRIPT_DIR/.venv"
export PYTHONUTF8=1

if [ ! -f "$APP_DIR/app.py" ]; then
  echo "[AnyTrack Editor] Program/app.py not found. Keep all four folders together."
  read -r -p "Press Enter to close..."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11-3.13 was not found. Install it from python.org."
  read -r -p "Press Enter to close..."
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "[AnyTrack Editor] Creating the macOS environment..."
  python3 -m venv "$VENV_DIR" || exit 1
fi

source "$VENV_DIR/bin/activate"
if [ ! -f "$VENV_DIR/.track_editor_deps_082" ]; then
  echo "[AnyTrack Editor] Installing dependencies. This is required only once..."
  python -m pip install --upgrade pip || exit 1
  python -m pip install -r "$APP_DIR/requirements.txt" || exit 1
  touch "$VENV_DIR/.track_editor_deps_082"
fi

python "$APP_DIR/app.py"
STATUS=$?
if [ $STATUS -ne 0 ]; then
  read -r -p "AnyTrack Editor stopped with an error. Press Enter to close..."
fi
exit $STATUS
