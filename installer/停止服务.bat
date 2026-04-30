@echo off
chcp 65001 >nul
title 停止LOF基金数据服务

echo ============================================================
echo    停止 LOF基金数据服务
echo ============================================================
echo.

tasklist /FI "IMAGENAME eq LOF基金服务.exe" 2>NUL | find /I /N "LOF基金服务.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    echo [*] 正在停止服务...
    taskkill /F /IM "LOF基金服务.exe" >nul 2>&1
    timeout /t 2 /nobreak >nul
    echo [√] 服务已停止
) else (
    echo [!] 未检测到运行中的服务
)

echo.
echo ============================================================
pause
