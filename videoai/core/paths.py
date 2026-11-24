"""Đường dẫn dùng chung. Mọi file người dùng nằm trong %APPDATA%/VideoAI-MrHuynh (Windows),
~/Library/Application Support/VideoAI-MrHuynh (macOS) hoặc ~/.videoai-mrhuynh (nơi khác). Có thể ghi đè bằng biến môi trường VIDEOAI_HOME."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Video AI - Mr. Huỳnh"
APP_SLUG = "VideoAI-MrHuynh"
APP_VERSION = "2.2.4"
IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"


def app_root() -> Path:
    """Thư mục chứa mã nguồn / exe (để tìm assets, bin)."""
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def package_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    env = os.environ.get("VIDEOAI_HOME")
    if env:
        p = Path(env)
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA", Path.home())) / APP_SLUG
    elif IS_MAC:
        p = Path.home() / "Library" / "Application Support" / APP_SLUG
    else:
        p = Path.home() / ".videoai-mrhuynh"
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_dir() -> Path:
    p = data_dir() / "profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_output_dir() -> Path:
    p = Path.home() / ("Movies" if IS_MAC else "Videos") / APP_SLUG / "output"
    return p


def assets_dir() -> Path:
    return package_dir() / "assets"


def bin_path(name: str) -> str:
    """Tìm công cụ đi kèm trong ./bin/<name>/..., sau đó tới PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    for base in (app_root() / "bin", package_dir().parent / "bin"):
        for cand in (base / name / exe, base / exe):
            if cand.exists():
                return str(cand)
        if base.exists():
            for sub in base.iterdir():
                if sub.is_dir() and (sub / exe).exists():
                    return str(sub / exe)
    return name
