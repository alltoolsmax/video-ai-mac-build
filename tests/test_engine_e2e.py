"""Kiểm thử đầu-cuối vòng lõi (F01) trên trang AI giả lập chạy ở máy cục bộ (không chạm nền tảng thật)."""
import time
from pathlib import Path

import pytest


def _wait(db, bid, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        rows = db.query("SELECT * FROM jobs WHERE batch_id=? ORDER BY row_no", (bid,))
        if rows and all(r["status"] in ("done", "failed", "blocked", "cancelled") for r in rows):
            return rows
        time.sleep(0.5)
    raise AssertionError("hết thời gian: " + str([(r["row_no"], r["status"]) for r in rows]))


@pytest.fixture()
def engine(db, qapp, mock_site, home):
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"grok": mock_site})
    eng = Engine(db)
    yield eng
    eng.shutdown()


def test_bulk_images_end_to_end(db, engine, home):
    aid = db.add_account("grok", "test", str(home / "prof"))
    ref = home / "ref.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", str(ref)])
    out = home / "out"
    bid = db.create_batch("grok", "grok", {"model": "Nano Banana Pro"}, str(out), "per_task", [
        {"mode": "t2i", "prompt": "Phở bò Hà Nội", "count": 2},
        {"mode": "i2i", "prompt": "Mèo con", "count": 1, "refs": [str(ref)]},
        {"mode": "t2i", "prompt": "BLOCKME xin lỗi", "count": 1},
    ])
    engine.start_page("grok", aid, 2, (0, 0))
    rows = _wait(db, bid, 90)
    assert [r["status"] for r in rows] == ["done", "done", "blocked"], [(r["status"], r["error_text"]) for r in rows]
    o1 = db.outputs(rows[0]["id"])
    assert len(o1) == 2 and all(Path(o["path"]).suffix == ".png" for o in o1)
    assert Path(o1[0]["path"]).parent.name.startswith("001_pho_bo_ha_noi")
    assert len(db.outputs(rows[1]["id"])) == 1
    assert rows[2]["error_code"] == "blocked"
    st = db.query("SELECT * FROM stats_daily")
    assert st[0]["done"] == 2 and st[0]["failed"] == 1


def test_video_download(db, engine, home):
    aid = db.add_account("grok", "test2", str(home / "prof2"))
    bid = db.create_batch("grok", "grok", {}, str(home / "vout"), "flat",
                          [{"mode": "t2v", "prompt": "VIDEO flycam", "count": 1}])
    engine.start_page("grok", aid, 1, (0, 0))
    rows = _wait(db, bid, 90)
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    o = db.outputs(rows[0]["id"])[0]
    assert o["kind"] == "video" and Path(o["path"]).stat().st_size > 10000


def test_missing_ref_and_no_account(db, engine, home):
    aid = db.add_account("grok", "t3", str(home / "prof3"))
    bid = db.create_batch("grok", "grok", {}, str(home / "x"), "flat",
                          [{"mode": "i2v", "prompt": "cần ảnh", "count": 1}])
    engine.start_page("grok", aid, 1, (0, 0))
    rows = _wait(db, bid, 30)
    assert rows[0]["status"] == "failed" and rows[0]["error_code"] == "ref_missing"


def test_stop_cancels_queue(db, engine, home):
    aid = db.add_account("grok", "t4", str(home / "prof4"))
    bid = db.create_batch("grok", "grok", {}, str(home / "y"), "flat",
                          [{"mode": "t2i", "prompt": f"p{i}", "count": 1} for i in range(5)])
    engine.start_page("grok", aid, 1, (3, 3))
    time.sleep(4)
    engine.stop_page("grok")
    time.sleep(1.5)
    rows = db.query("SELECT status FROM jobs WHERE batch_id=?", (bid,))
    assert sum(r["status"] == "cancelled" for r in rows) >= 3
    assert not any(r["status"] in ("queued", "running") for r in rows)


def test_check_account(db, engine, home, mock_site):
    aid = db.add_account("grok", "t5", str(home / "prof5"))
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    engine.check_account(acc, mock_site)
    t = time.time()
    while time.time() - t < 30:
        a = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
        if a["status"] != "unknown":
            break
        time.sleep(0.5)
    assert a["status"] == "ok"


# ---------------- Google Flow (trang giả lập theo cấu trúc giao diện thật) ----------------
@pytest.fixture()
def flow_engine(db, qapp, mock_site, home):
    from videoai.core.engine import Engine
    proj = mock_site.replace("index.html", "project/index.html")
    db.set_setting("platform_urls", {"flow_image": proj, "flow_video": proj})
    eng = Engine(db)
    yield eng
    eng.shutdown()


def test_flow_image_options_and_download(db, flow_engine, home):
    aid = db.add_account("flow", "f1", str(home / "pf1"))
    ref = home / "ref.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", str(ref)])
    bid = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "ratio": "9:16 Dọc"}, str(home / "fo"), "flat", [
        {"mode": "t2i", "prompt": "Quả táo đỏ", "count": 2},
        {"mode": "i2i", "prompt": "Mèo con", "count": 1, "refs": [str(ref)]},
        {"mode": "t2i", "prompt": "BLOCKME", "count": 1},
    ])
    flow_engine.start_page("flow_image", aid, 1, (0, 0))
    rows = _wait(db, bid, 120)
    assert [r["status"] for r in rows] == ["done", "done", "blocked"], [(r["status"], r["error_text"]) for r in rows]
    o = db.outputs(rows[0]["id"])
    assert len(o) == 2 and all(Path(x["path"]).suffix == ".png" and Path(x["path"]).stat().st_size > 5000 for x in o)
    assert len(db.outputs(rows[1]["id"])) == 1


def test_flow_video_frames(db, flow_engine, home):
    aid = db.add_account("flow", "f2", str(home / "pf2"))
    start = home / "s.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(start)])
    bid = db.create_batch("flow", "flow_video", {"model": "Veo 3.1 - Fast", "ratio": "9:16 Dọc", "resolutions": "720p",
                                                  "durations": "8 giây"}, str(home / "fv"), "flat",
                          [{"mode": "i2v", "prompt": "Cô gái quay lại mỉm cười", "count": 1, "refs": [str(start)]}])
    flow_engine.start_page("flow_video", aid, 1, (0, 0))
    rows = _wait(db, bid, 120)
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    o = db.outputs(rows[0]["id"])[0]
    assert o["kind"] == "video" and o["path"].endswith(".mp4") and Path(o["path"]).stat().st_size > 10000


def test_login_session_auto_detect_and_close(db, engine, home, mock_site):
    """Mở Chrome thường để đăng nhập → thấy đã đăng nhập → tự đóng → trạng thái ok; sau đó chạy tác vụ ẩn."""
    aid = db.add_account("grok", "login", str(home / "plogin"))
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    engine.open_login(acc, mock_site)
    t = time.time()
    while time.time() - t < 40:
        a = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
        if a["status"] == "ok":
            break
        time.sleep(0.5)
    assert a["status"] == "ok"
    assert not engine.browser._logins          # cửa sổ đăng nhập đã đóng
    bid = db.create_batch("grok", "grok", {}, str(home / "lo"), "flat", [{"mode": "t2i", "prompt": "sau đăng nhập", "count": 1}])
    engine.start_page("grok", aid, 1, (0, 0))
    rows = _wait(db, bid, 60)
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    assert engine.browser_hidden(aid) is True
