"""Xử lý tệp cho Video Lip-Sync: cắt video gốc theo thời lượng, chọn tỷ lệ, ghép lại tiếng gốc."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from . import ffmpeg

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def duration(path: str) -> float:
    try:
        return ffmpeg.duration(path)
    except Exception:
        return 0.0


def size(path: str) -> tuple[int, int] | None:
    from ..editor.render import media_size
    return media_size(path)


def prepare_clip(src: str, secs: float) -> str:
    """Đoạn 0 → secs giây của video gốc (ngắn hơn thì lấy hết), mã hóa lại H.264/AAC để Flow nhận ổn định."""
    d = Path(tempfile.mkdtemp(prefix="va_ls_"))
    out = d / f"{Path(src).stem[:40]}_{int(secs)}s.mp4"
    length = duration(src)
    t = min(float(secs), length) if length > 0 else float(secs)
    args = ["-i", src, "-t", f"{t:.3f}", "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    ffmpeg.run(args)
    return str(out)


def pick_ratio(choice: str, clip: str) -> str:
    """'Theo video gốc' → 16:9 nếu video ngang / vuông, 9:16 nếu video dọc. Flow chế độ Thành phần chỉ có 2 tỷ lệ này."""
    c = (choice or "").split(" ")[0]
    if c in ("16:9", "9:16"):
        return c
    sz = size(clip)
    return "9:16" if sz and sz[1] > sz[0] else "16:9"


def put_audio(video: str | Path, audio_src: str) -> Path:
    """Thay tiếng của kết quả bằng tiếng của đoạn video gốc (giữ nguyên hình). Video gốc không có tiếng → giữ nguyên."""
    video = Path(video)
    try:
        if not ffmpeg.has_audio(audio_src):
            return video
    except Exception:
        return video
    tmp = video.with_name(video.stem + "_tmpaudio" + video.suffix)
    ffmpeg.run(["-i", str(video), "-i", audio_src, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(tmp)])
    tmp.replace(video)
    return video


def cleanup(clip: str):
    try:
        shutil.rmtree(Path(clip).parent, ignore_errors=True)
    except Exception:
        pass


def pair_files(paths: list[str]) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Ghép cặp video + ảnh từ danh sách tệp: trùng tên (bỏ đuôi) thì ghép với nhau, còn lại ghép theo thứ tự.
    Trả về (các cặp (video, ảnh | None), ảnh còn dư)."""
    vids = [p for p in paths if Path(p).suffix.lower() in VIDEO_EXT]
    imgs = [p for p in paths if Path(p).suffix.lower() in IMAGE_EXT]
    by_stem = {Path(i).stem.lower(): i for i in imgs}
    pairs, used = [], set()
    for v in vids:
        i = by_stem.get(Path(v).stem.lower())
        if i and i not in used:
            used.add(i)
            pairs.append((v, i))
        else:
            pairs.append((v, None))
    rest = [i for i in imgs if i not in used]
    for k, (v, i) in enumerate(pairs):
        if i is None and rest:
            pairs[k] = (v, rest.pop(0))
    return pairs, rest
