"""Kiểm thử đơn vị: DB, nhập prompt, nhân vật, phụ đề, webhook."""
import json
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


def test_characters_expand(db, tmp_path):
    from videoai.services.characters import Characters
    ch = Characters(db)
    img = str(tmp_path / "minh.png")
    ch.save("Minh", "chàng trai 25 tuổi, tóc ngắn", [img])
    text, refs = ch.expand("@Minh đi dạo phố, @Lan đứng chờ")
    assert text.startswith("Minh (chàng trai 25 tuổi, tóc ngắn) đi dạo")
    assert "@Lan" in text and refs == [img]
    text2, _ = ch.expand("@minh cười", with_description=False)
    assert text2 == "Minh cười"


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
