"""Tải video từ link YouTube / TikTok / Facebook (và các trang yt-dlp hỗ trợ) bằng yt-dlp.

- yt-dlp.exe được giữ trong thư mục dữ liệu (ghi được) để tự cập nhật (`-U`): các trang đổi cách phát video
  thường xuyên, yt-dlp mới nhất mới tải được. Lần đầu: chép từ bin/yt-dlp đi kèm, không có thì tải từ GitHub.
- TikTok: chọn luồng KHÔNG có logo (yt-dlp đánh dấu luồng có logo là "watermarked" → loại ra).
  YouTube / Facebook: file gốc vốn không gắn logo.
- Gộp hình + tiếng bằng ffmpeg đi kèm, ra MP4 (hoặc MP3 nếu chỉ lấy âm thanh)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import bin_path, data_dir

NOWIN = 0x08000000 if os.name == "nt" else 0
EXE = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/" + ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")

QUALITIES = {
    "Tốt nhất (MP4)": None,
    "1080p (MP4)": 1080,
    "720p (MP4)": 720,
    "480p (MP4)": 480,
    "Chỉ âm thanh (MP3)": "mp3",
}
COOKIE_BROWSERS = {"Không dùng": None, "Firefox": "firefox", "Edge": "edge", "Chrome": "chrome", "Brave": "brave"}

PLATFORMS = [
    ("YouTube", r"(youtube\.com|youtu\.be)"),
    ("TikTok", r"(tiktok\.com|douyin\.com)"),
    ("Facebook", r"(facebook\.com|fb\.watch|fb\.com)"),
    ("Instagram", r"instagram\.com"),
    ("X / Twitter", r"(twitter\.com|x\.com)"),
]

NO_WATERMARK = "[format_note!*=?watermark]"


def platform_of(url: str) -> str:
    for name, pat in PLATFORMS:
        if re.search(pat, url, re.I):
            return name
    return "Khác"


def split_links(text: str) -> list[str]:
    """Lấy các link http(s) trong đoạn dán (mỗi dòng một link, hoặc lẫn trong chữ), bỏ trùng, giữ thứ tự."""
    out: list[str] = []
    for m in re.finditer(r"https?://[^\s<>\"']+", text or ""):
        u = m.group(0).rstrip(").,;]")
        if u not in out:
            out.append(u)
    return out


def tool_dir() -> Path:
    p = data_dir() / "tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ytdlp_cmd(auto_fetch: bool = True, log=None) -> list[str]:
    """Lệnh chạy yt-dlp. VIDEOAI_YTDLP (kiểm thử) > bản trong thư mục dữ liệu > chép từ bin > python -m yt_dlp > tải về."""
    env = os.environ.get("VIDEOAI_YTDLP")
    if env:
        return env.split("|")
    mine = tool_dir() / EXE
    if mine.exists():
        return [str(mine)]
    bundled = bin_path("yt-dlp")
    if Path(bundled).exists():
        shutil.copy2(bundled, mine)
        if os.name != "nt":
            mine.chmod(0o755)
        return [str(mine)]
    try:
        import yt_dlp  # noqa: F401  (máy lập trình có cài sẵn gói Python)
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        pass
    if not auto_fetch:
        raise RuntimeError("Chưa có yt-dlp")
    if log:
        log("Đang tải công cụ tải video (yt-dlp, ~18 MB) – chỉ lần đầu…")
    tmp = mine.with_suffix(".part")
    with urllib.request.urlopen(RELEASE_URL, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(mine)
    if os.name != "nt":
        mine.chmod(0o755)
    return [str(mine)]


def update_ytdlp(log=None) -> str:
    cmd = ytdlp_cmd(log=log)
    if len(cmd) != 1:
        return ""
    p = subprocess.run(cmd + ["-U"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NOWIN, timeout=180)
    lines = (p.stdout or p.stderr or "").strip().splitlines()
    return lines[-1] if lines else ""


def build_args(url: str, out_dir: str, quality: str = "Tốt nhất (MP4)", cookies: str | None = None) -> list[str]:
    q = QUALITIES.get(quality)
    ff = bin_path("ffmpeg")
    a = ["--newline", "--no-playlist", "--no-simulate", "--progress", "--encoding", "utf-8", "--windows-filenames",
         "--no-mtime", "--retries", "5", "--fragment-retries", "5",
         "--progress-template", "download:PRG|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
         "--print", "before_dl:TITLE|%(title)s",
         "--print", "after_move:FILE|%(filepath)s",
         "-P", str(out_dir), "-o", "%(title).90B [%(id)s].%(ext)s"]
    ff_full = ff if Path(ff).exists() else shutil.which(ff)
    if ff_full:
        a += ["--ffmpeg-location", ff_full]
    if q == "mp3":
        a += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        res = f"res:{q}," if q else "res,"
        a += ["-f", f"bv*{NO_WATERMARK}+ba/b{NO_WATERMARK}/bv*+ba/b",          # TikTok: luồng không logo trước
              "-S", res + "vcodec:h264,acodec:m4a",
              "--merge-output-format", "mp4", "--remux-video", "mp4"]
    if cookies:
        a += ["--cookies-from-browser", cookies]
    return a + ["--", url]


@dataclass
class Progress:
    percent: float = 0.0
    speed: str = ""
    eta: str = ""


def parse_line(line: str):
    """→ ("progress", Progress) | ("title", str) | ("file", str) | ("merge", "") | (None, line)."""
    line = line.rstrip("\r\n")
    if line.startswith("PRG|"):
        parts = (line.split("|") + ["", "", ""])[1:4]
        m = re.search(r"([\d.]+)%", parts[0])
        pct = float(m.group(1)) if m else 0.0
        return "progress", Progress(pct, parts[1].strip().replace("Unknown B/s", ""), re.sub(r"^(NA|Unknown)$", "", parts[2].strip()))
    if line.startswith("TITLE|"):
        return "title", line[6:].strip()
    if line.startswith("FILE|"):
        return "file", line[5:].strip()
    if line.startswith("[Merger]") or line.startswith("[VideoRemuxer]") or line.startswith("[ExtractAudio]"):
        return "merge", ""
    return None, line


ERRORS = [
    (r"ffmpeg.*not found|ffprobe.*not found|ffmpeg-location", "Thiếu ffmpeg (bin/ffmpeg) để gộp hình và tiếng."),
    (r"Private video|This video is private|content isn't available|not available to you",
     "Video riêng tư hoặc bị giới hạn – chọn \"Cookie từ trình duyệt\" (trình duyệt đã đăng nhập) rồi thử lại."),
    (r"Sign in to confirm|confirm your age|age-restricted|login required|log in|cookies",
     "Trang yêu cầu đăng nhập – chọn \"Cookie từ trình duyệt\" (trình duyệt đã đăng nhập tài khoản) rồi thử lại."),
    (r"Could not copy .*cookie|cookie database|Failed to decrypt|DPAPI",
     "Không đọc được cookie của trình duyệt – đóng hẳn trình duyệt đó rồi thử lại, hoặc chọn Firefox."),
    (r"Unsupported URL", "Link không được hỗ trợ – kiểm tra lại link video."),
    (r"Video unavailable|has been removed|does not exist|404", "Video không còn tồn tại hoặc link sai."),
    (r"HTTP Error 429|Too Many Requests|rate.?limit", "Trang đang giới hạn tải – đợi vài phút rồi thử lại."),
    (r"geo|not available in your country", "Video bị chặn theo quốc gia."),
]


def friendly_error(text: str) -> str:
    for pat, msg in ERRORS:
        if re.search(pat, text, re.I):
            return msg
    last = [l for l in text.strip().splitlines() if "ERROR" in l] or text.strip().splitlines()[-1:] or ["Lỗi không rõ"]
    return last[-1].replace("ERROR:", "").strip()[:300]


def download(url: str, out_dir: str, quality: str = "Tốt nhất (MP4)", cookies: str | None = None,
             on_event=None, cancel=None, log=None, _retried: bool = False) -> str:
    """Tải 1 link, trả về đường dẫn file. on_event(kind, value): "title" / "progress" (Progress) / "merge"."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    cmd = ytdlp_cmd(log=log) + build_args(url, out_dir, quality, cookies)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", creationflags=NOWIN, env=env)
    path, tail = "", []
    for line in p.stdout:
        if cancel and cancel():
            p.kill()
            raise RuntimeError("Đã dừng")
        kind, val = parse_line(line)
        if kind == "file":
            path = val
        elif kind:
            on_event and on_event(kind, val)
        else:
            tail = (tail + [val])[-40:]
    p.wait()
    if p.returncode == 0 and path and Path(path).exists():
        return path
    text = "\n".join(tail)
    # trang vừa đổi cách phát video → cập nhật yt-dlp rồi thử lại đúng 1 lần
    if not _retried and re.search(r"Unable to extract|Unsupported URL|nsig|Signature|HTTP Error 403|update", text, re.I):
        try:
            log and log("Đang cập nhật yt-dlp rồi thử lại…")
            update_ytdlp(log)
        except Exception:
            pass
        return download(url, out_dir, quality, cookies, on_event, cancel, log, _retried=True)
    raise RuntimeError(friendly_error(text))
