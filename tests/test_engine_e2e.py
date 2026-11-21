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
    db.set_setting("platform_urls", {"grok_image": mock_site, "grok_video": mock_site})
    eng = Engine(db)
    yield eng
    eng.shutdown()


def test_bulk_images_end_to_end(db, engine, home):
    aid = db.add_account("grok", "test", str(home / "prof"))
    ref = home / "ref.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", str(ref)])
    out = home / "out"
    bid = db.create_batch("grok", "grok_image", {"model": "Nano Banana Pro"}, str(out), "per_task", [
        {"mode": "t2i", "prompt": "Phở bò Hà Nội", "count": 2},
        {"mode": "i2i", "prompt": "Mèo con", "count": 1, "refs": [str(ref)]},
        {"mode": "t2i", "prompt": "BLOCKME xin lỗi", "count": 1},
    ])
    engine.start_page("grok_image", aid, 2, (0, 0))
    rows = _wait(db, bid, 90)
    assert [r["status"] for r in rows] == ["done", "done", "blocked"], [(r["status"], r["error_text"]) for r in rows]
    o1 = db.outputs(rows[0]["id"])
    assert len(o1) == 2 and all(Path(o["path"]).suffix == ".jpg" for o in o1)
    assert Path(o1[0]["path"]).parent.name.startswith("001_pho_bo_ha_noi")
    assert len(db.outputs(rows[1]["id"])) == 1
    assert rows[2]["error_code"] == "blocked"
    st = db.query("SELECT * FROM stats_daily")
    assert st[0]["done"] == 2 and st[0]["failed"] == 1


def test_video_download(db, engine, home):
    aid = db.add_account("grok", "test2", str(home / "prof2"))
    bid = db.create_batch("grok", "grok_image", {}, str(home / "vout"), "flat",
                          [{"mode": "t2v", "prompt": "VIDEO flycam", "count": 1}])
    engine.start_page("grok_image", aid, 1, (0, 0))
    rows = _wait(db, bid, 90)
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    o = db.outputs(rows[0]["id"])[0]
    assert o["kind"] == "video" and Path(o["path"]).stat().st_size > 10000


def test_missing_ref_and_no_account(db, engine, home):
    aid = db.add_account("grok", "t3", str(home / "prof3"))
    bid = db.create_batch("grok", "grok_video", {}, str(home / "x"), "flat",
                          [{"mode": "i2v", "prompt": "cần ảnh", "count": 1}])
    engine.start_page("grok_video", aid, 1, (0, 0))
    rows = _wait(db, bid, 30)
    assert rows[0]["status"] == "failed" and rows[0]["error_code"] == "ref_missing"


def test_stop_cancels_queue(db, engine, home):
    aid = db.add_account("grok", "t4", str(home / "prof4"))
    bid = db.create_batch("grok", "grok_image", {}, str(home / "y"), "flat",
                          [{"mode": "t2i", "prompt": f"p{i}", "count": 1} for i in range(5)])
    engine.start_page("grok_image", aid, 1, (3, 3))
    time.sleep(4)
    engine.stop_page("grok_image")
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
    db.set_setting("flow_rights_ok", True)       # mặc định: người dùng đã xác nhận quyền sử dụng tệp tải lên
    eng = Engine(db)
    yield eng
    eng.shutdown()


