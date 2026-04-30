@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ════════════════════════════════════════════════════════════
echo          LOF基金服务 - Windows安装包构建脚本
echo ════════════════════════════════════════════════════════════
echo.

cd /d "%~dp0.."

:: 检查 Python
echo [1/5] 检查环境...
py --version >nul 2>&1
if errorlevel 1 (
    echo [X] 错误: 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

:: 安装 PyInstaller（如果未安装）
echo [2/5] 检查 PyInstaller...
py -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [*] 正在安装 PyInstaller...
    py -m pip install pyinstaller -q
)

:: 安装项目依赖
echo [3/5] 安装项目依赖...
py -m pip install -r requirements.txt -q

:: PyInstaller 打包
echo [4/5] PyInstaller 打包后端服务...
py -m PyInstaller installer/lof_service.spec --noconfirm --clean

if errorlevel 1 (
    echo [X] 打包失败！
    pause
    exit /b 1
)

echo [√] 后端打包完成

:: 检查 Inno Setup
echo [5/5] 检查 Inno Setup...
set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if defined ISCC (
    echo [*] 正在创建安装包...
    "%ISCC%" installer/setup.iss
    if errorlevel 1 (
        echo [!] Inno Setup 编译失败，但exe文件已生成
        echo [!] 请手动安装 Inno Setup 6 并运行: installer\setup.iss
    ) else (
        echo [√] 安装包已生成: installer\output\LOF基金服务_Setup_v1.0.0.exe
    )
) else (
    echo [!] 未找到 Inno Setup 6，跳过安装包生成
    echo [*] 后端exe已生成: dist\LOF基金服务.exe
    echo.
    echo [*] 请手动安装 Inno Setup 6:
    echo     下载地址: https://jrsoftware.org/isdownload.php
    echo     安装后双击运行: installer\setup.iss
)

echo.
echo ════════════════════════════════════════════════════════════
echo                    构建完成！
echo ════════════════════════════════════════════════════════════
pause
