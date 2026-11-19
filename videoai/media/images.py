"""Chuyển ảnh kết quả sang .jpg (yêu cầu: ảnh tải về luôn có đuôi .jpg)."""
from __future__ import annotations

from pathlib import Path

from ..core import log

L = log.get("images")
JPG_QUALITY = 95


def to_jpg(path: Path | str, quality: int = JPG_QUALITY) -> Path:
    """Đổi ảnh (png/webp/…) sang .jpg cùng tên, giữ nguyên độ phân giải; nền trong suốt → trắng.
    Lỗi thì giữ tệp gốc."""
    src = Path(path)
    if src.suffix.lower() in (".jpg", ".jpeg"):
        if src.suffix != ".jpg":
            dst = _free(src.with_suffix(".jpg"))
            src.rename(dst)
            return dst
        return src
    dst = _free(src.with_suffix(".jpg"))
    try:
        from PySide6.QtGui import QColor, QImage, QPainter
        img = QImage(str(src))
        if img.isNull():
            raise ValueError("không đọc được ảnh")
        if img.hasAlphaChannel():
            bg = QImage(img.size(), QImage.Format_RGB32)
            bg.fill(QColor("white"))
            p = QPainter(bg)
            p.drawImage(0, 0, img)
            p.end()
            img = bg
        if not img.save(str(dst), "JPG", quality):
            raise ValueError("không ghi được jpg")
    except Exception as e:
        try:
            from . import ffmpeg
            ffmpeg.run(["-i", str(src), "-q:v", "2", str(dst)])
        except Exception as e2:
            L.warning("Không đổi được %s sang .jpg (%s / %s), giữ tệp gốc", src.name, e, e2)
            return src
    try:
        src.unlink()
    except OSError:
        pass
    return dst


def _free(p: Path) -> Path:
    k, out = 1, p
    while out.exists():
        out = p.with_name(f"{p.stem}_{k}{p.suffix}")
        k += 1
    return out
