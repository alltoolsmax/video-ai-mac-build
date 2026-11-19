@echo off
chcp 65001 >nul
title Bat thanh toan tu dong (VietQR + SePay) - Video AI Mr. Huynh
cd /d "%~dp0"
set "PY="
if exist "..\.venv-build\Scripts\python.exe" set "PY=..\.venv-build\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Chua co Python. Hay chay "build Windows.bat" mot lan truoc.
  pause
  exit /b 1
)
if not exist node_modules\wrangler call npm install wrangler@4 --no-fund --no-audit
%PY% -m pip install --quiet cryptography
%PY% setup.py --payment
echo.
pause
