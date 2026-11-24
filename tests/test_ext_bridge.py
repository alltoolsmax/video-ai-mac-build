"""Kiểm thử kết nối hai chiều giữa Tiện ích Chrome và Tools (ExtBridge)."""
import json
import urllib.request

import pytest

from videoai.services.ext_bridge import ExtBridge


class _FakeEngine:
    def __init__(self):
        self.paused = False
        self.needs_user = False


@pytest.fixture
def bridge(db):
    from videoai.core import log
    log.setup()                      # bật handler phát log lên listener (như khi mở app)
    eng = _FakeEngine()
    b = ExtBridge(db, eng)
    b.start()
    yield b, eng
    b.stop()


def _get(b, path, token=None):
    url = f"{b.base_url}{path}"
    if token is not None:
        url += ("&" if "?" in path else "?") + "token=" + token
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, json.loads(r.read())


def _post(b, path, body, token):
    url = f"{b.base_url}{path}?token={token}"
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_ping_no_token(bridge):
    b, _ = bridge
    code, d = _get(b, "/ext/ping")
    assert code == 200 and d["ok"] and d["app"] == "VideoAI-MrHuynh"


def test_status_requires_token(bridge):
    b, _ = bridge
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(b, "/ext/status", token="sai")
    assert e.value.code == 401


def test_status_counts_and_flow(bridge, db):
    b, _ = bridge
    aid = db.add_account("flow", "g1", "/tmp/p1")
    db.update_account(aid, status="ok")
    bid = db.create_batch("flow", "flow_video", {}, "/tmp/out", "flat",
                          [{"mode": "t2v", "prompt": "a", "count": 1}, {"mode": "t2v", "prompt": "b", "count": 1}])
    jobs = db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,))
    db.update_job(jobs[0]["id"], status="done")
    db.update_job(jobs[1]["id"], status="failed")
    code, st = _get(b, "/ext/status", token=b.token)
    assert code == 200
    assert st["flow_logged_in"] == 1
    assert st["counts"]["done"] == 1 and st["counts"]["failed"] == 1
    assert st["version"] and "app" in st


def test_pause_resume_two_way(bridge):
    b, eng = bridge
    assert not eng.paused
    _, r = _post(b, "/ext/command", {"action": "pause"}, b.token)
    assert r["ok"] and r["paused"] and eng.paused is True
    _, st = _get(b, "/ext/status", token=b.token)
    assert st["paused"] is True
    _, r = _post(b, "/ext/command", {"action": "resume"}, b.token)
    assert eng.paused is False
    _, st = _get(b, "/ext/status", token=b.token)
    assert st["paused"] is False


def test_recaptcha_from_engine_and_content(bridge):
    b, eng = bridge
    _, st = _get(b, "/ext/status", token=b.token)
    assert st["recaptcha"] is False
    eng.needs_user = True                      # engine phát hiện cần xác minh
    _, st = _get(b, "/ext/status", token=b.token)
    assert st["recaptcha"] is True
    eng.needs_user = False
    _post(b, "/ext/flow", {"logged_in": True, "recaptcha": True, "url": "https://flow.google.com/"}, b.token)
    _, st = _get(b, "/ext/status", token=b.token)   # content.js báo → còn hiệu lực vài giây
    assert st["recaptcha"] is True


def test_onboarded_callback_and_page(bridge):
    b, _ = bridge
    fired = []
    b.on_onboarded = lambda: fired.append(1)
    _post(b, "/ext/onboarded", {"ok": True}, b.token)
    assert fired == [1]
    code, html = b.port, b._onboard_html()
    assert "Trợ lý Chrome" in html and b.token in html and b.base_url in html


def test_logs_flow_through(bridge):
    b, _ = bridge
    from videoai.core import log
    log.get("test").warning("một cảnh báo thử")
    _, st = _get(b, "/ext/status", token=b.token)
    assert any(x["msg"] == "một cảnh báo thử" and x["level"] == "warn" for x in st["logs"])
