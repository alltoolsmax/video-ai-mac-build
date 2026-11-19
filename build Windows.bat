@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Build Video AI - Mr. Huynh
cd /d "%~dp0"

echo ============================================================
echo   BUILD VIDEO AI - MR. HUYNH  (tao file .exe cho Windows)
echo ============================================================
echo.

rem ---------- 1. Tim Python 3.10 - 3.13 ----------
set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [1/6] Chua co Python phu hop. Dang cai Python 3.12 bang winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PY="%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not defined PY (
    echo.
    echo [LOI] Khong tim thay Python 3.10 - 3.13.
    echo       Hay cai Python 3.12 tu https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
    echo       roi bam lai file nay.
    pause
    exit /b 1
)
echo [1/6] Dung Python: %PY%
%PY% --version

rem ---------- 2. Moi truong ao ----------
if not exist ".venv-build\Scripts\python.exe" (
    echo [2/6] Tao moi truong ao .venv-build ...
    %PY% -m venv .venv-build || goto :fail
) else (
    echo [2/6] Da co moi truong ao .venv-build
)
set "VPY=%~dp0.venv-build\Scripts\python.exe"

rem ---------- 3. Thu vien ----------
echo [3/6] Cai thu vien (lan dau mat vai phut) ...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q || goto :fail
"%VPY%" -m pip install -r requirements.txt pyinstaller --disable-pip-version-check -q || goto :fail

rem ---------- 4. Dong goi exe ----------
echo [4/6] Dong goi bang PyInstaller ...
if exist "dist\VideoAI-MrHuynh" rmdir /s /q "dist\VideoAI-MrHuynh"
"%VPY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build\out "build\VideoAI.spec" || goto :fail
if not exist "dist\VideoAI-MrHuynh\VideoAI-MrHuynh.exe" goto :fail

rem ---------- 5. Cong cu di kem ----------
echo [5/6] Tai ffmpeg, Real-ESRGAN va trinh duyet Chromium du phong ...
powershell -NoProfile -ExecutionPolicy Bypass -File "build\fetch_tools.ps1" -Dest "dist\VideoAI-MrHuynh\bin"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0dist\VideoAI-MrHuynh\ms-playwright"
"%VPY%" -m playwright install chromium
if errorlevel 1 echo    (Bo qua: ung dung se dung Chrome hoac Edge co san tren may.)
set "PLAYWRIGHT_BROWSERS_PATH="

rem ---------- 6. Bo cai dat (neu co Inno Setup) ----------
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    echo [6/6] Tao bo cai dat bang Inno Setup ...
    if not exist "build\out" mkdir "build\out"
    "%VPY%" -c "from videoai.core.paths import APP_VERSION;print(APP_VERSION)" > "build\out\ver.txt"
    set /p APPVER=<"build\out\ver.txt"
    "%ISCC%" /Q /DAppVersion=!APPVER! "build\installer.iss"
) else (
    echo [6/6] Khong co Inno Setup - bo qua buoc tao bo cai. ^(Tuy chon: winget install JRSoftware.InnoSetup^)
)

echo.
echo ============================================================
echo   XONG!
echo   File chay:  %~dp0dist\VideoAI-MrHuynh\VideoAI-MrHuynh.exe
echo   Mang sang may khac: copy CA THU MUC dist\VideoAI-MrHuynh
if defined ISCC echo   Bo cai:     %~dp0dist\VideoAI-MrHuynh-Setup-!APPVER!.exe
if defined ISCC echo   Phat hanh ban cap nhat: python build\make_release.py https://.../download/v{version}/
echo ============================================================
start "" explorer "%~dp0dist\VideoAI-MrHuynh"
pause
exit /b 0

:fail
echo.
echo [LOI] Build that bai. Xem thong bao phia tren.
echo       Gui anh chup man hinh nay de duoc ho tro.
pause
exit /b 1
