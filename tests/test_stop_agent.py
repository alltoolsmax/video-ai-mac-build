"""v2.2.7 – Dừng là dừng hẳn: bấm Dừng / đóng popup / tự đóng trình duyệt / Chat GPT đòi xác minh mà chưa xác minh
→ AI Agent và hàng tác vụ KHÔNG gửi thêm lệnh nào, không tự mở lại trình duyệt, không chuyển tài khoản khác."""
import asyncio as aio
import threading
import time
from concurrent.futures import Future

import pytest

from videoai.core.errors import JobError
from videoai.services import llm


class FakeBrowser:
    def __init__(self):
        self.closed = set()

    def closed_by_user(self, aid, within=600):
        return aid in self.closed


class FakeEngine:
    """ask_ai trả Future; mỗi lần gọi ghi lại tài khoản để kiểm tra có gửi tiếp hay không."""
    def __init__(self, behave):
        self.calls = []
        self.browser = FakeBrowser()
        self.behave = behave

    def ask_ai(self, acc, *a, **k):
        self.calls.append(acc["id"])
        f = Future()
        self.behave(self, acc, f)
        return f


@pytest.fixture()
def gpt2(db, home):
    ids = []
    for n in ("g1", "g2", "g3"):
        aid = db.add_account("gpt", n, str(home / n))
        db.update_account(aid, status="ok")
        ids.append(aid)
    llm._bad.clear()
    llm.begin()
    yield ids
    llm.begin()


def test_verification_not_done_stops_everything(db, gpt2):
    def behave(eng, acc, f):
        f.set_exception(JobError("needs_user", "Chưa xác minh trong 5 phút"))
    eng = FakeEngine(behave)
    with pytest.raises(llm.Cancelled) as e:
        llm.ask(db, eng, "s", "u")
    assert len(eng.calls) == 1                         # KHÔNG thử tài khoản Chat GPT khác
    assert "xác minh" in str(e.value)
    with pytest.raises(llm.Cancelled):                 # lượt sau (vd. phần kịch bản tiếp theo) cũng không gửi
        llm.ask(db, eng, "s", "u2")
    assert len(eng.calls) == 1
    llm.begin()                                         # người dùng bấm chạy lại → gửi được
    eng.behave = lambda e_, a, f: f.set_result("OK")
    assert llm.ask(db, eng, "s", "u3") == "OK"


def test_user_closed_browser_stops(db, gpt2):
    def behave(eng, acc, f):
        eng.browser.closed.add(acc["id"])
        f.set_exception(RuntimeError("Target page, context or browser has been closed"))
    eng = FakeEngine(behave)
    with pytest.raises(llm.Cancelled) as e:
        llm.ask(db, eng, "s", "u")
    assert len(eng.calls) == 1 and "đóng trình duyệt" in str(e.value)


def test_cancel_while_waiting_cancels_request(db, gpt2):
    futs = []
    eng = FakeEngine(lambda e_, a, f: futs.append(f))  # không bao giờ trả lời
    threading.Timer(1.0, lambda: llm.cancel("Đã đóng Quy trình tự động")).start()
    t = time.time()
    with pytest.raises(llm.Cancelled):
        llm.ask(db, eng, "s", "u", timeout_s=240)
    assert time.time() - t < 5                          # dừng ngay, không chờ hết 240 giây
    assert futs[0].cancelled()                          # yêu cầu đang chạy bị hủy (tab Chat GPT được đóng)
    assert len(eng.calls) == 1


def test_fix_prompts_stops_after_cancel(db, gpt2):
    n = {"c": 0}

    def behave(eng, acc, f):
        n["c"] += 1
        f.set_exception(JobError("needs_user", "x"))
    eng = FakeEngine(behave)
    with pytest.raises(llm.Cancelled):
        llm.fix_prompts(db, [f"p{i}" for i in range(60)], eng)   # 3 nhóm + sửa lẻ: dừng sau lần đầu
    assert n["c"] == 1


def test_other_errors_still_failover(db, gpt2):
    """Lỗi thường (không phải xác minh / đóng trình duyệt) vẫn chuyển tài khoản như cũ."""
    def behave(eng, acc, f):
        if len(eng.calls) == 1:
            f.set_exception(JobError("timeout", "chậm"))
        else:
            f.set_result("xong")
    eng = FakeEngine(behave)
    assert llm.ask(db, eng, "s", "u") == "xong"
    assert len(eng.calls) == 2


def test_engine_user_closes_browser_stops_page(db, qapp, mock_site, home):
    """Đang tạo video trên Flow mà người dùng tự đóng trình duyệt → dừng trang, không chuyển sang tài khoản khác."""
    from videoai.core.engine import Engine
    proj = mock_site.replace("index.html", "project/index.html")
    db.set_setting("platform_urls", {"flow_image": proj, "flow_video": proj})
    db.set_setting("flow_rights_ok", True)
    eng = Engine(db)
    try:
        a1 = db.add_account("flow", "c1", str(home / "pc1"))
        a2 = db.add_account("flow", "c2", str(home / "pc2"))
        bid = db.create_batch("flow", "flow_video", {"model": "Veo 3.1 - Fast", "ratio": "9:16 Dọc", "quality": "720p"},
                              str(home / "oc"), "flat",
                              [{"mode": "t2v", "prompt": f"NEVERME cảnh {i}", "count": 1, "refs": []} for i in range(3)])
        eng.start_page("flow_video", [a1, a2], 1, (0, 0))
        t = time.time()
        while time.time() - t < 60:                     # chờ tác vụ đầu đang chạy trên 1 tài khoản
            run = db.query("SELECT account_id FROM jobs WHERE batch_id=? AND status='running'", (bid,))
            if run and run[0]["account_id"]:
                break
            time.sleep(0.5)
        aid = run[0]["account_id"]
        time.sleep(4)                                   # đã bấm Tạo trên Flow
        ctx = eng.browser._contexts[aid]
        aio.run_coroutine_threadsafe(ctx.close(), eng.loop).result(20)   # NGƯỜI DÙNG đóng trình duyệt (không qua tools)
        t = time.time()
        while time.time() - t < 30:
            rows = db.query("SELECT status FROM jobs WHERE batch_id=?", (bid,))
            if all(r["status"] == "cancelled" for r in rows):
                break
            time.sleep(0.5)
        assert [r["status"] for r in rows] == ["cancelled"] * 3, rows
        other = a2 if aid == a1 else a1
        time.sleep(3)
        assert other not in eng.browser._contexts or not db.query(
            "SELECT 1 FROM jobs WHERE batch_id=? AND account_id=? AND status='running'", (bid, other))
        assert aid not in eng.browser._contexts         # KHÔNG tự mở lại trình duyệt vừa bị đóng
    finally:
        eng.shutdown()


def test_old_stop_expires_and_stop_button_only_when_running(db, gpt2, monkeypatch):
    """Dừng từ lâu không chặn lượt AI mới; nút Dừng trang tạo không đụng AI Agent khi AI không chạy."""
    eng = FakeEngine(lambda e_, a, f: f.set_result("OK"))
    llm.cancel("x", only_if_running=True)              # AI không chạy → không dừng gì
    assert not llm.stopped()
    llm.cancel("y")
    monkeypatch.setattr(llm, "_touch", llm._touch - llm.STALE_S - 1)
    assert llm.ask(db, eng, "s", "u") == "OK"          # dừng đã cũ → lượt mới chạy bình thường
