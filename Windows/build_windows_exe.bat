@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "APP_DIR=%SCRIPT_DIR%..\Program"
call "%SCRIPT_DIR%start_windows.bat" --prepare-only
if not exist "%SCRIPT_DIR%.venv\Scripts\python.exe" exit /b 1
call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name "AnyTrack Editor" --icon "%APP_DIR%\assets\app_icon.ico" --add-data "%APP_DIR%\assets;assets" --collect-all fit_tool --collect-all gpxpy --distpath "%SCRIPT_DIR%dist" --workpath "%SCRIPT_DIR%build" --specpath "%SCRIPT_DIR%build" "%APP_DIR%\app.py"
echo.
echo Build: %SCRIPT_DIR%dist\AnyTrack Editor\AnyTrack Editor.exe
pause