def test_flow_image_options_and_download(db, flow_engine, home):
    aid = db.add_account("flow", "f1", str(home / "pf1"))
    ref = home / "ref.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", str(ref)])
    bid = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "ratio": "9:16 Dọc", "quality": "2K"}, str(home / "fo"), "flat", [
        {"mode": "t2i", "prompt": "Quả táo đỏ", "count": 2},
        {"mode": "i2i", "prompt": "Mèo con", "count": 1, "refs": [str(ref)]},
        {"mode": "t2i", "prompt": "BLOCKME", "count": 1},
        {"mode": "t2i", "prompt": "BLOCKME lần 2", "count": 1},      # ô lỗi trùng nội dung với ô lỗi cũ vẫn nhận ra
    ])
    flow_engine.start_page("flow_image", aid, 1, (0, 0))
    rows = _wait(db, bid, 160)
    assert [r["status"] for r in rows] == ["done", "done", "blocked", "blocked"], [(r["status"], r["error_text"]) for r in rows]
    o = db.outputs(rows[0]["id"])
    assert len(o) == 2 and all(Path(x["path"]).suffix == ".jpg" and Path(x["path"]).stat().st_size > 5000 for x in o)
    from PySide6.QtGui import QImage
    im = QImage(o[0]["path"])
    assert im.height() > im.width(), "ảnh phải đúng tỷ lệ 9:16 đã chọn"      # lần bấm cài đặt đầu bị lỡ vẫn đặt đúng
    assert len(db.outputs(rows[1]["id"])) == 1
    import asyncio as aio
    tab = next(iter(flow_engine.runs["flow_image"].tabs.values()))[0]
    got = aio.run_coroutine_threadsafe(tab.evaluate("window.downloads"), flow_engine.loop).result(10)
    assert got and all(x.startswith("2K") for x in got)          # tải đúng chất lượng đã chọn


def test_flow_video_frames(db, flow_engine, home):
    aid = db.add_account("flow", "f2", str(home / "pf2"))
    start = home / "s.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(start)])
    bid = db.create_batch("flow", "flow_video", {"model": "Veo 3.1 - Fast", "ratio": "9:16 Dọc", "resolutions": "720p",
                                                  "durations": "8 giây", "quality": "1080p"}, str(home / "fv"), "flat",
                          [{"mode": "i2v", "prompt": "Cô gái quay lại mỉm cười", "count": 1, "refs": [str(start)]},
                           # hàng 2: ô "Bắt đầu" vẫn còn ảnh của hàng 1 → phải bỏ ảnh cũ rồi đặt khung đầu + khung cuối
                           {"mode": "i2v", "prompt": "Chuyển cảnh", "count": 1, "refs": [str(start), str(start)]}])
    flow_engine.start_page("flow_video", aid, 1, (0, 0))
    rows = _wait(db, bid, 180)
    assert [r["status"] for r in rows] == ["done", "done"], [(r["status"], r["error_text"]) for r in rows]
    import asyncio as aio
    tab = next(iter(flow_engine.runs["flow_video"].tabs.values()))[0]
    st = aio.run_coroutine_threadsafe(tab.evaluate("[S.start, S.end]"), flow_engine.loop).result(10)
    assert st[0] and st[1] and st[0] != st[1]          # khung đầu và khung cuối là 2 ảnh tải lên ở hàng 2
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
    bid = db.create_batch("grok", "grok_image", {}, str(home / "lo"), "flat", [{"mode": "t2i", "prompt": "sau đăng nhập", "count": 1}])
    engine.start_page("grok_image", aid, 1, (0, 0))
    rows = _wait(db, bid, 60)
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    assert engine.browser_hidden(aid) is True


def _set_no_credit(engine, db, aid, url):
    import asyncio as aio
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))

    async def go():
        pg = await engine.browser.new_page(acc, url)
        await pg.evaluate("localStorage.setItem('noCredit','1')")
        await pg.close()
    aio.run_coroutine_threadsafe(go(), engine.loop).result(60)


def test_multi_account_parallel(db, engine, home):
    a1 = db.add_account("grok", "tk1", str(home / "m1"))
    a2 = db.add_account("grok", "tk2", str(home / "m2"))
    bid = db.create_batch("grok", "grok_image", {}, str(home / "mo"), "flat",
                          [{"mode": "t2i", "prompt": f"anh {c}", "count": 1} for c in "abcd"])
    engine.start_page("grok_image", [a1, a2], 1, (0, 0))
    rows = _wait(db, bid, 90)
    assert all(r["status"] == "done" for r in rows), [(r["status"], r["error_text"]) for r in rows]
    used = {r["account_id"] for r in rows}
    assert used == {a1, a2}


