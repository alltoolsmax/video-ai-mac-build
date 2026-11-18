"""Các thao tác video bằng ffmpeg đi kèm (bin/ffmpeg) hoặc ffmpeg trong PATH."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ..core.paths import bin_path

NOWIN = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW


def ffmpeg() -> str:
    return bin_path("ffmpeg")


def ffprobe() -> str:
    return bin_path("ffprobe")


def run(args: list[str]) -> None:
    p = subprocess.run([ffmpeg(), "-hide_banner", "-y", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NOWIN)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-1500:])


def probe(path: str | Path) -> dict:
    p = subprocess.run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])
    return json.loads(p.stdout)


def duration(path) -> float:
    return float(probe(path)["format"].get("duration", 0) or 0)


def has_audio(path) -> bool:
    return any(s.get("codec_type") == "audio" for s in probe(path).get("streams", []))


# ---------------- cắt ----------------
def cut_segments(src: str, out_dir: str, seg_seconds: float) -> list[Path]:
    """Chia video thành các đoạn dài seg_seconds (cắt chính xác, mã hóa lại)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    total = duration(src)
    files = []
    t, i = 0.0, 1
    stem = Path(src).stem
    while t < total - 0.05:
        f = out / f"{stem}_part{i:03d}.mp4"
        run(["-ss", f"{t:.3f}", "-i", src, "-t", f"{min(seg_seconds, total - t):.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", str(f)])
        files.append(f)
        t += seg_seconds
        i += 1
    return files


def cut_range(src: str, out: str, start: float, end: float) -> Path:
    run(["-ss", f"{start:.3f}", "-i", src, "-t", f"{end - start:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", out])
    return Path(out)


# ---------------- khung hình ----------------
def extract_frame(src: str, out: str, which: str = "last", at: float | None = None) -> Path:
    if which == "first":
        run(["-i", src, "-frames:v", "1", "-q:v", "1", out])
    elif which == "at" and at is not None:
        run(["-ss", f"{at:.3f}", "-i", src, "-frames:v", "1", "-q:v", "1", out])
    else:  # khung cuối
        run(["-sseof", "-0.1", "-i", src, "-update", "1", "-frames:v", "1", "-q:v", "1", out])
    return Path(out)


def extract_every(src: str, out_dir: str, every_s: float) -> list[Path]:
    o = Path(out_dir)
    o.mkdir(parents=True, exist_ok=True)
    run(["-i", src, "-vf", f"fps=1/{every_s}", "-q:v", "2", str(o / (Path(src).stem + "_%04d.jpg"))])
    return sorted(o.glob(Path(src).stem + "_*.jpg"))


# ---------------- ghép ----------------
def concat(clips: list[str], out: str, size: tuple[int, int] = (1920, 1080), fps: int = 30,
           music: str | None = None, music_volume: float = 0.3, keep_clip_audio: bool = True,
           subtitles: str | None = None, fade: float = 0.0) -> Path:
    """Ghép nhiều clip (chuẩn hóa kích thước/fps), thêm nhạc nền và phụ đề SRT (đốt vào hình)."""
    w, h = size
    args: list[str] = []
    for c in clips:
        args += ["-i", c]
    n = len(clips)
    parts = []
    for i, c in enumerate(clips):
        v = (f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
             f"setsar=1,fps={fps},format=yuv420p")
        if fade > 0:
            d = duration(c)
            v += f",fade=t=in:st=0:d={fade},fade=t=out:st={max(0, d - fade)}:d={fade}"
        parts.append(v + f"[v{i}]")
        if keep_clip_audio and has_audio(c):
            parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        else:
            d = duration(c)
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{d:.3f}[a{i}]")
    parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    vlast, alast = "[vc]", "[ac]"
    if subtitles:
        sub = subtitles.replace("\\", "/").replace(":", "\\:")
        parts.append(f"{vlast}subtitles='{sub}':force_style='FontName=Inter,FontSize=22,Outline=2'[vs]")
        vlast = "[vs]"
    if music:
        args += ["-stream_loop", "-1", "-i", music]
        parts.append(f"[{n}:a]volume={music_volume}[bg]")
        parts.append(f"{alast}[bg]amix=inputs=2:duration=first:dropout_transition=2[am]")
        alast = "[am]"
    args += ["-filter_complex", ";".join(parts), "-map", vlast, "-map", alast,
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", out]
    run(args)
    return Path(out)


def images_to_video(images: list[str], out: str, seconds_each: float = 3.0, size=(1920, 1080), fps=30) -> Path:
    """Trình chiếu ảnh (hiệu ứng zoom nhẹ)."""
    tmp = Path(tempfile.mkdtemp())
    clips = []
    w, h = size
    frames = int(seconds_each * fps)
    for i, im in enumerate(images):
        c = tmp / f"s{i:03d}.mp4"
        run(["-loop", "1", "-i", im, "-t", f"{seconds_each}", "-vf",
             f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,crop={w*2}:{h*2},"
             f"zoompan=z='min(zoom+0.0008,1.12)':d={frames}:s={w}x{h}:fps={fps},format=yuv420p",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(c)])
        clips.append(str(c))
    return concat(clips, out, size, fps, keep_clip_audio=False)


def remove_audio(src: str, out: str) -> Path:
    run(["-i", src, "-c:v", "copy", "-an", out])
    return Path(out)


def speed(src: str, out: str, factor: float) -> Path:
    a = []
    f = factor
    while f > 2.0:
        a.append("atempo=2.0"); f /= 2.0
    while f < 0.5:
        a.append("atempo=0.5"); f /= 0.5
    a.append(f"atempo={f:.4f}")
    if has_audio(src):
        run(["-i", src, "-filter_complex", f"[0:v]setpts=PTS/{factor}[v];[0:a]{','.join(a)}[a]",
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "19", out])
    else:
        run(["-i", src, "-vf", f"setpts=PTS/{factor}", "-c:v", "libx264", "-crf", "19", out])
    return Path(out)


def reframe(src: str, out: str, ratio: str = "9:16", mode: str = "blur") -> Path:
    """Đổi khung 16:9 ↔ 9:16: 'blur' (nền mờ) hoặc 'crop' (cắt giữa)."""
    w, h = (1080, 1920) if ratio == "9:16" else (1920, 1080) if ratio == "16:9" else (1080, 1080)
    if mode == "crop":
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        run(["-i", src, "-vf", vf, "-c:v", "libx264", "-crf", "19", "-c:a", "copy", out])
    else:
        fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:2[bg];"
              f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
        run(["-i", src, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "19",
             "-c:a", "copy", out])
    return Path(out)


def add_logo(src: str, logo: str, out: str, corner: str = "br", scale: float = 0.12, opacity: float = 0.9) -> Path:
    """Chèn logo CỦA BẠN lên video (không dùng để che/xóa watermark của nền tảng)."""
    pos = {"tl": "20:20", "tr": "W-w-20:20", "bl": "20:H-h-20", "br": "W-w-20:H-h-20"}[corner]
    fc = (f"[1:v][0:v]scale2ref=w=iw*{scale}:h=ow/mdar[lg][base];[lg]format=rgba,colorchannelmixer=aa={opacity}[l];"
          f"[base][l]overlay={pos}[v]")
    run(["-i", src, "-i", logo, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "19",
         "-c:a", "copy", out])
    return Path(out)
