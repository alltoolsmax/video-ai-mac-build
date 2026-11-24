# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec cho macOS:  python -m PyInstaller --noconfirm build/VideoAI-mac.spec
# Tạo dist/Video AI - Mr Huynh.app (chạy trên máy Mac có cùng loại chip với máy build: Apple M hoặc Intel).
import os
import re
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
PKG = os.path.join(ROOT, "videoai")
VER = re.search(r'APP_VERSION = "([^"]+)"', open(os.path.join(PKG, "core", "paths.py"), encoding="utf-8").read()).group(1)
APP = "Video AI - Mr Huynh"

datas = [
    (os.path.join(PKG, "assets"), "videoai/assets"),
    (os.path.join(PKG, "ui", "tokens.json"), "videoai/ui"),
    (os.path.join(PKG, "adapters", "selectors"), "videoai/adapters/selectors"),
    (os.path.join(PKG, "languages"), "videoai/languages"),
    (os.path.join(PKG, "update_config.json"), "videoai"),
    (os.path.join(PKG, "license_config.json"), "videoai"),
    (os.path.join(ROOT, "chrome-extension"), "chrome-extension"),
]
datas = [d for d in datas if os.path.exists(d[0])]
datas += collect_data_files("playwright") + collect_data_files("certifi")

hiddenimports = collect_submodules("videoai") + ["PySide6.QtSvg", "keyring.backends.macOS", "openpyxl.cell._writer", "certifi"]

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
    console=False,
    upx=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VideoAI-MrHuynh")
icns = os.path.join(ROOT, "build", "out", "icon.icns")
app = BUNDLE(
    coll,
    name=APP + ".app",
    icon=icns if os.path.exists(icns) else None,
    bundle_identifier="net.mrhuynh.videoai",
    version=VER,
    info_plist={
        "CFBundleName": APP,
        "CFBundleDisplayName": "Video AI - Mr. Huỳnh",
        "CFBundleShortVersionString": VER,
        "CFBundleVersion": VER,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "LSApplicationCategoryType": "public.app-category.video",
    },
)
