@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "APP_DIR=%SCRIPT_DIR%..\Program"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "PYTHONUTF8=1"

if not exist "%APP_DIR%\app.py" (
  echo [AnyTrack Editor] Program\app.py not found. Keep all four folders together.
  pause
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo [AnyTrack Editor] Creating the Windows environment...
  py -3 -m venv "%VENV_DIR%" 2>nul || python -m venv "%VENV_DIR%"
  if errorlevel 1 goto :python_error
)

call "%VENV_DIR%\Scripts\activate.bat"
if not exist "%VENV_DIR%\.track_editor_deps_082" (
  echo [AnyTrack Editor] Installing dependencies. This is required only once...
  python -m pip install --upgrade pip
  python -m pip install -r "%APP_DIR%\requirements.txt"
  if errorlevel 1 goto :install_error
  type nul > "%VENV_DIR%\.track_editor_deps_082"
)

if /I "%~1"=="--prepare-only" exit /b 0
python "%APP_DIR%\app.py"
if errorlevel 1 pause
exit /b %errorlevel%

:python_error
echo Python 3.11-3.13 was not found. Install it and enable "Add Python to PATH".
pause
exit /b 1

:install_error
echo Could not install dependencies. Check the internet connection and try again.
pause
exit /b 1
