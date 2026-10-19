@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  call "%PROJECT_DIR%setup.bat"
  if errorlevel 1 exit /b 1
)

"%PYTHON%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
  echo Python environment is unavailable. Run setup.bat to repair it.
  pause
  exit /b 1
)
"%PYTHON%" "%PROJECT_DIR%launcher.py" %*
set "LAUNCH_STATUS=%ERRORLEVEL%"
if not "%LAUNCH_STATUS%"=="0" pause
exit /b %LAUNCH_STATUS%
