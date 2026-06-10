@echo off
set PY=C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\python.exe

echo ========================================
echo  Crypto Screener v2 - BingX
echo ========================================
echo.
echo 選擇模式：
echo   1. swing    - 4H 掃一次
echo   2. intraday - 1H 每 15 分鐘持續掃
echo   3. swing + verbose  - 顯示詳細篩選原因
echo.
set /p MODE="輸入 1 / 2 / 3: "

if "%MODE%"=="1" (
    %PY% main.py --mode swing --exchange bingx --discord
) else if "%MODE%"=="2" (
    %PY% main.py --mode intraday --exchange bingx --discord
) else if "%MODE%"=="3" (
    %PY% main.py --mode swing --exchange bingx --verbose
) else (
    echo 無效選項
)

pause
