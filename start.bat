@echo off
set PY=C:\Users\User\AppData\Local\Python\bin\python.exe

echo ================================================
echo   Trade Bot Launcher
echo ================================================
echo.

:: ── EMA Scanner (4H) ──────────────────────────────
cd /d "%~dp0ema_scanner"
start "EMA Scanner" cmd /k "%PY%" -u main.py
start "EMA Dashboard :5001" cmd /k "%PY%" -u web_app.py
echo [OK] EMA Scanner started (port 5001)

echo.
echo ================================================
echo   EMA Scanner  : http://localhost:5001
echo ================================================
echo.
pause
