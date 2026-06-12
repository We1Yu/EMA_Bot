@echo off
set PY=C:\Users\User\AppData\Local\Python\bin\python.exe

echo ================================================
echo   Trade Bot Launcher
echo ================================================
echo.

:: ── EMA Scanner (4H, 先啟動) ─────────────────────
cd /d "%~dp0ema_scanner"
start "EMA Scanner" cmd /k "%PY%" -u main.py
start "EMA Dashboard :5001" cmd /k "%PY%" -u web_app.py
echo [1/2] EMA Scanner started (port 5001)

:: ── 等 60 秒，避免 BingX rate limit ──────────────
echo Waiting 60 seconds before starting Scalp Bot...
timeout /t 60 /nobreak >nul

:: ── Scalp Bot (5m) ───────────────────────────────
cd /d "%~dp0crypto_screener"
start "Scalp Bot" cmd /k "%PY%" -u main_scalp.py
start "Scalp Dashboard :5000" cmd /k "%PY%" -u web_app.py
echo [2/2] Scalp Bot started (port 5000)

echo.
echo ================================================
echo   All bots running!
echo   EMA Scanner  : http://localhost:5001
echo   Scalp Bot    : http://localhost:5000
echo ================================================
echo.
pause
