"""v2.2.4: chia tải — khi nhiều tài khoản cùng rảnh, ưu tiên tài khoản đã tạo ÍT video nhất trong ngày
(các tài khoản mòn đều, không vắt kiệt một cái rồi cháy trước)."""
from videoai.core.db import now
from videoai.core.engine import Engine, PageRun


def _done(db, aid, n):
    bid = db.create_batch("flow", "flow_video", {}, "/tmp/o", "flat",
                          [{"mode": "t2v", "prompt": f"p{i}", "count": 1} for i in range(n)])
    for j in db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,)):
        db.update_job(j["id"], status="done", account_id=aid, finished_at=now())


def test_prefers_least_used_today(db):
    eng = Engine(db)
    try:
        a1 = db.add_account("flow", "g1", "/tmp/p1")   # đã tạo 4 video hôm nay
        a2 = db.add_account("flow", "g2", "/tmp/p2")   # chưa tạo
        _done(db, a1, 4)
        r = PageRun("flow_video", [a1, a2], 1, (0, 0))
        free = {a1: 1, a2: 1}
        today = {a1: eng.daily_done(a1), a2: eng.daily_done(a2)}
        pick = min([a1, a2], key=lambda a: eng._dispatch_rank(a, set(), free, r, today))
        assert pick == a2                               # a2 ít dùng hơn → được chọn dù đứng sau
        # khi hoà nhau thì theo thứ tự khai báo
        _done(db, a2, 4)
        today = {a1: eng.daily_done(a1), a2: eng.daily_done(a2)}
        pick = min([a1, a2], key=lambda a: eng._dispatch_rank(a, set(), free, r, today))
        assert pick == a1
    finally:
        eng.shutdown()


def test_busy_beats_daily_count(db):
    eng = Engine(db)
    try:
        a1 = db.add_account("flow", "g1", "/tmp/p1")
        a2 = db.add_account("flow", "g2", "/tmp/p2")
        _done(db, a1, 0)
        r = PageRun("flow_video", [a1, a2], 2, (0, 0))
        free = {a1: 1, a2: 2}                            # a1 đang bận 1 slot, a2 rảnh hoàn toàn
        today = {a1: 0, a2: 9}
        pick = min([a1, a2], key=lambda a: eng._dispatch_rank(a, set(), free, r, today))
        assert pick == a2                               # rảnh hơn vẫn ưu tiên trước số lượng ngày
    finally:
        eng.shutdown()