def test_failover_when_out_of_credit(db, engine, home, mock_site):
    a1 = db.add_account("grok", "het_tien", str(home / "f1"))
    a2 = db.add_account("grok", "con_tien", str(home / "f2"))
    _set_no_credit(engine, db, a1, mock_site)
    bid = db.create_batch("grok", "grok_image", {}, str(home / "fo2"), "flat",
                          [{"mode": "t2i", "prompt": f"p {c}", "count": 1} for c in "abc"] +
                          [{"mode": "t2i", "prompt": "BLOCKME", "count": 1}])
    engine.start_page("grok_image", [a1, a2], 1, (0, 0), True)
    rows = _wait(db, bid, 120)
    st = [r["status"] for r in rows]
    assert st[:3] == ["done"] * 3, [(r["status"], r["error_text"]) for r in rows]
    assert all(r["account_id"] == a2 for r in rows[:3])
    assert st[3] == "blocked"                 # vi phạm nội dung: không chuyển tài khoản
    assert engine.runs["grok_image"].down.get(a1) == "quota"


def test_no_failover_pauses(db, engine, home, mock_site):
    a1 = db.add_account("grok", "only", str(home / "n1"))
    _set_no_credit(engine, db, a1, mock_site)
    bid = db.create_batch("grok", "grok_image", {}, str(home / "no"), "flat", [{"mode": "t2i", "prompt": "x", "count": 1}])
    engine.start_page("grok_image", [a1], 1, (0, 0), True)
    rows = _wait(db, bid, 60)
    assert rows[0]["status"] == "failed" and rows[0]["error_code"] == "quota"


def test_flow_video_compose_with_overlay(db, flow_engine, home):
    """Thành phần (ảnh tham chiếu): bảng cài đặt có lớp phủ, phải đóng được trước khi bấm nút '+'."""
    db.set_setting("flow_rights_ok", True)
    aid = db.add_account("flow", "f3", str(home / "pf3"))
    ref = home / "ing.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=green:s=64x64", "-frames:v", "1", str(ref)])
    bid = db.create_batch("flow", "flow_video", {"model": "Omni 1.2 Flash", "ratio": "16:9 Ngang", "resolutions": "720p",
                                                  "durations": "6 giây", "quality": "720p"}, str(home / "fc"), "flat",
                          [{"mode": "compose", "prompt": "Nhân vật đi dạo", "count": 1, "refs": [str(ref)]}])
    flow_engine.start_page("flow_video", aid, 1, (0, 0))
    rows = _wait(db, bid, 120)
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    outs = db.outputs(rows[0]["id"])
    assert len(outs) == 1 and outs[0]["kind"] == "video" and outs[0]["path"].endswith(".mp4")   # không lấy nhầm ô ảnh tải lên


def test_flow_one_task_per_account_across_pages(db, flow_engine, home):
    """2 tài khoản, chạy cùng lúc trang ảnh (3 tác vụ) và trang video (2 tác vụ):
    không lúc nào 1 tài khoản chạy 2 tác vụ; tài khoản rảnh nhận tác vụ kế tiếp; cả 2 tài khoản đều được dùng."""
    a1 = db.add_account("flow", "acc1", str(home / "q1"))
    a2 = db.add_account("flow", "acc2", str(home / "q2"))
    db.update_account(a1, status="ok")
    db.update_account(a2, status="ok")
    b1 = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "quality": "1K"}, str(home / "qa"), "flat",
                         [{"mode": "t2i", "prompt": f"ảnh {c}", "count": 1} for c in "abc"])
    b2 = db.create_batch("flow", "flow_video", {"model": "Omni 1.2 Flash", "quality": "720p", "durations": "6 giây"},
                         str(home / "qb"), "flat", [{"mode": "t2v", "prompt": f"video {c}", "count": 1} for c in "xy"])
    flow_engine.start_page("flow_image", [a1], 1, (0, 0))      # chỉ truyền 1 tài khoản: phần mềm tự lấy thêm tk sẵn sàng
    flow_engine.start_page("flow_video", [a1], 1, (0, 0))
    worst, t0 = 0, time.time()
    while time.time() - t0 < 240:
        run = db.query("SELECT account_id, COUNT(*) n FROM jobs WHERE status='running' GROUP BY account_id")
        worst = max([worst] + [r["n"] for r in run])
        rows = db.query("SELECT * FROM jobs WHERE batch_id IN (?,?)", (b1, b2))
        if all(r["status"] in ("done", "failed", "blocked", "cancelled") for r in rows):
            break
        time.sleep(0.15)
    assert worst == 1, f"có tài khoản chạy {worst} tác vụ cùng lúc"
    assert all(r["status"] == "done" for r in rows), [(r["status"], r["error_text"]) for r in rows]
    assert {r["account_id"] for r in rows} == {a1, a2}


