@echo off
chcp 65001 >nul
title 工程项目投资采运销分红系统 - 一键启动
color 0A

echo ================================================
echo        工程项目投资采运销分红系统 - 一键启动
echo ================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python 环境！
    echo 请先安装 Python 3.8 或以上版本
    pause
    exit /b 1
)

echo [OK] Python 环境检测通过
python --version
echo.

echo [检查] 正在检查依赖包...
pip install flask schedule -q
echo.

if not exist "backups" mkdir backups
if not exist "uploads" mkdir uploads

echo ================================================
echo   工程项目投资采运销分红系统正在启动...
echo   默认账号: admin  默认密码: admin123
echo   访问: http://127.0.0.1:5002
echo ================================================
echo.

python app.py

pause
