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


def upscale_ffmpeg(src: str, out: str, scale: int = 2) -> Path:
    """Dự phòng khi chưa có Real-ESRGAN: phóng to Lanczos + làm nét nhẹ."""
    from .ffmpeg import run
    run(["-i", src, "-vf", f"scale=iw*{scale}:ih*{scale}:flags=lanczos,unsharp=5:5:0.6", out])
    return Path(out)