def test_free_tier_engine_runs_one_at_a_time(db, flow_engine, home):
    a1 = db.add_account("flow", "fr1", str(home / "fr1"))
    a2 = db.add_account("flow", "fr2", str(home / "fr2"))
    db.update_account(a1, status="ok")
    db.update_account(a2, status="ok")
    flow_engine.max_total = 1
    b = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "quality": "1K"}, str(home / "fr"), "flat",
                        [{"mode": "t2i", "prompt": f"x {c}", "count": 1} for c in "ab"])
    flow_engine.start_page("flow_image", [a1, a2], 1, (0, 0))
    worst, t0 = 0, time.time()
    while time.time() - t0 < 120:
        n = db.one("SELECT COUNT(*) n FROM jobs WHERE status='running'")["n"]
        worst = max(worst, n)
        rows = db.query("SELECT * FROM jobs WHERE batch_id=?", (b,))
        if all(r["status"] in ("done", "failed", "blocked") for r in rows):
            break
        time.sleep(0.1)
    assert worst == 1 and all(r["status"] == "done" for r in rows), [(r["status"], r["error_text"]) for r in rows]


def test_batch_one_task_per_account_with_rest(db, flow_engine, home):
    """5 tác vụ, 3 tài khoản: chạy cùng lúc 3 tác vụ (mỗi tài khoản 1); tài khoản xong thì nghỉ rồi mới nhận tác vụ kế."""
    from datetime import datetime
    ids = []
    for i in range(3):
        a = db.add_account("flow", f"acc{i}", str(home / f"rest{i}"))
        db.update_account(a, status="ok")
        ids.append(a)
    b = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "quality": "1K"}, str(home / "rest"), "flat",
                        [{"mode": "t2i", "prompt": f"cảnh {k}", "count": 1} for k in range(5)])
    REST = 3
    flow_engine.start_page("flow_image", [ids[0]], 1, (REST, REST))
    peak, t0 = 0, time.time()
    while time.time() - t0 < 240:
        peak = max(peak, db.one("SELECT COUNT(*) n FROM jobs WHERE status='running'")["n"])
        rows = db.query("SELECT * FROM jobs WHERE batch_id=?", (b,))
        if all(r["status"] in ("done", "failed", "blocked") for r in rows):
            break
        time.sleep(0.1)
    assert all(r["status"] == "done" for r in rows), [(r["status"], r["error_text"]) for r in rows]
    assert peak == 3                                            # 3 tài khoản → đúng 3 tác vụ chạy cùng lúc
    ts = lambda s: datetime.fromisoformat(s).timestamp()
    by_acc = {}
    for r in rows:
        by_acc.setdefault(r["account_id"], []).append((ts(r["started_at"]), ts(r["finished_at"])))
    assert set(by_acc) == set(ids)
    for spans in by_acc.values():
        spans.sort()
        for (s1, f1), (s2, f2) in zip(spans, spans[1:]):
            assert s2 - f1 >= REST - 0.5, f"tài khoản nhận tác vụ kế sau {s2 - f1:.1f}s (phải nghỉ ≥ {REST}s)"


