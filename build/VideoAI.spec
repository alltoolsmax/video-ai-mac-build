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
    (os.path.join(PKG, "update_config.json"), "videoai"),
    (os.path.join(PKG, "license_config.json"), "videoai"),
]
datas += collect_data_files("playwright")
# VieNeu-TTS v3 Turbo (nếu đã cài): giọng mẫu (assets/*.json), từ điển phát âm sea_g2p, onnxruntime
_tts_hidden = []
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    import importlib.util
    if importlib.util.find_spec("vieneu"):
        datas += collect_data_files("vieneu") + collect_data_files("sea_g2p") + collect_data_files("vieneu_utils")
        _skip = ("fast", "turbo", "standard", "core_xpu", "remote", "serve", "v3_turbo_serve", "finetune")
        _tts_hidden = (collect_submodules("vieneu", filter=lambda n: not any(p in _skip for p in n.split(".")[1:]))
                       + collect_submodules("vieneu_utils") + collect_submodules("sea_g2p")
                       + ["onnxruntime", "soundfile", "soxr", "kaldi_native_fbank", "tokenizers", "huggingface_hub", "yaml"])
except Exception as e:
    print("Bo qua VieNeu-TTS:", e)

hiddenimports = collect_submodules("videoai") + [
    "PySide6.QtSvg", "keyring.backends.Windows", "openpyxl.cell._writer",
] + _tts_hidden

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
