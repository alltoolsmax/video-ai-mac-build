"""v2.2.5 – cơ chế GỬI / NHẬN của Flow: tác vụ đã gửi lên Flow thì không bao giờ tạo lại ở tài khoản khác;
lỗi sau khi gửi → quay lại đúng tài khoản / đúng dự án để lấy kết quả. Chạy trên trang Flow giả lập (máy cục bộ)."""
import asyncio as aio
import json
import time
from pathlib import Path

import pytest

from videoai.adapters import flow as flow_mod


def _wait(db, bid, timeout=90):
    t = time.time()
    rows = []
    while time.time() - t < timeout:
        rows = db.query("SELECT * FROM jobs WHERE batch_id=? ORDER BY row_no", (bid,))
        if rows and all(r["status"] in ("done", "failed", "blocked", "cancelled") for r in rows):
            return rows
        time.sleep(0.5)
    raise AssertionError("hết thời gian: " + str([(r["row_no"], r["status"], r["error_text"]) for r in rows]))


@pytest.fixture()
def feng(db, qapp, mock_site, home):
    from videoai.core.engine import Engine
    proj = mock_site.replace("index.html", "project/index.html")
    db.set_setting("platform_urls", {"flow_image": proj, "flow_video": proj})
    db.set_setting("flow_rights_ok", True)
    flow_mod._HELD.clear()
    eng = Engine(db)
    eng.proj = proj
    yield eng
    eng.shutdown()


def _gens(eng, page_key):
    out = []
    for tabs in eng.runs[page_key].tabs.values():
        for tab in tabs:
            out += aio.run_coroutine_threadsafe(tab.evaluate("window.GENS || []"), eng.loop).result(10)
    return out


def test_timeout_after_send_receives_on_same_account_without_resending(db, feng, home):
    """Video tạo chậm hơn thời gian chờ: trước đây quá giờ → chuyển sang tài khoản khác TẠO LẠI (2 lần tốn tín dụng).
    Giờ: quay lại đúng tài khoản đã gửi, lấy kết quả của lần gửi đó – Flow chỉ nhận đúng 1 lần bấm Tạo."""
    a1 = db.add_account("flow", "s1", str(home / "ps1"))
    a2 = db.add_account("flow", "s2", str(home / "ps2"))
    bid = db.create_batch("flow", "flow_video", {"model": "Veo 3.1 - Fast", "ratio": "9:16 Dọc", "quality": "720p",
                                                  "timeout_s": 3}, str(home / "sr1"), "flat",
                          [{"mode": "t2v", "prompt": "SLOWME chú mèo đi dạo", "count": 1, "refs": []}])
    feng.start_page("flow_video", [a1, a2], 1, (0, 0))
    rows = _wait(db, bid, 120)
    r = rows[0]
    assert r["status"] == "done", (r["status"], r["error_text"])
    assert len(_gens(feng, "flow_video")) == 1                 # chỉ GỬI 1 lần
    assert r["attempts"] >= 1                                  # đã có ít nhất 1 lần quá giờ rồi NHẬN lại
    assert r["flow_sent"] is None                              # xong thì xóa biên nhận
    o = db.outputs(r["id"])
    assert len(o) == 1 and o[0]["path"].endswith(".mp4")


def test_lost_receipt_regenerates_once(db, feng, home, monkeypatch):
    """Biên nhận còn nhưng trong dự án không có ô nào của lần gửi đó (Flow đã không nhận) → tạo mới đúng 1 lần."""
    monkeypatch.setattr(flow_mod.FlowAdapter, "LOST_AFTER_S", 3)
    a1 = db.add_account("flow", "l1", str(home / "pl1"))
    bid = db.create_batch("flow", "flow_video", {"model": "Veo 3.1 - Fast", "ratio": "9:16 Dọc", "quality": "720p"},
                          str(home / "sr2"), "flat", [{"mode": "t2v", "prompt": "Chim bay", "count": 1, "refs": []}])
    jid = db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,))[0]["id"]
    db.set_flow_receipt(jid, {"account_id": a1, "project": feng.proj, "seen": [], "at": time.time() - 600,
                              "kind": "video", "want": 1, "state": "sent", "tries": 1})
    feng.start_page("flow_video", a1, 1, (0, 0))
    rows = _wait(db, bid, 120)
    assert rows[0]["status"] == "done", (rows[0]["status"], rows[0]["error_text"])
    assert len(_gens(feng, "flow_video")) == 1
    assert rows[0]["flow_sent"] is None