def test_flow_video_extend(db, flow_engine, home):
    """Kéo dài Video: tạo video từ cảnh đầu → mở trình chỉnh sửa → Kéo dài từng đoạn (đúng số giây) → tải video đã kéo dài."""
    aid = db.add_account("flow", "fx", str(home / "pfx"))
    bid = db.create_batch("flow", "flow_video", {"model": "Omni 1.2 Flash", "ratio": "16:9 Ngang", "resolutions": "720p",
                                                  "durations": "8 giây", "quality": "", "extend_secs": 6}, str(home / "fx"), "flat",
                          [{"mode": "extend", "prompt": "Cô gái ngồi uống trà || Cô đứng dậy || Cô đi vào nhà", "count": 1},
                           {"mode": "extend", "prompt": "Con mèo ngủ || BLOCKEXT nhảy lên", "count": 1}])
    flow_engine.start_page("flow_video", aid, 1, (0, 0))
    rows = _wait(db, bid, 200)
    assert [r["status"] for r in rows] == ["done", "blocked"], [(r["status"], r["error_text"]) for r in rows]
    import asyncio as aio
    tab = next(iter(flow_engine.runs["flow_video"].tabs.values()))[0]
    got = aio.run_coroutine_threadsafe(tab.evaluate("[window.lastPrompt, E.done, window.extDownloads, location.hash]"), flow_engine.loop).result(10)
    assert got[1][:2] == [{"prompt": "Cô đứng dậy", "secs": 6}, {"prompt": "Cô đi vào nhà", "secs": 6}], got
    assert got[2] == ["720p Kích thước gốc"] and "edit" not in got[3]      # tải bản gốc, rồi quay lại lưới
    o = db.outputs(rows[0]["id"])
    assert len(o) == 1 and o[0]["path"].endswith(".mp4") and Path(o[0]["path"]).stat().st_size > 10000


def test_gpt_image_end_to_end(db, qapp, mock_site, home):
    """Tạo ảnh GPT: nhập prompt (+ tỷ lệ trong prompt), gửi, chờ 'Creating image', lưu ảnh; ảnh tham chiếu; hết lượt / bị chặn."""
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"gpt_image": mock_site.replace("index.html", "gpt/index.html")})
    eng = Engine(db)
    try:
        aid = db.add_account("gpt", "g1", str(home / "pg1"))
        ref = home / "r.png"
        from videoai.media import ffmpeg
        ffmpeg.run(["-f", "lavfi", "-i", "color=c=green:s=64x64", "-frames:v", "1", str(ref)])
        bid = db.create_batch("gpt", "gpt_image", {"ratio": "16:9 Ngang"}, str(home / "go"), "flat", [
            {"mode": "t2i", "prompt": "Quả táo đỏ", "count": 1},
            {"mode": "i2i", "prompt": "Mèo con theo ảnh", "count": 1, "refs": [str(ref)]},
            {"mode": "t2i", "prompt": "BLOCKME", "count": 1},
            {"mode": "t2i", "prompt": "LIMITME", "count": 1}])
        eng.start_page("gpt_image", aid, 1, (0, 0))
        rows = _wait(db, bid, 160)
        st = [r["status"] for r in rows]
        assert st == ["done", "done", "blocked", "failed"] and rows[3]["error_code"] == "quota", \
            [(r["status"], r["error_text"]) for r in rows]
        o = db.outputs(rows[0]["id"])
        from PySide6.QtGui import QImage
        im = QImage(o[0]["path"])
        assert o[0]["path"].endswith(".jpg") and im.width() > im.height()      # 16:9 ghi vào prompt
        assert len(db.outputs(rows[1]["id"])) == 1
    finally:
        eng.shutdown()


def test_grok_image_end_to_end(db, qapp, mock_site, home):
    """Tạo ảnh Grok qua chat: tự đóng cookie, gửi 'Generate N images … Aspect ratio …', chỉ lấy ảnh SAU tin nhắn vừa gửi
    (không lấy ảnh mẫu của trang), đúng tỷ lệ; Grok từ chối → bị chặn."""
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"grok_image": mock_site.replace("index.html", "grok/index.html")})
    eng = Engine(db)
    try:
        aid = db.add_account("grok", "k1", str(home / "pk1"))
        bid = db.create_batch("grok", "grok_image", {"ratio": "16:9 Ngang"}, str(home / "ko"), "flat", [
            {"mode": "t2i", "prompt": "Mèo phi hành gia", "count": 2},
            {"mode": "t2i", "prompt": "BLOCKME", "count": 1}])
        eng.start_page("grok_image", aid, 1, (0, 0))
        rows = _wait(db, bid, 120)
        assert [r["status"] for r in rows] == ["done", "blocked"], [(r["status"], r["error_text"]) for r in rows]
        o = db.outputs(rows[0]["id"])
        from PySide6.QtGui import QImage
        sizes = [(QImage(x["path"]).width(), QImage(x["path"]).height()) for x in o]
        assert len(o) == 2 and all(s == (1280, 720) for s in sizes), sizes        # đúng 16:9, không lấy ảnh mẫu 768x432
    finally:
        eng.shutdown()

