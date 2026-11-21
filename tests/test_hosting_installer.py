"""Máy chủ PHP: phát hành bản cập nhật bằng file DUY NHẤT trên trang tải (video_ai_mrhuynh_win.exe) –
đọc số phiên bản trong bộ cài, SHA-256, kiểm tra là bộ cài Inno Setup; đọc từ ổ đĩa hosting hoặc tải qua https/http."""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("php"), reason="cần php")


def _fake_setup(path: Path, ver: str, size_mb: int = 6) -> bytes:
    """Giả bộ cài: có chuỗi 'Inno Setup' và khối thông tin phiên bản UTF-16 như tài nguyên VERSIONINFO."""
    vi = "ProductVersion".encode("utf-16le") + b"\0\0" + b"\0\0" + ver.encode("utf-16le") + b"\0\0"
    data = b"MZ" + b"\0" * 4000 + vi + b"\0" * 1000 + b"Inno Setup Setup Data (6.4.0)" + b"\x01" * (size_mb << 20)
    path.write_bytes(data)
    return data


def _php(tmp_path, code: str) -> dict:
    priv = tmp_path / "priv"
    priv.mkdir(exist_ok=True)
    (priv / "config.php").write_text("<?php return ['site_downloads_dir' => " + json.dumps(str(tmp_path / "dl")) + "];")
    script = tmp_path / "t.php"
    script.write_text("<?php\nrequire " + json.dumps(str(ROOT / "hosting/active_private/video/lib.php")) + ";\n" + code)
    out = subprocess.run(["php", str(script)], capture_output=True, text=True, timeout=120,
                         env={"VIDEOAI_PRIVATE": str(priv), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr + out.stdout
    return json.loads(out.stdout)


def test_version_sha_and_inno_from_disk(tmp_path):
    (tmp_path / "dl").mkdir()
    data = _fake_setup(tmp_path / "dl" / "video_ai_mrhuynh_win.exe", "1.9.10.0")
    r = _php(tmp_path, "$p = VideoAI\\site_installer_path('/khong/co/admin');"
                       "echo json_encode(['p' => $p] + VideoAI\\inspect_installer($p));")
    assert r["p"].endswith("dl/video_ai_mrhuynh_win.exe")
    assert r["version"] == "1.9.10" and r["inno"] and r["size"] == len(data)
    assert r["sha256"] == hashlib.sha256(data).hexdigest()


def test_inspect_over_http_and_cpanel_layout(tmp_path):
    # bố cục cPanel: /home/u/active.mrhuynh.net/admin  và  /home/u/public_html/downloads
    home = tmp_path / "home"
    (home / "active.mrhuynh.net" / "admin").mkdir(parents=True)
    (home / "public_html" / "downloads").mkdir(parents=True)
    data = _fake_setup(home / "public_html" / "downloads" / "video_ai_mrhuynh_win.exe", "2.0.1")
    srv = subprocess.Popen(["php", "-S", "127.0.0.1:8766", "-t", str(home / "public_html" / "downloads")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        r = _php(tmp_path,
                 "$p = VideoAI\\site_installer_path(" + json.dumps(str(home / "active.mrhuynh.net" / "admin")) + ");"
                 "$h = VideoAI\\inspect_installer('http://127.0.0.1:8766/video_ai_mrhuynh_win.exe?check=1');"
                 "echo json_encode(['p' => $p, 'h' => $h]);")
        assert r["p"] == str(home / "public_html" / "downloads" / "video_ai_mrhuynh_win.exe")
        assert r["h"]["version"] == "2.0.1" and r["h"]["sha256"] == hashlib.sha256(data).hexdigest()
    finally:
        srv.terminate()


def test_not_an_installer(tmp_path):
    (tmp_path / "dl").mkdir()
    (tmp_path / "dl" / "video_ai_mrhuynh_win.exe").write_bytes(b"MZ" + b"\0" * 100)
    r = _php(tmp_path, "echo json_encode(VideoAI\\inspect_installer(VideoAI\\site_installer_path('/x/y')));")
    assert not r["inno"] and r["version"] == ""
