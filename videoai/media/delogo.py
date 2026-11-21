"""Xóa logo / watermark nhìn thấy (vd logo Flow ở góc phải dưới) trên ảnh và video do người dùng tạo, bằng ffmpeg.

Vùng logo = hình chữ nhật theo TỈ LỆ khung hình (x, y, w, h trong 0..1) → dùng chung cho mọi kích thước.
Cách xóa:
- "fill":  làm liền nền (bộ lọc delogo: nội suy từ viền xung quanh) – đẹp trên nền đơn giản
- "blur":  làm mờ mạnh vùng logo
- "crop":  cắt bỏ dải viền chứa logo rồi phóng lại đúng kích thước gốc (không còn dấu vết, mất một ít mép hình)
Lưu tệp mới (…_xoalogo), không ghi đè tệp gốc. Dấu ẩn SynthID của Google (không nhìn thấy) không bị ảnh hưởng."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import ffmpeg as F

VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# vị trí đặt sẵn (tỉ lệ khung hình). "auto" = logo Flow: chữ "Veo" nhỏ ở góc phải dưới
PRESETS = {
    "auto": (0.80, 0.885, 0.18, 0.095),
    "br": (0.78, 0.86, 0.20, 0.12),
    "bl": (0.02, 0.86, 0.20, 0.12),
    "tr": (0.78, 0.02, 0.20, 0.12),
    "tl": (0.02, 0.02, 0.20, 0.12),
}
METHODS = ("fill", "blur", "crop")


def is_video(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


def size_of(path) -> tuple[int, int]:
    st = next(s for s in F.probe(path)["streams"] if s.get("codec_type") == "video")
    w, h = int(st["width"]), int(st["height"])
    rot = str((st.get("tags") or {}).get("rotate", "0"))
    if rot in ("90", "270", "-90"):
        w, h = h, w
    return w, h


def clamp_box(box, w: int, h: int) -> tuple[int, int, int, int]:
    """Đổi tỉ lệ → điểm ảnh, nằm gọn trong khung (delogo cần cách mép ≥ 1 điểm ảnh)."""
    fx, fy, fw, fh = box
    x = int(round(fx * w))
    y = int(round(fy * h))
    bw = int(round(fw * w))
    bh = int(round(fh * h))
    x = max(1, min(x, w - 4))
    y = max(1, min(y, h - 4))
    bw = max(2, min(bw, w - x - 1))
    bh = max(2, min(bh, h - y - 1))
    return x, y, bw, bh


def build_filter(box, w: int, h: int, method: str) -> str:
    x, y, bw, bh = clamp_box(box, w, h)
    if method == "blur":
        r = max(4, min(bw, bh) // 3)
        return (f"[0:v]split[a][b];[b]crop={bw}:{bh}:{x}:{y},gblur=sigma={r}:steps=3[m];"
                f"[a][m]overlay={x}:{y}[v]")
    if method == "crop":
        # bỏ dải chứa logo theo cạnh gần nhất (dưới/trên), giữ đúng tỉ lệ rồi phóng về kích thước gốc
        cut = (h - y) if y + bh / 2 > h / 2 else (y + bh)
        cut = min(cut + 2, int(h * 0.3))
        nh = h - cut
        nw = int(w * nh / h) // 2 * 2
        nh = nh // 2 * 2
        oy = 0 if y + bh / 2 > h / 2 else cut
        ox = (w - nw) // 2
        if x + bw / 2 > w / 2:              # logo bên phải → giữ mép trái
            ox = 0
        elif x + bw / 2 < w / 2:
            ox = w - nw
        return f"[0:v]crop={nw}:{nh}:{ox}:{oy},scale={w}:{h}:flags=lanczos,setsar=1[v]"
    return f"[0:v]delogo=x={x}:y={y}:w={bw}:h={bh}[v]"


def out_path(src, out_dir) -> Path:
    s = Path(src)
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    o = d / f"{s.stem}_xoalogo{s.suffix.lower()}"
    k = 2
    while o.exists():
        o = d / f"{s.stem}_xoalogo_{k}{s.suffix.lower()}"
        k += 1
    return o


def remove(src, out_dir, box=PRESETS["auto"], method: str = "fill", on_pct=None) -> Path:
    """Xóa logo 1 tệp → đường dẫn tệp mới. on_pct(0..100) báo tiến độ (video)."""
    src = str(src)
    w, h = size_of(src)
    flt = build_filter(box, w, h, method if method in METHODS else "fill")
    out = out_path(src, out_dir)
    if not is_video(src):
        q = ["-q:v", "2"] if out.suffix in (".jpg", ".jpeg") else []
        F.run(["-i", src, "-filter_complex", flt, "-map", "[v]", "-frames:v", "1", *q, str(out)])
        return out
    dur = max(0.1, F.duration(src))
    args = [F.ffmpeg(), "-hide_banner", "-y", "-i", src, "-filter_complex", flt, "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", creationflags=F.NOWIN)
    for line in p.stdout:
        m = re.match(r"out_time_(?:ms|us)=(\d+)", line.strip())
        if m and on_pct:
            on_pct(min(99, int(int(m.group(1)) / 1e6 / dur * 100)))
    err = p.stderr.read()
    if p.wait() != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(err[-1200:])
    if on_pct:
        on_pct(100)
    return out


def preview_frame(src, dst) -> Path:
    """Ảnh để xem trước / khoanh vùng: ảnh gốc, hoặc khung giữa video."""
    if not is_video(src):
        return Path(src)
    at = max(0.0, F.duration(src) / 2)
    return F.extract_frame(str(src), str(dst), "at", at)
