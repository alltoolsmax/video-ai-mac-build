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
                                     "'site_downloads_dir' => " + json.dumps(str(dl)) + ", 'mac_github_json' => '/khong/co.json', 'gh_video_win.json' => "
                                     + json.dumps(str(tmp_path / "gh_video_win.json")) + "];")
    (tmp_path / "gh_video_win.json").write_text(json.dumps({"version": "2.1.5", "sha256": "c" * 64, "size": 123456789}))
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
        # Windows do GitHub build: bấm Phát hành → khách tải thẳng từ GitHub
        assert call("releases")["win_github"]["version"] == "2.1.5"
        r = call("release_publish", {"version": "2.1.5", "github": True, "os": "win", "notes": "gh"})
        assert r["ok"] and r["url"] == "https://github.com/alltoolsmax/video-ai-mac-build/releases/download/v2.1.5/video_ai_mrhuynh_win.exe"
        w = version()
        assert w["version"] == "2.1.5" and w["sha256"] == "c" * 64 and w["size"] == 123456789
        # đếm máy đã cài / đang hoạt động (giống GCloud Hub)
        version("?m=mayA1234567890&v=2.1.3&tier=pro&os=win")
        version("?os=mac&m=mayB1234567890&v=2.1.3&tier=free")
        version("?m=mayA1234567890&v=2.1.3&tier=pro&os=win")
        version("?m=khong%20hop%20le&v=x")                 # mã máy sai: chỉ tính lượt kiểm tra
        with urllib.request.urlopen(f"{U}/video/index.php/v1/app/ping?m=mayC1234567890&v=2.1.2&tier=free&os=win",
                                    timeout=30) as r:
            assert json.loads(r.read())["ok"]
        ins = call("installs")
        st = ins["stats"]
        assert st["total"] == 3 and st["active_24h"] == 3 and st["online"] == 3 and st["used_30d"] == 3
        assert st["checks"] == 7 and st["pro_30d"] == 1 and st["free_30d"] == 2 and st["mac_30d"] == 1
        assert st["release_win"] == "2.1.5" and st["release_mac"] == "1.9.11"
        a = [x for x in ins["list"] if x["machine"] == "mayA1234567890"][0]
        assert a["checks"] == 2 and a["os"] == "win" and a["version"] == "2.1.3" and a["tier"] == "pro"
        # Voice AI 1.6.2+: báo qua /v1/app/ping?p=voice → bảng riêng, không lẫn với Video AI
        for q in ("p=voice&m=MH-1A2B-3C4D-5E6F-7A8B&v=1.6.2&os=win&tier=licensed&k=open",
                  "p=voice&m=MH-1A2B-3C4D-5E6F-7A8B&v=1.6.2&os=win&tier=licensed",
                  "p=voice&m=MH-AAAA-BBBB-CCCC-DDDD&v=1.6.2&os=mac&tier=trial&k=open"):
            with urllib.request.urlopen(f"{U}/video/index.php/v1/app/ping?{q}", timeout=30) as r:
                assert json.loads(r.read())["ok"]
        vi = call("v_installs")
        vs = vi["stats"]
        assert vs["total"] == 2 and vs["online"] == 2 and vs["opens"] == 2
        assert vs["licensed_30d"] == 1 and vs["trial_30d"] == 1 and vs["mac_30d"] == 1
        assert call("installs")["stats"]["total"] == 3                # Video AI không đổi
    finally:
        srv.terminate()


def test_download_filename_header_has_no_quotes():
    """Tên tệp tải về phải đúng "video_ai_mrhuynh_win.exe": không có \\" (hosting không xử lý dấu thoát →
    trình duyệt đổi thành "_video_ai_mrhuynh_win.exe_" và khách không chạy được)."""
    t = (Path(__file__).resolve().parents[1] / "hosting" / "downloads" / ".htaccess").read_text(encoding="utf-8")
    lines = [l for l in t.splitlines() if "Content-Disposition" in l]
    assert len(lines) == 4
    for l in lines:
        assert '\\"' not in l and l.count('"') == 2
    assert "filename=video_ai_mrhuynh_win.exe\"" in t and "filename=video_ai_mrhuynh_mac.dmg\"" in t


def test_mac_update_comes_from_github_release(tmp_path):
    """Mac: máy chủ đọc video_mac.json của bản mới nhất trên GitHub (tên cố định), trả bộ cài đúng chip."""
    priv = tmp_path / "priv"
    priv.mkdir()
    mj = tmp_path / "video_mac.json"
    mj.write_text(json.dumps({"version": "2.1.5", "apple": {"file": "video_ai_mrhuynh_mac_apple.dmg", "sha256": "a" * 64, "size": 10},
                              "intel": {"file": "video_ai_mrhuynh_mac_intel.dmg", "sha256": "b" * 64, "size": 20}}))
    (priv / "config.php").write_text("<?php return ['mac_github_json' => " + json.dumps(str(mj)) + "];")

    def ask(q):
        script = tmp_path / "t.php"
        script.write_text("<?php\nrequire " + json.dumps(str(ROOT / "hosting/active_private/video/lib.php")) + ";\n"
                          "parse_str(" + json.dumps(q) + ", $_GET); VideoAI\\api_version();")
        out = subprocess.run(["php", str(script)], capture_output=True, text=True, timeout=60,
                             env={"VIDEOAI_PRIVATE": str(priv), "PATH": "/usr/bin:/bin"})
        return json.loads(out.stdout)
    a = ask("os=mac&arch=arm64&m=mayMac00000001&v=2.1.4")
    assert a["version"] == "2.1.5" and a["sha256"] == "a" * 64
    assert a["url"] == "https://github.com/alltoolsmax/video-ai-mac-build/releases/download/v2.1.5/video_ai_mrhuynh_mac_apple.dmg"
    i = ask("os=mac&v=2.1.3")                         # bản cũ chưa gửi chip → bản Intel (chạy được mọi máy Mac)
    assert i["url"].endswith("/v2.1.5/video_ai_mrhuynh_mac_intel.dmg") and i["size"] == 20
    w = ask("v=2.1.4")                                # Windows: vẫn từ trang quản trị
    assert w["version"] == "0.0.0"
    mj.write_text("hỏng")                             # GitHub lỗi: dùng bản đã nhớ
    assert ask("os=mac&arch=arm64")["version"] == "2.1.5"