def test_muse_image_and_video_end_to_end(db, qapp, mock_site, home):
    """Muse (muse.ai): ảnh — xin đúng số ảnh + tỷ lệ, tải bản đầy đủ trong hộp xem, không lấy ảnh cũ; video — tải mp4;
    ảnh → video gửi kèm ảnh; Muse từ chối → bị chặn."""
    from videoai.core.engine import Engine
    url = mock_site.replace("index.html", "muse/index.html")
    db.set_setting("platform_urls", {"muse_image": url, "meta_muse": url})
    eng = Engine(db)
    try:
        aid = db.add_account("muse", "m1", str(home / "pm1"))
        ref = home / "r.png"
        from videoai.media import ffmpeg
        ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", str(ref)])
        b1 = db.create_batch("muse", "muse_image", {"ratio": "16:9 Ngang"}, str(home / "mi"), "flat", [
            {"mode": "t2i", "prompt": "Quả táo đỏ", "count": 2},
            {"mode": "t2i", "prompt": "BLOCKME", "count": 1}])
        eng.start_page("muse_image", aid, 1, (0, 0))
        rows = _wait(db, b1, 120)
        assert [r["status"] for r in rows] == ["done", "blocked"], [(r["status"], r["error_text"]) for r in rows]
        from PySide6.QtGui import QImage
        o = db.outputs(rows[0]["id"])
        assert len(o) == 2 and all(QImage(x["path"]).width() == 2048 for x in o)      # bản đầy đủ, không phải ảnh nhỏ
        b2 = db.create_batch("muse", "meta_muse", {"ratio": "9:16 Dọc"}, str(home / "mv"), "flat", [
            {"mode": "t2v", "prompt": "Mèo đi dạo", "count": 1},
            {"mode": "i2v", "prompt": "Cho ảnh chuyển động", "count": 1, "refs": [str(ref)]}])
        eng.start_page("meta_muse", aid, 1, (0, 0))
        rows = _wait(db, b2, 120)
        assert [r["status"] for r in rows] == ["done", "done"], [(r["status"], r["error_text"]) for r in rows]
        assert all(db.outputs(r["id"])[0]["path"].endswith(".mp4") for r in rows)
        import asyncio as aio
        tab = next(iter(eng.runs["meta_muse"].tabs.values()))[0]
        sent = aio.run_coroutine_threadsafe(tab.evaluate("[window.sent, window.attached]"), eng.loop).result(10)
        assert sent[0][-1].startswith("Animate the attached image into a video: Cho ảnh chuyển động") and "9:16" in sent[0][-1]
        assert sent[1] == 1
    finally:
        eng.shutdown()


def test_grok_video_end_to_end(db, qapp, mock_site, home):
    """Tạo Video Grok qua chat: gửi 'Generate a video … Aspect ratio 9:16 (portrait, vertical)', tải mp4 sau tin nhắn vừa gửi."""
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"grok_video": mock_site.replace("index.html", "grok/index.html")})
    eng = Engine(db)
    try:
        aid = db.add_account("grok", "k2", str(home / "pk2"))
        bid = db.create_batch("grok", "grok_video", {"ratio": "9:16 Dọc"}, str(home / "kv"), "flat",
                              [{"mode": "t2v", "prompt": "Mèo đi dạo", "count": 1}])
        eng.start_page("grok_video", aid, 1, (0, 0))
        rows = _wait(db, bid, 120)
        assert rows[0]["status"] == "done", (rows[0]["status"], rows[0]["error_text"])
        assert db.outputs(rows[0]["id"])[0]["path"].endswith(".mp4")
        import asyncio as aio
        tab = next(iter(eng.runs["grok_video"].tabs.values()))[0]
        sent = aio.run_coroutine_threadsafe(tab.evaluate("window.sent[0]"), eng.loop).result(10)
        assert sent.startswith("Generate a video: Mèo đi dạo") and "9:16 (portrait, vertical)" in sent, sent
    finally:
        eng.shutdown()

