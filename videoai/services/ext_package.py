"""Tìm thư mục Tiện ích Chrome đi kèm app và đóng gói thành ZIP cho người dùng tải về."""
from __future__ import annotations

import zipfile
from pathlib import Path

from ..core.paths import app_root, package_dir

ZIP_NAME = "video-ai-tro-ly-chrome.zip"


def extension_dir() -> Path | None:
    """Thư mục chrome-extension đi kèm (cạnh exe khi đã đóng gói, hoặc trong mã nguồn khi chạy dev)."""
    for base in (app_root(), package_dir().parent, Path(__file__).resolve().parents[2]):
        d = base / "chrome-extension"
        if (d / "manifest.json").exists():
            return d
    return None


def make_zip(dest: Path) -> Path:
    src = extension_dir()
    if src is None:
        raise FileNotFoundError("Không tìm thấy thư mục chrome-extension đi kèm Tools.")
    dest = Path(dest)
    if dest.is_dir():
        dest = dest / ZIP_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(src).as_posix())
    return dest
