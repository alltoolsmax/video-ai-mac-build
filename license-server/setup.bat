@echo off
chcp 65001 >nul
title Cai may chu ban quyen - Video AI Mr. Huynh
cd /d "%~dp0"
echo.
echo === Kiem tra Node.js ===
where node >nul 2>nul
if errorlevel 1 (
  echo Chua co Node.js - dang cai bang winget...
  winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
  set "PATH=%PATH%;%ProgramFiles%\nodejs"
)
where node >nul 2>nul
if errorlevel 1 (
  echo Khong cai duoc Node.js. Tai tai https://nodejs.org roi chay lai file nay.
  pause
  exit /b 1
)
echo === Cai cong cu Cloudflare (wrangler) ===
if not exist node_modules\wrangler call npm install wrangler@4 --no-fund --no-audit
echo === Tim Python ===
set "PY="
if exist "..\.venv-build\Scripts\python.exe" set "PY=..\.venv-build\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Chua co Python. Hay chay "build Windows.bat" mot lan truoc ^(no tu cai Python^).
  pause
  exit /b 1
)
%PY% -m pip install --quiet cryptography
%PY% setup.py
echo.
pause
