@echo off
setlocal
set "PROJECT_DIR=%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(sys.version_info < (3,10))"
  if errorlevel 1 goto :missing_python
  py -3 -m venv "%PROJECT_DIR%.venv"
) else (
  python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
  if errorlevel 1 goto :missing_python
  python -m venv "%PROJECT_DIR%.venv"
)
if errorlevel 1 goto :failed
"%PROJECT_DIR%.venv\Scripts\python.exe" -m pip install -r "%PROJECT_DIR%requirements.txt"
if errorlevel 1 goto :failed
echo Setup completed. Double-click start.bat to open the tool.
exit /b 0
:missing_python
echo Python 3.10 or later is required. Python 3.12 is recommended for this project.
echo Install Python from python.org, then run setup.bat again.
pause
exit /b 1
:failed
echo Setup failed. Check Python, network access and the messages above.
pause
exit /b 1
