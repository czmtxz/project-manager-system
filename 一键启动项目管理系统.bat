@echo off
chcp 65001 >nul
title 项目管理系统 - 一键启动
color 0A

echo ================================================
echo        项目管理系统 - 一键启动脚本
echo ================================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    echo 请先安装 Python 3.8 或以上版本
    echo 下载地址: https://www.python.org/downloads/
    echo.
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [OK] Python 环境检测通过
python --version
echo.

:: 检查并安装依赖
echo [检查] 正在检查依赖包...
pip install flask schedule -q
if %errorlevel% equ 0 (
    echo [OK] 依赖包安装完成
) else (
    echo [警告] 依赖安装可能存在问题，尝试继续运行...
)
echo.

:: 创建必要目录
if not exist "backups" mkdir backups
if not exist "uploads" mkdir uploads

:: 启动系统
echo ================================================
echo   项目管理系统正在启动...
echo   默认账号: admin
echo   默认密码: admin123
echo   默认端口: 5002
echo ================================================
echo.
echo 启动成功后，请在浏览器中访问:
echo   http://127.0.0.1:5002
echo.
echo 按 Ctrl+C 停止服务器
echo.

python app.py

pause
