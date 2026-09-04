@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  if errorlevel 1 goto :error
)
if not exist .env copy /Y .env.example .env >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error
start "StrikeSnipe" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8787"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8787/
exit /b 0
:error
pause
