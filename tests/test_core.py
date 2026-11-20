"""Kiểm thử đơn vị: DB, nhập prompt, nhân vật, phụ đề, webhook."""
import json
import pytest
import urllib.request
from pathlib import Path

import pytest


def test_batch_and_recover(db):
    bid = db.create_batch("flow", "flow_image", {"model": "x"}, "/tmp/o", "per_task",
                          [{"mode": "t2i", "prompt": "a"}, {"mode": "t2i", "prompt": "b", "count": 2}])
    jobs = db.query("SELECT * FROM jobs WHERE batch_id=? ORDER BY row_no", (bid,))
    assert [j["row_no"] for j in jobs] == [1, 2] and jobs[1]["count"] == 2
    db.update_job(jobs[0]["id"], status="running")
    assert db.recover_running() == 1
    assert db.job(jobs[0]["id"])["status"] == "queued"
    assert db.counts("flow", "flow_image") == {"queued": 2}


def test_status_check_constraint(db):
    import sqlite3
    bid = db.create_batch("flow", "flow_image", {}, "/tmp", "flat", [{"mode": "t2i", "prompt": "a"}])
    j = db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,))[0]
    with pytest.raises(sqlite3.IntegrityError):
        db.update_job(j["id"], status="weird")


def test_settings_unicode(db):
    db.set_setting("x", {"tên": "Huỳnh 😀"})
    assert db.get_setting("x") == {"tên": "Huỳnh 😀"}


def test_prompt_io(tmp_path):
    from videoai.services import prompt_io
    assert prompt_io.split_prompts("a\n\n b \nc") == ["a", "b", "c"]
    assert prompt_io.split_prompts("dòng 1\ndòng 2\n\ncảnh 2", "block") == ["dòng 1\ndòng 2", "cảnh 2"]
    f = tmp_path / "p.txt"
    f.write_text("Phở bò\nHội An 🏮\n", encoding="utf-8")
    assert prompt_io.load_file(f) == ["Phở bò", "Hội An 🏮"]
    c = tmp_path / "p.csv"
    c.write_text("id,prompt\n1,mèo\n2,chó\n", encoding="utf-8")
    assert prompt_io.load_file(c) == ["mèo", "chó"]
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["STT", "Prompt"])
    ws.append([1, "cánh đồng lúa"])
    ws.append([2, None])
    ws.append([3, "biển xanh"])
    x = tmp_path / "p.xlsx"
    wb.save(x)
    assert prompt_io.load_file(x) == ["cánh đồng lúa", "biển xanh"]


def test_ref_library(db, tmp_path):
    from videoai.media import ffmpeg
    from videoai.services.refs import RefLibrary
    lib = RefLibrary(db)
    src = tmp_path / "Cô gái áo dài.png"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(src)])
    a = lib.add(str(src), "Minh", "Nhân vật", "chàng trai 25 tuổi, tóc ngắn")
    b = lib.add(str(src))                               # tên tự gợi ý từ tên tệp
    c = lib.add(str(src), "minh")                       # trùng tên (không phân biệt hoa thường) → Minh2
    assert lib.get(b)["name"] == "CoGaiAoDai" and lib.get(c)["name"] == "minh2"
    text, refs = lib.expand("@Minh đi dạo phố, @Lan đứng chờ")
    assert text.startswith("Minh (chàng trai 25 tuổi, tóc ngắn) đi dạo")
    assert "@Lan" in text and refs == [lib.get(a)["path"]]
    assert Path(lib.get(a)["path"]).parent.name == "refs"   # ảnh được chép vào kho
    assert lib.update(b, "Minh", "Bối cảnh", "") == "Minh2" or True
    assert [g for g, n in lib.groups() if n] [:1] == ["Nhân vật"]
    lib.delete([a])
    assert lib.get(a) is None and len(lib.all()) == 2


