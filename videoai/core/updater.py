"""Cập nhật online.

Máy chủ chỉ cần một tệp JSON công khai (vd. trên GitHub Releases, Cloudflare R2, hosting riêng):

    {
      "version": "1.2.0",
      "url": "https://.../VideoAI-MrHuynh-Setup-1.2.0.exe",
      "sha256": "…",                       # build/make_release.py tự tính
      "notes": "- Sửa lỗi …\n- Thêm …",
      "mandatory": false
    }

Mặc định phần mềm hỏi chính máy chủ bản quyền: <server_url>/v1/app/version (hosting của bạn, quản lý ở
trang quản trị › Cập nhật phần mềm). Có thể ghi đè bằng videoai/update_config.json hoặc cài đặt "update_url".
"min_version": bản thấp hơn số này bắt buộc cập nhật (không có nút "Để sau").
Luồng: kiểm tra → tải bộ cài về thư mục tạm (kiểm tra SHA-256) → thoát ứng dụng → chạy bộ cài ở chế độ im lặng
vào đúng thư mục đang cài → mở lại ứng dụng bản mới.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from .paths import APP_VERSION, app_root, package_dir

UA = {"User-Agent": f"VideoAI-MrHuynh/{APP_VERSION}"}
INNO_MARK = b"Inno Setup"


def _vt(v: str) -> tuple:
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (4 - len(out)))


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _vt(remote) > _vt(local)


def manifest_url(db=None) -> str:
    if db is not None:
        u = (db.get_setting("update_url", "") or "").strip()
        if u:
            return u
    f = package_dir() / "update_config.json"
    try:
        u = json.loads(f.read_text(encoding="utf-8")).get("manifest_url", "").strip()
        if u:
            return u
    except Exception:
        pass
    try:      # mặc định: máy chủ bản quyền (hosting) → /v1/app/version
        srv = json.loads((package_dir() / "license_config.json").read_text(encoding="utf-8")).get("server_url", "").strip()
    except Exception:
        srv = ""
    return srv.rstrip("/") + "/v1/app/version" if srv.startswith("http") else ""


def is_mandatory(info: dict, local: str = APP_VERSION) -> bool:
    mv = (info.get("min_version") or "").strip()
    return bool(info.get("mandatory")) or bool(mv and _vt(local) < _vt(mv))


def check(db=None, timeout: int = 15) -> dict | None:
    """Trả về thông tin bản mới nếu có, None nếu đang dùng bản mới nhất. Lỗi mạng → ném lỗi."""
    url = manifest_url(db)
    if not url:
        raise RuntimeError("Chưa cấu hình địa chỉ kiểm tra cập nhật.")
    req = urllib.request.Request(url, headers={**UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        info = json.loads(r.read().decode("utf-8"))
    if not info.get("version"):
        raise RuntimeError("Tệp thông tin cập nhật không hợp lệ.")
    if not is_newer(info["version"]):
        return None
    if not str(info.get("url", "")).startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise RuntimeError("Link tải bản cập nhật không hợp lệ (phải là https).")
    return info


def download(info: dict, progress=None) -> Path:
    dest = Path(tempfile.gettempdir()) / "VideoAI-MrHuynh-update" / Path(info["url"].split("?")[0]).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    req = urllib.request.Request(info["url"], headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        total = total or int(info.get("size") or 0)
        inno = False
        tail = b""
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            if not inno:                        # bộ cài Inno Setup có chuỗi này; file chạy của PyInstaller thì không
                inno = INNO_MARK in (tail + chunk)
                tail = chunk[-64:]
            got += len(chunk)
            if progress and total:
                progress(int(got * 100 / total), f"{got / 1e6:.1f} / {total / 1e6:.1f} MB")
    size = int(info.get("size") or 0)
    if size and dest.stat().st_size != size:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Tải chưa đủ dung lượng (mạng bị ngắt). Hãy thử lại.")
    if not inno and dest.suffix.lower() == ".exe":
        dest.unlink(missing_ok=True)
        raise RuntimeError("File cập nhật trên máy chủ không phải bộ cài (Setup) mà là file chạy. "
                           "Người bán cần tải đúng file VideoAI-MrHuynh-Setup-x.y.z.exe lên máy chủ.")
    want = (info.get("sha256") or "").lower()
    if want and h.hexdigest() != want:
        dest.unlink(missing_ok=True)
        raise RuntimeError("Tệp tải về không khớp mã kiểm tra (mạng lỗi, hoặc máy chủ đang thay bản mới). Hãy thử lại sau ít phút.")
    if progress:
        progress(100, "")
    return dest


def can_self_install() -> bool:
    return os.name == "nt" and getattr(sys, "frozen", False)


def install_and_restart(setup: Path) -> None:
    """Chạy bộ cài im lặng vào thư mục hiện tại rồi mở lại ứng dụng. Gọi xong thì thoát ứng dụng ngay."""
    app_dir = app_root()
    exe = Path(sys.executable)
    script = Path(tempfile.gettempdir()) / "VideoAI-MrHuynh-update" / "apply_update.cmd"
    log_file = script.with_name("apply_update.log")
    script.write_text(   # ping thay cho timeout: timeout lỗi khi không có cửa sổ console
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "ping -n 4 127.0.0.1 >nul\r\n"
        f"start \"\" /wait \"{setup}\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /DIR=\"{app_dir}\" /LOG=\"{log_file}\"\r\n"
        f"start \"\" \"{exe}\"\r\n",
        encoding="utf-8")
    flags = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
