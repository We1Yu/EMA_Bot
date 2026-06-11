@echo off
set PY=C:\Users\joeau\AppData\Local\Programs\Python\Python314\python.exe
cd /d "%~dp0"

start "Crypto Scalp Bot" cmd /k "%PY%" -u main_scalp.py
start "Dashboard" cmd /k "%PY%" -u web_app.py

echo.
echo 啟動完成！
echo   高頻虛擬交易機器人：已在獨立視窗運行 (BingX)
echo   網頁儀表板（含兩個分頁）：http://localhost:5000
echo.
pause
