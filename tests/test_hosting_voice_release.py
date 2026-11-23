"""Voice AI phát hành giống Video AI: file trên trang tải → trang quản trị kiểm tra, tính SHA-256, máy chủ tự ký,
ghi version.json; máy chủ Voice trả version_mac + link .dmg theo chip; phần mềm Voice AI chấp nhận chữ ký."""
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VOICE_REPO = Path("/home/claude/voice-ai-mac-build")
pytestmark = pytest.mark.skipif(not shutil.which("php") or not Path("/tmp/vvenv/bin/python").exists() or not VOICE_REPO.exists(), reason="cần php + mã nguồn Voice AI")


def _fake_setup(p: Path, ver: str) -> bytes:
    vi = "ProductVersion".encode("utf-16le") + b"\0\0" + b"\0\0" + ver.encode("utf-16le") + b"\0\0"
    data = b"MZ" + b"\0" * 4000 + vi + b"Inno Setup Setup Data (6.4.0)" + b"\x01" * (6 << 20)
    p.write_bytes(data)
    return data


def _fake_dmg(p: Path, fill: bytes) -> bytes:
    data = fill * (1 << 20) + b"koly" + b"\0" * 508
    p.write_bytes(data)
    return data


def test_voice_release_like_video(tmp_path):
    seed = "11" * 32
    pub = subprocess.run(["php", "-r", f"echo bin2hex(sodium_crypto_sign_publickey(sodium_crypto_sign_seed_keypair(hex2bin('{seed}'))));"],
                         capture_output=True, text=True).stdout.strip()
    site = tmp_path / "site"
    priv = tmp_path / "priv"
    dl = tmp_path / "dl"
    (site / "admin").mkdir(parents=True)
    (priv / "video").mkdir(parents=True)
    dl.mkdir()
    for f in ("index.html", "api.php"):
        shutil.copy(ROOT / "hosting/active.mrhuynh.net/admin" / f, site / "admin" / f)
    shutil.copy(ROOT / "may-chu-chung/voice-ai/active.mrhuynh.net/index.php", site / "index.php")
    shutil.copy(ROOT / "may-chu-chung/voice-ai/active.mrhuynh.net/version.json", site / "version.json")
    (site / "router.php").write_text("<?php $p = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);\n"
                                     "if (str_starts_with($p, '/api/')) { require __DIR__ . '/index.php'; return true; } return false;")
    shutil.copy(ROOT / "hosting/active_private/video/lib.php", priv / "video" / "lib.php")
    shutil.copy(ROOT / "may-chu-chung/voice-ai/active_private/lib.php", priv / "lib.php")
    (priv / "video" / "config.php").write_text("<?php return ['seed_hex' => str_repeat('ab', 32), 'admin_password' => 'matkhau-test-123', "
                                               "'site_downloads_dir' => " + json.dumps(str(dl)) + "];")
    (priv / "config.php").write_text("<?php return ['seed_hex' => '" + seed + "', 'plans' => ['1m' => ['name' => '1 tháng', 'days' => 30, "
                                     "'price' => 99000, 'type' => 1]], 'order_ttl_minutes' => 30];")
    exe = _fake_setup(dl / "voice_ai_mrhuynh_win.exe", "1.6.2")
    (dl / "voice_win.json").write_text(json.dumps({"version": "1.6.2", "sha256": hashlib.sha256(exe).hexdigest(), "size": len(exe)}))
    a = _fake_dmg(dl / "voice_ai_mrhuynh_mac_apple.dmg", b"A")
    i = _fake_dmg(dl / "voice_ai_mrhuynh_mac_intel.dmg", b"I")
    (dl / "voice_mac.json").write_text(json.dumps({"version": "1.6.2", "apple": {"sha256": hashlib.sha256(a).hexdigest(), "size": len(a)},
                                                   "intel": {"sha256": hashlib.sha256(i).hexdigest(), "size": len(i)}}))
    env = {"VIDEOAI_PRIVATE": str(priv / "video"), "ACTIVE_PRIVATE": str(priv), "PATH": "/usr/bin:/bin",
           "VOICEAI_UPDATE_PUBKEY_HEX": pub}
    srv = subprocess.Popen(["php", "-S", "127.0.0.1:8769", "-t", str(site), str(site / "router.php")], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    U = "http://127.0.0.1:8769"

    def call(a, body=None):
        req = urllib.request.Request(f"{U}/admin/api.php?a={a}", data=json.dumps(body).encode() if body else None,
                                     headers={"x-admin-token": "matkhau-test-123", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())
    try:
        time.sleep(1.2)
        r = call("v_releases")
        assert r["site"]["win"]["version"] == "1.6.2"
        assert r["current"]["version"] == "1.6.1"
        bad = call("v_release_publish", {"version": "1.6.3", "os": "win"})
        assert not bad["ok"] and "1.6.2" in bad["message"]
        r = call("v_release_publish", {"version": "1.6.2", "os": "win", "notes": "Bắt buộc cập nhật\nĐếm số máy"})
        assert r["ok"], r
        v = json.loads((site / "version.json").read_text())
        assert v["version"] == "1.6.2" and v["sha256"] == hashlib.sha256(exe).hexdigest() and v["signature"]
        assert v["url"].endswith("/voice_ai_mrhuynh_win.exe?v=1.6.2") and v["url_mac"] == "https://github.com/alltoolsmax/voice-ai-mac-build/releases/latest"
        assert v["highlights"] == ["Bắt buộc cập nhật", "Đếm số máy"]
        # phần mềm Voice AI chấp nhận chữ ký do máy chủ tạo
        chk = subprocess.run([str(Path("/tmp/vvenv/bin/python")), "-c",
                              "import sys; sys.path.insert(0, sys.argv[1]); from apps.update_installer import verify_signature as v; "
                              "print(v(sys.argv[2], sys.argv[3], sys.argv[4], bytes.fromhex(sys.argv[5])), "
                              "v('9.9.9', sys.argv[3], sys.argv[4], bytes.fromhex(sys.argv[5])))",
                              str(VOICE_REPO), "1.6.2", v["sha256"], v["signature"], pub], capture_output=True, text=True)
        assert chk.stdout.strip() == "True False", chk.stderr
        bad = call("v_release_publish", {"version": "1.6.2", "os": "mac"})
        assert not bad["ok"] and "GitHub" in bad["message"]
        with urllib.request.urlopen(f"{U}/api/app/version", timeout=30) as resp:
            api = json.loads(resp.read())
        assert api["version"] == "1.6.2" and api["signature"] == v["signature"] and api["sha256"] == v["sha256"]
        hist = call("v_releases")["releases"]
        assert [h["os"] for h in hist] == ["win"]
        # khóa trên hosting khác khóa trong phần mềm → không ký
        srv.terminate()
        srv.wait(10)
        env["VOICEAI_UPDATE_PUBKEY_HEX"] = "00" * 32
        srv = subprocess.Popen(["php", "-S", "127.0.0.1:8769", "-t", str(site), str(site / "router.php")], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.2)
        bad = call("v_release_publish", {"version": "1.6.2", "os": "win"})
        assert not bad["ok"] and "KHÁC khóa" in bad["message"]
    finally:
        srv.terminate()