def test_dreamina_video_end_to_end(db, qapp, mock_site, home):
    """Dreamina: đóng quảng cáo, chọn model / tỷ lệ / độ phân giải / thời lượng, bấm Generate 2 lần (lần đầu chỉ mở phiên),
    đợi khối kết quả của đúng prompt, tải mp4; 'unusual activity' → dừng tài khoản (flagged)."""
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"dreamina": mock_site.replace("index.html", "dreamina/index.html")})
    eng = Engine(db)
    try:
        aid = db.add_account("dreamina", "d1", str(home / "pd1"))
        bid = db.create_batch("dreamina", "dreamina", {"model": "Dreamina Seedance 2.5 Flash", "ratio": "9:16 Dọc",
                                                       "quality": "1080P", "durations": "10 giây"}, str(home / "dv"), "flat",
                              [{"mode": "t2v", "prompt": "Mèo đi dạo trong vườn", "count": 1},
                               {"mode": "t2v", "prompt": "FLAGME chó chạy", "count": 1}])
        eng.start_page("dreamina", aid, 1, (0, 0))
        rows = _wait(db, bid, 150)
        assert rows[0]["status"] == "done", (rows[0]["status"], rows[0]["error_text"])
        assert rows[1]["error_code"] == "flagged", (rows[1]["status"], rows[1]["error_text"])
        assert db.outputs(rows[0]["id"])[0]["path"].endswith(".mp4")
        import asyncio as aio
        tab = next(iter(eng.runs["dreamina"].tabs.values()))[0]
        last = aio.run_coroutine_threadsafe(tab.evaluate("S.sent[S.sent.length - 1]"), eng.loop).result(10)
        assert (last["model"], last["ratio"], last["res"], last["secs"]) == ("Dreamina Seedance 2.5 Flash", "9:16", "1080P", 10), last
    finally:
        eng.shutdown()


def test_ai_agent_via_logged_in_account(db, qapp, mock_site, home):
    """AI Agent không cần API key: gửi yêu cầu vào khung chat của tài khoản đã đăng nhập và đọc câu trả lời."""
    from videoai.core.engine import Engine
    from videoai.services import llm
    db.set_setting("ai_chat_urls", {"gpt": mock_site.replace("index.html", "chat/index.html")})
    eng = Engine(db)
    try:
        aid = db.add_account("gpt", "g-ai", str(home / "pai"))
        db.update_account(aid, status="ok")
        assert llm.pick_account(db)["id"] == aid
        out = llm.fix_prompts(db, ["a red apple", "cat on sofa"], eng)
        assert out == ["Improved: a red apple", "Improved: cat on sofa"]
        story = llm.write_story(db, "chuyện chú mèo", 3, eng)
        assert story == ["Scene 1 of the story", "Scene 2 of the story", "Scene 3 of the story"]
        db.update_account(aid, status="expired")
        import pytest
        with pytest.raises(RuntimeError):
            llm.complete(db, "x", "y", eng)                   # không còn tài khoản đăng nhập → báo rõ
    finally:
        eng.shutdown()