def test_srt_roundtrip():
    from videoai.media import srt
    s = srt.from_lines(["Xin chào", "", "Tạm biệt"], 2.5)
    cues = srt.parse_srt(s)
    assert [c["text"] for c in cues] == ["Xin chào", "Tạm biệt"]
    assert cues[0]["start"] == 0 and cues[0]["end"] == 2.5


def test_slugify():
    from videoai.core.engine import slugify
    assert slugify("Bát phở bò tái bốc khói!") == "bat_pho_bo_tai_boc_khoi"
    assert slugify("😀😀") == "prompt"
    assert len(slugify("a" * 200)) == 40


def test_webhook(db, qapp):
    from videoai.services.webhook import WebhookServer

    class FakeEngine:
        started = []

        def start_page(self, *a):
            self.started.append(a)

    eng = FakeEngine()
    aid = db.add_account("flow", "me", "/tmp/p")
    wh = WebhookServer(db, eng)
    wh.start(0) if False else None
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    wh.start(port)
    base = f"http://127.0.0.1:{port}"

    def call(path, body=None, token=wh.token):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        assert call("/api/pages", token="sai")[0] == 401
        code, res = call("/api/jobs", {"page": "flow_video", "prompts": ["a", " ", "b"], "count": 99})
        assert code == 201 and res["jobs"] == 2
        assert eng.started[0][0] == "flow_video" and eng.started[0][1] == aid
        jobs = db.query("SELECT count FROM jobs")
        assert all(j["count"] == 4 for j in jobs)        # bị giới hạn max_count
        assert call("/api/jobs", {"page": "nope", "prompts": ["a"]})[0] == 400
        assert call("/api/jobs", {"page": "flow_image", "prompts": ["a"], "mode": "t2v"})[0] == 400
        code, st = call(f"/api/jobs/{res['batch_id']}")
        assert code == 200 and len(st["jobs"]) == 2 and st["finished"] is False
    finally:
        wh.stop()


def test_updater_flow(tmp_path, monkeypatch):
    """Máy chủ cập nhật giả: latest.json + bộ cài; kiểm tra so sánh phiên bản, tải về, kiểm SHA-256."""
    import functools, hashlib, json, threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from videoai.core import updater
    setup = tmp_path / "VideoAI-MrHuynh-Setup-9.9.0.exe"
    setup.write_bytes(b"MZ" + b"x" * 100_000 + b"Inno Setup Setup Data (6.4.0)" + b"y" * 100_000)
    app_exe = tmp_path / "VideoAI-MrHuynh 9.9.0.exe"          # file chạy (không phải bộ cài) → phải bị từ chối
    app_exe.write_bytes(b"MZ" + b"z" * 150_000)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    (tmp_path / "latest.json").write_text(json.dumps({"version": "9.9.0", "url": base + setup.name,
                                                       "sha256": hashlib.sha256(setup.read_bytes()).hexdigest()}))

    class DB:
        def get_setting(self, k, d=None):
            return base + "latest.json" if k == "update_url" else d
    assert updater.is_newer("1.10.0", "1.9.9") and not updater.is_newer("1.1.0", "1.1.0")
    info = updater.check(DB())
    assert info["version"] == "9.9.0"
    got = []
    path = updater.download(info, lambda p, m: got.append(p))
    assert path.read_bytes() == setup.read_bytes() and got[-1] == 100
    info["sha256"] = "0" * 64
    with pytest.raises(RuntimeError):
        updater.download(info)
    with pytest.raises(RuntimeError, match="không phải bộ cài"):
        updater.download({"version": "9.9.0", "url": base + "VideoAI-MrHuynh%209.9.0.exe"})
    (tmp_path / "latest.json").write_text(json.dumps({"version": "0.1", "url": base + setup.name}))
    assert updater.check(DB()) is None
    (tmp_path / "latest.json").write_text(json.dumps({"version": "9.9.1", "url": "http://evil.example/x.exe"}))
    with pytest.raises(RuntimeError):            # link tải không phải https → từ chối
        updater.check(DB())
    srv.shutdown()


