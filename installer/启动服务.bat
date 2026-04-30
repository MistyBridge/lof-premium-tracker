@echo off
chcp 65001 >nul
title LOF基金数据服务

echo ============================================================
echo    LOF基金数据服务 启动中...
echo ============================================================
echo.

cd /d "%~dp0"

:: 检查是否已有实例运行
tasklist /FI "IMAGENAME eq LOF基金服务.exe" 2>NUL | find /I /N "LOF基金服务.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    echo [!] 检测到服务已在运行
    echo.
    goto :open_browser
)

echo [*] 正在启动后端服务...
start "" "%~dp0LOF基金服务.exe"

:: 等待服务启动
echo [*] 等待服务就绪...
timeout /t 5 /nobreak >nul

:open_browser
echo [*] 正在打开前端页面...
start "" "http://localhost:5000"

echo.
echo ============================================================
echo    服务已启动！
echo    前端地址: http://localhost:5000
echo    API文档:  http://localhost:5000/api/funds
echo    健康检查: http://localhost:5000/health
echo ============================================================
echo.
echo 按任意键关闭此窗口（服务将继续在后台运行）
pause >nul
