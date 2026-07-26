@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
  echo Virtual environment not found: %PYTHON%
  echo Please create .venv and install requirements first.
  pause
  exit /b 1
)

"%PYTHON%" -m streamlit run "%PROJECT_DIR%app.py"
endlocal
