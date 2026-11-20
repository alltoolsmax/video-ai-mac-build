"""Nâng cấp ảnh bằng Real-ESRGAN ncnn-vulkan (chạy trên GPU bất kỳ qua Vulkan, có cả CPU dự phòng chậm).
Tải bản Windows tại github.com/xinntao/Real-ESRGAN/releases (realesrgan-ncnn-vulkan-*.zip),
giải nén vào bin/realesrgan/ (script build/fetch_tools.ps1 làm việc này)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..core.paths import bin_path

NOWIN = 0x08000000 if os.name == "nt" else 0
MODELS = {
    "Ảnh thật (realesrgan-x4plus)": "realesrgan-x4plus",
    "Anime / minh họa (realesrgan-x4plus-anime)": "realesrgan-x4plus-anime",
    "Nhanh (realesr-animevideov3)": "realesr-animevideov3",
}


def available() -> bool:
    exe = bin_path("realesrgan-ncnn-vulkan")
    return Path(exe).exists() or bool(__import__("shutil").which(exe))


def upscale(src: str, out: str, scale: int = 4, model: str = "realesrgan-x4plus", fmt: str = "png") -> Path:
    exe = bin_path("realesrgan-ncnn-vulkan")
    mdir = Path(exe).parent / "models"
    args = [exe, "-i", src, "-o", out, "-n", model, "-s", str(scale), "-f", fmt]
    if mdir.exists():
        args += ["-m", str(mdir)]
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    if p.returncode != 0 or not Path(out).exists():
        raise RuntimeError((p.stderr or p.stdout)[-800:] or "Real-ESRGAN lỗi")
    return Path(out)


def _size(path: str) -> tuple[int, int]:
    from PySide6.QtGui import QImageReader
    s = QImageReader(path).size()
    return s.width(), s.height()


def upscale_to(src: str, out: str, factor: float, model: str = "realesrgan-x4plus", fmt: str = "png") -> Path:
    """Nâng ảnh lên đúng ×factor (2, 3, 4, 6…). Real-ESRGAN luôn chạy ×4 (đúng tỷ lệ gốc của model, cho chi tiết tốt nhất)
    rồi đưa về kích thước cần: ×2/×3 thu nhỏ Lanczos từ bản ×4 (nét hơn phóng thẳng), ×6 phóng thêm ×1.5 + làm nét nhẹ.
    Chưa có Real-ESRGAN: phóng to Lanczos + làm nét."""
    from .ffmpeg import run
    w, h = _size(src)
    if w <= 0 or h <= 0:
        raise RuntimeError("Không đọc được ảnh: " + Path(src).name)
    tw, th = int(round(w * factor)) // 2 * 2, int(round(h * factor)) // 2 * 2
    out_p = Path(out)
    if not available():
        run(["-y", "-i", src, "-vf", f"scale={tw}:{th}:flags=lanczos,unsharp=5:5:0.6", str(out_p)])
        return out_p
    tmp = out_p.with_name(out_p.stem + "_x4tmp.png")
    try:
        upscale(src, str(tmp), 4, model, "png")
        if abs(factor - 4) < 1e-6 and fmt == "png":
            tmp.replace(out_p)
            return out_p
        sharpen = ",unsharp=5:5:0.5" if factor > 4 else ""
        run(["-y", "-i", str(tmp), "-vf", f"scale={tw}:{th}:flags=lanczos{sharpen}", str(out_p)])
        return out_p
    finally:
        tmp.unlink(missing_ok=True)


def upscale_ffmpeg(src: str, out: str, scale: int = 2) -> Path:
    """Dự phòng khi chưa có Real-ESRGAN: phóng to Lanczos + làm nét nhẹ."""
    from .ffmpeg import run
    run(["-i", src, "-vf", f"scale=iw*{scale}:ih*{scale}:flags=lanczos,unsharp=5:5:0.6", out])
    return Path(out)