def test_receipt_of_unusable_account_is_dropped(db, feng, home):
    """Tài khoản đã gửi không còn trong hàng chạy (tắt / hết phiên) → bỏ biên nhận, chạy trên tài khoản khác."""
    a1 = db.add_account("flow", "u1", str(home / "pu1"))
    gone = db.add_account("flow", "u2", str(home / "pu2"))
    db.update_account(gone, enabled=0)                  # tài khoản đã gửi bị tắt
    bid = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "quality": "1K"}, str(home / "sr3"), "flat",
                          [{"mode": "t2i", "prompt": "Bông hoa", "count": 1, "refs": []}])
    jid = db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,))[0]["id"]
    db.set_flow_receipt(jid, {"account_id": gone, "project": feng.proj, "seen": [], "at": time.time(),
                              "kind": "image", "want": 1, "state": "sent", "tries": 0})
    feng.start_page("flow_image", a1, 1, (0, 0))
    rows = _wait(db, bid, 90)
    assert rows[0]["status"] == "done" and rows[0]["account_id"] == a1, (rows[0]["status"], rows[0]["error_text"])
    assert len(_gens(feng, "flow_image")) == 1


def test_receive_gives_up_without_regenerating(db, feng, home, monkeypatch):
    """Đã gửi mà nhận mãi không được (quá số lần) → DỪNG tác vụ, báo link dự án để tải tay, KHÔNG tạo lại."""
    monkeypatch.setattr("videoai.core.engine.RECEIVE_MAX_TRIES", 1)
    a1 = db.add_account("flow", "g1", str(home / "pg1"))
    a2 = db.add_account("flow", "g2", str(home / "pg2"))
    bid = db.create_batch("flow", "flow_video", {"model": "Veo 3.1 - Fast", "ratio": "9:16 Dọc", "quality": "720p",
                                                  "timeout_s": 2}, str(home / "sr4"), "flat",
                          [{"mode": "t2v", "prompt": "NEVERME chú chó", "count": 1, "refs": []}])
    feng.start_page("flow_video", [a1, a2], 1, (0, 0))
    rows = _wait(db, bid, 120)
    r = rows[0]
    assert r["status"] == "failed" and "tải tay" in (r["error_text"] or ""), (r["status"], r["error_text"])
    assert feng.proj.split("?")[0] in r["error_text"]
    assert len(_gens(feng, "flow_video")) == 1                 # không tạo lại ở tài khoản thứ 2
    assert r["flow_sent"] is None


def test_project_hold_helpers():
    flow_mod._HELD.clear()
    u = "https://flow.google.com/project/abc?x=1#t"
    flow_mod.hold_project(u, "j1")
    assert flow_mod.project_busy("https://flow.google.com/project/abc", "j2")
    assert not flow_mod.project_busy(u, "j1")
    flow_mod.release_project(u, "j1")
    assert not flow_mod.project_busy(u, "j2")
    assert flow_mod.project_key("https://flow.google.com/") == ""


def test_db_migration_adds_flow_sent(tmp_path):
    import sqlite3
    from videoai.core.db import Database
    p = tmp_path / "old.db"
    Database(p)
    c = sqlite3.connect(p)                         # giả lập cơ sở dữ liệu của bản cũ (chưa có cột flow_sent)
    c.execute("ALTER TABLE jobs DROP COLUMN flow_sent")
    c.commit()
    c.close()
    Database(p)
    cols = {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(jobs)")}
    assert "flow_sent" in cols
