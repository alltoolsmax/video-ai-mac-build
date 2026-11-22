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


def _fake_dmg(path: Path, size_mb: int = 6) -> bytes:
    data = b"\x78\x01" + b"\x02" * (size_mb << 20) + b"koly" + b"\0" * 508
    path.write_bytes(data)
    return data


def test_admin_publish_windows_and_mac_separately(tmp_path):
    """Trang quản trị phát hành bản Windows (.exe) và macOS (.dmg + mac.json) riêng; /v1/app/version?os=mac trả bản Mac,
    phần mềm Windows cũ (không gửi ?os) vẫn nhận bản Windows. CSDL cũ chưa có cột os được tự nâng cấp."""
    import sqlite3
    import urllib.request
    priv = tmp_path / "priv"
    dl = tmp_path / "dl"
    priv.mkdir()
    dl.mkdir()
    (priv / "lib.php").symlink_to(ROOT / "hosting/active_private/video/lib.php")
    (priv / "config.php").write_text("<?php return ['seed_hex' => str_repeat('ab', 32), 'admin_password' => 'matkhau-test-123', "
                                     "'site_downloads_dir' => " + json.dumps(str(dl)) + "];")
    (priv / "data").mkdir()
    db = sqlite3.connect(priv / "data" / "videoai.sqlite")          # CSDL bản cũ: bảng releases chưa có cột os
    db.execute("CREATE TABLE releases (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL, url TEXT NOT NULL, "
               "sha256 TEXT, size INTEGER, notes TEXT, mandatory INTEGER NOT NULL DEFAULT 0, min_version TEXT, "
               "active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)")
    db.commit()
    db.close()
    _fake_setup(dl / "video_ai_mrhuynh_win.exe", "1.9.11")
    dmg = _fake_dmg(dl / "video_ai_mrhuynh_mac.dmg")
    (dl / "mac.json").write_text(json.dumps({"version": "1.9.11", "sha256": hashlib.sha256(dmg).hexdigest(), "arch": "arm64"}))
    env = {"VIDEOAI_PRIVATE": str(priv), "ACTIVE_PRIVATE": str(tmp_path / "none"), "PATH": "/usr/bin:/bin"}
    srv = subprocess.Popen(["php", "-S", "127.0.0.1:8768", "-t", str(ROOT / "hosting/active.mrhuynh.net")], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    U = "http://127.0.0.1:8768"

    def call(a, body=None):
        req = urllib.request.Request(f"{U}/admin/api.php?a={a}", data=json.dumps(body).encode() if body else None,
                                     headers={"x-admin-token": "matkhau-test-123", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def version(q=""):
        with urllib.request.urlopen(f"{U}/video/index.php/v1/app/version{q}", timeout=30) as r:
            return json.loads(r.read())
    try:
        time.sleep(1.2)
        rel = call("releases")
        assert rel["site_mac"]["version"] == "1.9.11" and rel["site_mac"]["arch"] == "arm64"
        assert call("release_publish", {"version": "1.9.11", "site": True, "os": "win", "notes": "win"})["ok"]
        bad = None
        try:
            call("release_publish", {"version": "1.9.12", "site": True, "os": "mac"})
        except urllib.error.HTTPError as e:
            bad = json.loads(e.read())
        assert bad and "1.9.11" in bad.get("error", bad.get("message", json.dumps(bad, ensure_ascii=False)))
        r = call("release_publish", {"version": "1.9.11", "site": True, "os": "mac", "notes": "mac"})
        assert r["ok"] and r["url"].endswith("video_ai_mrhuynh_mac.dmg?v=1.9.11")
        w, m = version(), version("?os=mac")
        assert w["url"].endswith("video_ai_mrhuynh_win.exe?v=1.9.11") and w["notes"] == "win"
        assert m["url"].endswith("video_ai_mrhuynh_mac.dmg?v=1.9.11") and m["sha256"] == hashlib.sha256(dmg).hexdigest()
    finally:
        srv.terminate()
