"""v2.2.3: giới hạn số video/ngày mỗi tài khoản (mặc định 50) — đủ ngưỡng thì tạm dừng tài khoản tới hôm sau."""
from videoai.core.db import now
from videoai.core.engine import Engine, PageRun


def _done_jobs(db, aid, n, when=None):
    bid = db.create_batch("flow", "flow_video", {}, "/tmp/o", "flat",
                          [{"mode": "t2v", "prompt": f"p{i}", "count": 1} for i in range(n)])
    for j in db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,)):
        db.update_job(j["id"], status="done", account_id=aid, finished_at=when or now())


def test_daily_done_counts_today(db):
    eng = Engine(db)
    try:
        aid = db.add_account("flow", "g1", "/tmp/p1")
        _done_jobs(db, aid, 3)
        _done_jobs(db, aid, 2, when="2020-01-01T00:00:00.000000Z")   # hôm khác: không tính
        assert eng.daily_done(aid) == 3
    finally:
        eng.shutdown()


def test_cap_pauses_account_then_resumes_next_day(db):
    eng = Engine(db)
    eng.daily_cap = 5
    try:
        aid = db.add_account("flow", "g1", "/tmp/p1")
        r = PageRun("flow_video", [aid], 1, (0, 0))
        eng.runs["flow_video"] = r
        _done_jobs(db, aid, 5)                 # đủ ngưỡng
        eng._apply_daily_cap(r)
        assert r.down.get(aid) == "capped" and aid not in r.usable()
        # giả lập sang ngày mới: các job hôm nay thành hôm qua → đếm = 0
        db.execute("UPDATE jobs SET finished_at='2020-01-01T00:00:00.000000Z' WHERE account_id=?", (aid,))
        eng._apply_daily_cap(r)
        assert aid not in r.down and aid in r.usable()
    finally:
        eng.shutdown()


def test_cap_zero_means_unlimited(db):
    eng = Engine(db)
    eng.daily_cap = 0
    try:
        aid = db.add_account("flow", "g1", "/tmp/p1")
        r = PageRun("flow_video", [aid], 1, (0, 0))
        _done_jobs(db, aid, 100)
        eng._apply_daily_cap(r)
        assert aid not in r.down
    finally:
        eng.shutdown()
