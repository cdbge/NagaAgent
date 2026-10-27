@echo off
REM NagaAgent launcher (ASCII only - cmd reads .bat as GBK,
REM Chinese comments would be garbled and executed as commands)
setlocal
cd /d D:\Desktop\NagaAgent
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -X faulthandler -u main.py > "data\run.log" 2>&1
