@echo off
set PY=C:\Users\User\AppData\Local\Python\bin\python.exe

cd /d "%~dp0crypto_screener"
start "Crypto Scalp Bot" cmd /k "%PY%" -u main_scalp.py
start "Dashboard" cmd /k "%PY%" -u web_app.py

echo.
echo Started!
echo   Scalp Bot : running in separate window (BingX)
echo   Dashboard : http://localhost:5000
echo.
pause