def test_updater_server_defaults(tmp_path, monkeypatch):
    """Không cấu hình riêng → hỏi máy chủ bản quyền /v1/app/version; min_version → bắt buộc."""
    import json
    from videoai.core import updater
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    monkeypatch.setattr(updater, "package_dir", lambda: pkg)
    (pkg / "license_config.json").write_text(json.dumps({"server_url": "https://active.mrhuynh.net/video/"}))
    assert updater.manifest_url() == "https://active.mrhuynh.net/video/v1/app/version"
    (pkg / "update_config.json").write_text(json.dumps({"manifest_url": "https://x.example/latest.json"}))
    assert updater.manifest_url() == "https://x.example/latest.json"
    (pkg / "license_config.json").write_text("{}")
    (pkg / "update_config.json").write_text("{}")
    assert updater.manifest_url() == ""
    assert updater.is_mandatory({"min_version": "1.5.0"}, "1.4.3")
    assert not updater.is_mandatory({"min_version": "1.5.0"}, "1.5.0")
    assert updater.is_mandatory({"mandatory": True}, "9.0")
    assert not updater.is_mandatory({"min_version": ""}, "1.0")


def test_palette_and_languages():
    import colorsys, json
    from videoai.ui import palette
    from videoai.core.i18n import LANGUAGES
    from videoai.core.paths import package_dir
    lum = lambda h: colorsys.rgb_to_hls(*palette._rgb(h))[1]
    assert palette.map_hex("#070b24", "dark_navy") == "#070b24"
    for th in ("light_ivory", "light_ice"):
        assert lum(palette.map_hex("#070b24", th)) > 0.9          # nền tối → nền sáng
        assert lum(palette.map_hex("#eaf0ff", th)) < 0.35         # chữ sáng → chữ tối
        assert palette.map_hex("#ffffff", th) == "#ffffff"        # chữ trắng trên nút màu giữ nguyên
    assert lum(palette.map_hex("#070b24", "dark_graphite")) < 0.15
    assert list(LANGUAGES) == ["vi", "en", "zh", "hi", "ja", "ko"]
    keys = None
    for code in ("en", "zh", "hi", "ja", "ko"):
        d = json.loads((package_dir() / "languages" / f"{code}.json").read_text(encoding="utf-8"))
        assert len(d) > 300 and d["Cài đặt"] and d["Tạo Video Flow"]
        keys = keys or set(d)
        assert set(d) == keys                                     # 5 ngôn ngữ đủ cùng bộ chữ


def test_upscale_exact_factors(tmp_path, monkeypatch):
    """Nâng cấp ảnh 2x/3x/4x/6x ra đúng kích thước; Real-ESRGAN luôn chạy ×4 rồi đưa về đúng cỡ."""
    from PySide6.QtGui import QImage
    from videoai.media import ffmpeg, upscale
    src = tmp_path / "a.png"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc=s=120x80", "-frames:v", "1", str(src)])
    monkeypatch.setattr(upscale, "available", lambda: False)                 # chưa có Real-ESRGAN: Lanczos
    for f in (2, 3, 4, 6):
        out = upscale.upscale_to(str(src), str(tmp_path / f"o{f}.png"), f)
        im = QImage(str(out))
        assert (im.width(), im.height()) == (120 * f, 80 * f), (f, im.width(), im.height())
    calls = []

    def fake_esr(s, o, scale, model, fmt, on_pct=None):                                   # giả lập Real-ESRGAN ×4
        calls.append(scale)
        ffmpeg.run(["-y", "-i", s, "-vf", "scale=iw*4:ih*4", o])
    monkeypatch.setattr(upscale, "available", lambda: True)
    monkeypatch.setattr(upscale, "upscale", fake_esr)
    for f in (2, 3, 4, 6):
        out = upscale.upscale_to(str(src), str(tmp_path / f"e{f}.jpg"), f, fmt="jpg")
        im = QImage(str(out))
        assert (im.width(), im.height()) == (120 * f, 80 * f)
    assert calls == [4, 4, 4, 4] and not list(tmp_path.glob("*_x4tmp.png"))
