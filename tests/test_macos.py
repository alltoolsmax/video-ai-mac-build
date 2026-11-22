"""Bản macOS (chạy giả lập trên Linux): tự cập nhật bằng .dmg, mã máy, gói tải lên trang tải."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_manifest_url_asks_for_mac_build(monkeypatch, tmp_path):
    from videoai.core import updater
    (tmp_path / "license_config.json").write_text(json.dumps({"server_url": "https://active.example/video"}))
    monkeypatch.setattr(updater, "package_dir", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert updater.manifest_url(None) == "https://active.example/video/v1/app/version?os=mac"
    monkeypatch.setattr(sys, "platform", "win32")
    assert updater.manifest_url(None).endswith("/v1/app/version")


def test_mac_machine_id_uses_platform_uuid(monkeypatch):
    from videoai.core import license as LIC
    monkeypatch.delenv("VIDEOAI_MACHINE_ID", raising=False)
    monkeypatch.setattr(LIC.os, "name", "posix")
    monkeypatch.setattr(sys, "platform", "darwin")

    class R:
        stdout = '  "IOPlatformUUID" = "1234ABCD-0000-1111-2222-333344445555"\n'
    monkeypatch.setattr(LIC.subprocess, "run", lambda *a, **k: R())
    a = LIC.machine_id()
    R.stdout = '  "IOPlatformUUID" = "FFFF0000-0000-1111-2222-333344445555"\n'
    assert a != LIC.machine_id() and len(a) == 40


def test_download_checks_dmg(tmp_path, monkeypatch):
    """Tệp .dmg phải là ảnh đĩa thật (khối 'koly' cuối tệp) và khớp SHA-256."""
    import http.server
    import socketserver
    import threading
    from videoai.core import updater
    good = b"\x01" * 100000 + b"koly" + b"\0" * 508
    (tmp_path / "ok.dmg").write_bytes(good)
    (tmp_path / "bad.dmg").write_bytes(b"\x01" * 100512)
    h = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path), **k)
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path / "t"))
    try:
        p = updater.download({"url": f"http://127.0.0.1:{port}/ok.dmg?v=2", "sha256": hashlib.sha256(good).hexdigest(),
                              "size": len(good)})
        assert p.name == "ok.dmg" and p.read_bytes() == good
        with pytest.raises(RuntimeError, match="macOS"):
            updater.download({"url": f"http://127.0.0.1:{port}/bad.dmg", "size": 100512})
    finally:
        srv.shutdown()


def test_mac_self_update_replaces_app_and_reopens(tmp_path, monkeypatch):
    """Ứng dụng thoát → gắn .dmg → chép .app mới đè .app cũ (cùng chỗ) → gỡ .dmg → mở lại ứng dụng."""
    from videoai.core import updater
    apps = tmp_path / "Applications"
    old = apps / "Video AI - Mr Huynh.app"
    (old / "Contents" / "MacOS").mkdir(parents=True)
    (old / "Contents" / "MacOS" / "VideoAI-MrHuynh").write_text("old")
    (old / "Contents" / "MacOS" / "stale.txt").write_text("x")
    newsrc = tmp_path / "dmgsrc" / "Video AI - Mr Huynh.app" / "Contents" / "MacOS"
    newsrc.mkdir(parents=True)
    (newsrc / "VideoAI-MrHuynh").write_text("new")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    log = tmp_path / "calls.txt"
    (fake / "hdiutil").write_text(f"""#!/bin/sh
echo "hdiutil $@" >> '{log}'
if [ "$1" = attach ]; then
  while [ $# -gt 0 ]; do if [ "$1" = -mountpoint ]; then shift; cp -R '{tmp_path / "dmgsrc"}'/. "$1"/; fi; shift; done
fi
exit 0
""")
    (fake / "ditto").write_text('#!/bin/sh\ncp -R "$1" "$2"\n')
    (fake / "open").write_text(f'#!/bin/sh\necho "open $@" >> \'{log}\'\n')
    for f in fake.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(old / "Contents" / "MacOS" / "VideoAI-MrHuynh"))
    monkeypatch.setattr(updater.os, "getpid", _dead_pid)
    assert updater.mac_bundle() == old.resolve() and updater.can_self_install()
    dmg = tmp_path / "upd" / "video_ai_mrhuynh_mac.dmg"
    dmg.parent.mkdir()
    dmg.write_bytes(b"x")
    updater.install_and_restart(dmg)
    for _ in range(100):
        if log.exists() and "open " in log.read_text():
            break
        time.sleep(0.1)
    calls = log.read_text()
    assert "hdiutil attach" in calls and "hdiutil detach" in calls and f"open {old.resolve()}" in calls
    assert (old / "Contents" / "MacOS" / "VideoAI-MrHuynh").read_text() == "new"
    assert not (old / "Contents" / "MacOS" / "stale.txt").exists() and not Path(str(old) + ".new").exists()


def test_make_downloads_mac(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import make_downloads as MD
    monkeypatch.setattr(MD, "ROOT", tmp_path)
    (tmp_path / "videoai" / "core").mkdir(parents=True)
    (tmp_path / "videoai" / "core" / "paths.py").write_text('APP_VERSION = "2.0.0"\n')
    dmg = tmp_path / "a.dmg"
    data = b"\x01" * 2000 + b"koly" + b"\0" * 508
    dmg.write_bytes(data)
    out = MD.main_mac(dmg, "arm64")
    info = json.loads((out / "mac.json").read_text())
    assert info["version"] == "2.0.0" and info["sha256"] == hashlib.sha256(data).hexdigest() and info["arch"] == "arm64"
    import zipfile
    assert sorted(zipfile.ZipFile(tmp_path / "dist" / "downloads-mac-upload.zip").namelist()) == ["mac.json", "video_ai_mrhuynh_mac.dmg"]
    (tmp_path / "x.dmg").write_bytes(b"\x01" * 3000)
    with pytest.raises(SystemExit):
        MD.main_mac(tmp_path / "x.dmg")


def test_download_page_has_mac_section():
    html = (ROOT / "hosting/downloads/index.template.html").read_text(encoding="utf-8")
    assert "video_ai_mrhuynh_mac.dmg" in html and "mac.json" in html and "Vẫn mở" in html
    ht = (ROOT / "hosting/downloads/.htaccess").read_text(encoding="utf-8")
    assert "x-apple-diskimage" in ht and 'filename=\\"video_ai_mrhuynh_mac.dmg\\"' in ht


def test_build_scripts_are_valid_shell():
    for f in ("build Mac.command", "build/fetch_tools_mac.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / f)]).returncode == 0, f
        assert b"\r\n" not in (ROOT / f).read_bytes()