def test_flow_lipsync_end_to_end(db, flow_engine, home, mock_site):
    """Copy Động Tác: cắt video gốc theo thời lượng, tỷ lệ theo video gốc (dọc → 9:16), tải video + ảnh lên làm thành phần,
    gửi prompt cố định, tải kết quả và ghép lại tiếng gốc."""
    from videoai.media import ffmpeg
    from videoai.adapters.lipsync_prompt import LIPSYNC_PROMPT
    db.set_setting("platform_urls", {"lipsync": mock_site.replace("index.html", "project/index.html")})
    db.set_setting("flow_rights_ok", True)          # người dùng đã đồng ý trong tools → tools bấm "Tôi đồng ý, không hiện lại"
    aid = db.add_account("flow", "fl", str(home / "pfl"))
    src = home / "goc.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc=size=360x640:rate=25", "-f", "lavfi", "-i", "sine=f=500", "-t", "12",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)])
    img = home / "nv.png"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=orange:s=200x260", "-frames:v", "1", str(img)])
    seen = {}
    from videoai.adapters import flow as F
    orig = F.FlowAdapter.run_and_save

    async def spy(self, page, job, refs, params, *a, **k):
        if job.get("mode") == "compose":
            seen.update(prompt=job["prompt"], ratio=params["ratio"], clip_dur=ffmpeg.duration(refs[0]), n_refs=len(refs))
        return await orig(self, page, job, refs, params, *a, **k)
    F.FlowAdapter.run_and_save = spy
    try:
        bid = db.create_batch("flow", "lipsync", {"ratio": "Theo video gốc", "quality": "720p", "lipsync_secs": 5,
                                                   "keep_audio": True, "model": "Omni 1.2 Flash", "resolutions": "720p"},
                              str(home / "ls"), "flat", [{"mode": "lipsync", "prompt": "goc + nv", "count": 1,
                                                          "refs": [str(src), str(img)]}])
        flow_engine.start_page("lipsync", aid, 1, (0, 0))
        rows = _wait(db, bid, 180)
    finally:
        F.FlowAdapter.run_and_save = orig
    assert rows[0]["status"] == "done", rows[0]["error_text"]
    assert seen["prompt"] == LIPSYNC_PROMPT and seen["ratio"] == "9:16" and seen["n_refs"] == 2
    assert abs(seen["clip_dur"] - 5) < 0.3                       # video gốc 12s → lấy 5s đầu
    out = db.outputs(rows[0]["id"])[0]["path"]
    assert out.endswith(".mp4") and ffmpeg.has_audio(out)         # đã ghép tiếng gốc



def test_flow_upload_rights_dialog_not_auto_accepted_without_consent(db, flow_engine, home):
    """Hộp "Quyền sử dụng video này" của Google: chưa đồng ý trong tools → không tự bấm, tác vụ báo lỗi rõ ràng."""
    db.set_setting("flow_rights_ok", False)
    aid = db.add_account("flow", "f9", str(home / "pf9"))
    ref = home / "r9.png"
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1", str(ref)])
    bid = db.create_batch("flow", "flow_video", {"model": "Omni 1.2 Flash", "ratio": "16:9 Ngang", "resolutions": "720p",
                                                  "durations": "6 giây", "quality": "720p"}, str(home / "f9o"), "flat",
                          [{"mode": "compose", "prompt": "đi dạo", "count": 1, "refs": [str(ref)]}])
    flow_engine.start_page("flow_video", aid, 1, (0, 0), False)
    rows = _wait(db, bid, 120)
    assert rows[0]["status"] == "failed" and "quyền sử dụng" in (rows[0]["error_text"] or "")


@pytest.mark.parametrize("mode", ["agent=1", "agentpanel=1", "agentstuck=1"])
def test_flow_agent_switch_turned_off(db, qapp, mock_site, home, mode):
    """Tác nhân Flow: công tắc bật / chế độ bảng bên (công tắc bị ẩn) → tools đóng bảng + tắt rồi tạo trực tiếp;
    không tắt được và Flow hỏi phê duyệt chi phí → bấm "Phê duyệt" (chỉ lần này, không "Luôn phê duyệt")."""
    from videoai.core.engine import Engine
    proj = mock_site.replace("index.html", "project/index.html") + "?" + mode
    db.set_setting("platform_urls", {"flow_image": proj})
    eng = Engine(db)
    try:
        aid = db.add_account("flow", "fa", str(home / f"pfa{mode[:6]}"))
        bid = db.create_batch("flow", "flow_image", {"model": "Nano Banana Pro", "quality": "1K"}, str(home / "fao"), "flat",
                              [{"mode": "t2i", "prompt": "quả táo", "count": 1}])
        eng.start_page("flow_image", aid, 1, (0, 0))
        rows = _wait(db, bid, 120)
        assert rows[0]["status"] == "done", rows[0]["error_text"]
    finally:
        eng.shutdown()
