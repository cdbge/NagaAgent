@echo off
chcp 65001 > nul
rem 本脚本位于 <repo>\scripts\，先回到仓库根目录再启动
cd /d "%~dp0.."
if exist ".venv\" (
    .venv\Scripts\python.exe main.py %*
) else (
    echo 未检测到虚拟环境，请先运行 scripts\setup.bat 进行初始化，或手动配置。
    pause > nul
)
