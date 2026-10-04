@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call start.bat
call ".venv\Scripts\activate.bat"
pip install pyinstaller
pyinstaller --noconfirm --clean --windowed --name "AnyTrack Editor" --icon "assets\app_icon.ico" --add-data "assets;assets" --collect-all fit_tool --collect-all gpxpy app.py
echo.
echo Build: dist\AnyTrack Editor\AnyTrack Editor.exe
pause
