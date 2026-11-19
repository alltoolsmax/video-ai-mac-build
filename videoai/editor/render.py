"""Xuất dự án dựng video ra MP4 bằng ffmpeg (một lệnh filter_complex)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from ..media.ffmpeg import NOWIN, duration, ffmpeg, has_audio
from .model import FILTERS, Project


def font_file() -> str | None:
    cands = []
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        cands += [Path(win) / "Fonts" / n for n in ("segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf")]
    cands += [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
              Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")]
    for c in cands:
        if c.exists():
            return str(c)
    return None


def _esc_path(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _atempo(speed: float) -> list[str]:
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    out.append(f"atempo={s:.4f}")
    return out


def build_command(p: Project, out: str, preview: bool = False) -> tuple[list[str], str]:
    """Trả về (lệnh ffmpeg, thư mục tạm). preview=True: xuất nhanh độ phân giải thấp."""
    if not p.clips:
        raise ValueError("Timeline chưa có clip video/ảnh nào.")
    tmp = tempfile.mkdtemp(prefix="vae_")
    W, H = (p.width, p.height) if not preview else (p.width // 3 // 2 * 2, p.height // 3 // 2 * 2)
    fps = p.fps
    args: list[str] = []
    fc: list[str] = []
    n_in = 0
    vlabels, alabels = [], []
    for i, c in enumerate(p.clips):
        if c.kind == "image":
            args += ["-loop", "1", "-framerate", str(fps), "-t", f"{c.dur + 0.1:.3f}", "-i", c.src]
        else:
            args += ["-i", c.src]
        idx = n_in
        n_in += 1
        d = c.dur
        chain = []
        if c.kind == "video":
            chain.append(f"trim=start={c.in_s:.3f}:end={c.out_s:.3f},setpts=PTS-STARTPTS")
            if abs(c.speed - 1) > 1e-3:
                chain.append(f"setpts=PTS/{c.speed:.4f}")
        else:
            chain.append(f"trim=duration={d:.3f},setpts=PTS-STARTPTS")
        sw, sh = int(W * c.scale) // 2 * 2, int(H * c.scale) // 2 * 2
        chain.append(f"scale={sw}:{sh}:force_original_aspect_ratio=decrease")
        if c.scale >= 1:
            chain.append(f"pad={max(W, sw)}:{max(H, sh)}:(ow-iw)/2:(oh-ih)/2:black,crop={W}:{H}")
        else:
            chain.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
        chain.append(f"setsar=1,fps={fps},format=yuv420p")
        if FILTERS.get(c.filter):
            chain.append(FILTERS[c.filter])
        if c.fade_in > 0:
            chain.append(f"fade=t=in:st=0:d={min(c.fade_in, d / 2):.3f}")
        if c.fade_out > 0:
            fo = min(c.fade_out, d / 2)
            chain.append(f"fade=t=out:st={d - fo:.3f}:d={fo:.3f}")
        fc.append(f"[{idx}:v]{','.join(chain)}[v{i}]")
        vlabels.append(f"[v{i}]")
        if c.kind == "video" and c.has_audio and c.volume > 0 and has_audio(c.src):
            ach = [f"atrim=start={c.in_s:.3f}:end={c.out_s:.3f},asetpts=PTS-STARTPTS"]
            if abs(c.speed - 1) > 1e-3:
                ach += _atempo(c.speed)
            ach.append(f"volume={c.volume:.3f},aresample=48000,aformat=channel_layouts=stereo")
            if c.fade_in > 0:
                ach.append(f"afade=t=in:st=0:d={min(c.fade_in, d / 2):.3f}")
            if c.fade_out > 0:
                fo = min(c.fade_out, d / 2)
                ach.append(f"afade=t=out:st={d - fo:.3f}:d={fo:.3f}")
            ach.append(f"apad,atrim=duration={d:.3f}")
            fc.append(f"[{idx}:a]{','.join(ach)}[a{i}]")
        else:
            fc.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={d:.3f}[a{i}]")
        alabels.append(f"[a{i}]")
    n = len(p.clips)
    fc.append("".join(v + a for v, a in zip(vlabels, alabels)) + f"concat=n={n}:v=1:a=1[vcat][acat]")
    vlast = "[vcat]"
    total = p.video_duration
    # chữ
    font = font_file()
    for k, t in enumerate(p.texts):
        if t.start >= total:
            continue
        tf = Path(tmp) / f"t{k}.txt"
        tf.write_text(t.text, encoding="utf-8")
        size = int(t.size * (H / 1080))
        y = {"Trên": "h*0.08", "Giữa": "(h-text_h)/2"}.get(t.pos, "h-text_h-h*0.08")
        opts = [f"textfile='{_esc_path(str(tf))}'", f"fontsize={size}", f"fontcolor={t.color}",
                "x=(w-text_w)/2", f"y={y}", "line_spacing=8", "borderw=3", "bordercolor=black@0.85",
                f"enable='between(t,{t.start:.3f},{t.start + t.dur:.3f})'"]
        if font:
            opts.insert(0, f"fontfile='{_esc_path(font)}'")
        if t.box:
            opts += ["box=1", "boxcolor=black@0.35", f"boxborderw={max(6, size // 4)}"]
        fc.append(f"{vlast}drawtext={':'.join(opts)}[vt{k}]")
        vlast = f"[vt{k}]"
    # nhạc / lồng tiếng
    amix = ["[acat]"]
    for k, a in enumerate(p.audios):
        if a.start >= total:
            continue
        args += ["-i", a.src]
        idx = n_in
        n_in += 1
        d = min(a.dur, total - a.start)
        ch = [f"atrim=start={a.in_s:.3f}:end={a.in_s + d:.3f},asetpts=PTS-STARTPTS",
              f"volume={a.volume:.3f},aresample=48000,aformat=channel_layouts=stereo"]
        if a.fade_in > 0:
            ch.append(f"afade=t=in:st=0:d={min(a.fade_in, d / 2):.3f}")
        if a.fade_out > 0:
            fo = min(a.fade_out, d / 2)
            ch.append(f"afade=t=out:st={d - fo:.3f}:d={fo:.3f}")
        ms = int(a.start * 1000)
        ch.append(f"adelay={ms}|{ms}")
        fc.append(f"[{idx}:a]{','.join(ch)}[m{k}]")
        amix.append(f"[m{k}]")
    if len(amix) > 1:
        fc.append("".join(amix) + f"amix=inputs={len(amix)}:duration=first:dropout_transition=0:normalize=0[aout]")
        alast = "[aout]"
    else:
        alast = "[acat]"
    script = Path(tmp) / "graph.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")
    cmd = [ffmpeg(), "-hide_banner", "-y", *args, "-filter_complex_script", str(script),
           "-map", vlast, "-map", alast, "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "veryfast" if preview else "medium", "-crf", "28" if preview else "19",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", out]
    return cmd, tmp


def export(p: Project, out: str, progress=None, preview: bool = False) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    cmd, tmp = build_command(p, out, preview)
    total = max(0.1, p.video_duration)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", creationflags=NOWIN)
    err_lines: list[str] = []

    import threading

    def _err():
        for line in proc.stderr:
            err_lines.append(line)
            del err_lines[:-40]
    th = threading.Thread(target=_err, daemon=True)
    th.start()
    for line in proc.stdout:
        m = re.match(r"out_time_(?:us|ms)=(\d+)", line.strip())
        if m and progress:
            progress(min(99, int(int(m.group(1)) / 1e6 / total * 100)), "")
    proc.wait()
    th.join(timeout=2)
    if proc.returncode != 0:
        raise RuntimeError("".join(err_lines)[-1500:])
    if progress:
        progress(100, "")
    return Path(out)


def probe_media(path: str) -> dict:
    """Thời lượng + có âm thanh không (ảnh: 3 giây mặc định)."""
    from .model import media_kind
    k = media_kind(path)
    if k == "image":
        return {"kind": "image", "dur": 3.0, "audio": False}
    try:
        return {"kind": k, "dur": max(0.1, duration(path)), "audio": k == "audio" or has_audio(path)}
    except Exception:
        return {"kind": k, "dur": 5.0, "audio": False}
