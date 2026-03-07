@echo off
setlocal

cd /d "%~dp0"
set "PY=C:\Windows\py.exe"
if not exist "%PY%" set "PY=py"

echo [SMOKE] Python:
"%PY%" --version
if errorlevel 1 goto :fail

echo [SMOKE] Baseline run:
"%PY%" main.py
if errorlevel 1 goto :fail

echo [SMOKE] Mock once run:
"%PY%" main.py --once --backend mock --simulate-text "smoke-min"
if errorlevel 1 goto :fail

echo [SMOKE] OK
exit /b 0

:fail
echo [SMOKE] FAILED with exit code %errorlevel%
exit /b %errorlevel%
