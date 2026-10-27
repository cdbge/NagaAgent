@echo off
chcp 65001 > nul
rem 本脚本位于 <repo>\scripts\，setup.py 就在同一目录
cd /d "%~dp0"
python setup.py
pause > nul
