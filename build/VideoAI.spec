# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec cho Video AI - Mr. Huỳnh.  Chạy:  pyinstaller --noconfirm build/VideoAI.spec
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
PKG = os.path.join(ROOT, "videoai")

datas = [
    (os.path.join(PKG, "assets"), "videoai/assets"),
    (os.path.join(PKG, "ui", "tokens.json"), "videoai/ui"),
    (os.path.join(PKG, "adapters", "selectors"), "videoai/adapters/selectors"),
    (os.path.join(PKG, "languages"), "videoai/languages"),
]
datas += collect_data_files("playwright")

hiddenimports = collect_submodules("videoai") + [
    "PySide6.QtSvg", "keyring.backends.Windows", "openpyxl.cell._writer",
]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VideoAI-MrHuynh",
    icon=os.path.join(PKG, "assets", "icon.ico"),
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VideoAI-MrHuynh")
