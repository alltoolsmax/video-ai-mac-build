@echo off
chcp 65001 >nul
title Chuan bi goi hosting - Video AI Mr. Huynh
cd /d "%~dp0\.."
set "PY="
if exist ".venv-build\Scripts\python.exe" set "PY=.venv-build\Scripts\python.exe"
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
%PY% -m pip install --quiet cryptography
%PY% tools\prepare_hosting.py %*
echo.
pause
