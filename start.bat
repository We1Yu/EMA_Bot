@echo off
set PY=C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\python.exe
cd /d "%~dp0ema_scanner"
start "EMA Scanner Bot" cmd /k "%PY%" -u main.py
start "EMA Dashboard" cmd /k "%PY%" -u web_app.py
echo.
echo 啟動完成！
echo   掃描機器人：已在獨立視窗運行
echo   網頁儀表板：http://localhost:5000
echo.
pause
