#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/../Program"
VENV_DIR="$SCRIPT_DIR/.venv"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
python -m pip install -r "$APP_DIR/requirements.txt" pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name "AnyTrack Editor" --icon "$APP_DIR/assets/app_icon.png" --add-data "$APP_DIR/assets:assets" --collect-all fit_tool --collect-all gpxpy --distpath "$SCRIPT_DIR/dist" --workpath "$SCRIPT_DIR/build" --specpath "$SCRIPT_DIR/build" "$APP_DIR/app.py"
echo "Build: $SCRIPT_DIR/dist/AnyTrack Editor/"
