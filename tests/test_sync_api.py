"""SYNC API (chạy cùng Video AI): kho API key ↔ cookie, khung nhập API Key khi thêm tài khoản, cửa sổ SYNC API,
API HTTP cho mọi nền tảng, ghim tác vụ vào tài khoản của key, và thứ tự AI Agent (API chính thức → tài khoản)."""
import base64
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from videoai.core.cookies import CookieError
from videoai.syncapi.store import SyncKeyError, SyncStore, looks_like_key

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
GROK = json.dumps([{"domain": ".grok.com", "name": "sso", "value": "S1", "expirationDate": 4_000_000_000}])
GROK2 = json.dumps([{"domain": ".grok.com", "name": "sso", "value": "S2", "expirationDate": 4_100_000_000}])
GPT = json.dumps([{"domain": ".chatgpt.com", "name": "__Secure-next-auth.session-token", "value": "T"}])
MUSE = "sid=abc; other=1"


class FakeEngine:
    """Ghi lại cookie được nạp; với API HTTP thì "chạy" tác vụ ngay: tạo tệp kết quả hoặc báo lỗi theo kịch bản."""

    def __init__(self, db, out: Path):
        self.db, self.out = db, out
        self.pasted, self.ensured, self.asked = [], [], []
        self.fail = None                   # (error_code, error_text) cho tác vụ kế tiếp

    def paste_cookies(self, account, cookies, url):
        self.pasted.append((account["id"], [c["name"] + "=" + c["value"] for c in cookies], url))

    def ensure_page(self, page_key, account_id):
        self.ensured.append((page_key, account_id))
        job = self.db.one("SELECT j.* FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.page=? AND j.status='queued'"
                          " ORDER BY j.created_at DESC", (page_key,))
        if self.fail:
            code, text = self.fail
            self.fail = None
            self.db.update_job(job["id"], status="blocked" if code == "blocked" else "failed", error_code=code, error_text=text)
            return
        self.out.mkdir(parents=True, exist_ok=True)
        video = "video" in page_key or page_key == "meta_muse"
        for i in range(int(job["count"])):
            f = self.out / f"{job['id']}_{i}{'.mp4' if video else '.jpg'}"
            f.write_bytes(b"\x00\x00\x00\x18ftypmp42" if video else b"\xff\xd8\xff" + bytes([i]))
            self.db.add_output(job["id"], "video" if video else "image", str(f))
        self.db.update_job(job["id"], status="done", progress=100, account_id=account_id)

    def ask_ai(self, account, system, user, timeout_s=240, on_status=None, files=None, **kw):
        from concurrent.futures import Future
        self.asked.append((account["id"], system, user, len(files or []), kw))
        f = Future()
        f.set_result("câu trả lời")
        return f


def _acc(db, home, platform, name):
    aid = db.add_account(platform, name, str(home / f"p_{platform}_{name}"))
    return db.one("SELECT * FROM accounts WHERE id=?", (aid,))


# ------------------------------------------------------------------ kho key
def test_store_keys_cookies_links(db):
    st = SyncStore(db)
    key, exp, warns = st.save_cookie("grok", GROK)
    assert looks_like_key(key) and exp == 4_000_000_000 and warns == []
    assert st.get(key)["platform"] == "grok" and st.cookie_text(key) == GROK
    assert "S1" not in json.dumps(db.get_setting("sync_api_keys"))            # cookie lưu mã hóa
    assert st.find(key)["key"] == key and st.find("sync-" + "0" * 48) is None and st.find("") is None

    k2, exp2, _ = st.save_cookie("grok", GROK2, key)                           # cập nhật cookie: key giữ nguyên
    assert k2 == key and exp2 == 4_100_000_000 and st.cookie_text(key) == GROK2
    cks, _, text = st.cookies(key)
    assert [c["value"] for c in cks] == ["S2"] and text == GROK2

    with pytest.raises(SyncKeyError):
        st.save_cookie("gpt", GPT, key)                                        # key của nền tảng khác
    with pytest.raises(SyncKeyError):
        st.save_cookie("grok", GROK, "sync-" + "1" * 48)                       # key lạ
    with pytest.raises(CookieError):
        st.save_cookie("grok", "   ")
    with pytest.raises(SyncKeyError):
        st.save_cookie("dreamina", GROK)

    st.link("a1", key)
    st.link("a2", key)
    assert st.key_of("a1") == key and sorted(st.accounts_of(key)) == ["a1", "a2"]
    st.unlink("a1")
    assert st.key_of("a1") == "" and st.accounts_of(key) == ["a2"]
    kg, _, _ = st.save_cookie("gpt", GPT)
    assert [e["key"] for e in st.entries("grok")] == [key] and {e["key"] for e in st.entries()} == {key, kg}
    st.delete(key)
    assert st.get(key) is None and st.accounts_of(key) == []


def test_apply_key_loads_cookie_into_account_and_resyncs(db, qapp, home, tmp_path):
    from videoai.syncapi.service import SyncApi
    eng = FakeEngine(db, tmp_path)
    sync = SyncApi(db, eng)
    acc = _acc(db, home, "grok", "g1")
    key, _, _ = sync.store.save_cookie("grok", GROK)

    assert sync.apply_key(acc, key) == []
    assert eng.pasted == [(acc["id"], ["sso=S1"], "https://grok.com/")]
    row = db.one("SELECT status, cookie_expires FROM accounts WHERE id=?", (acc["id"],))
    assert row["status"] == "unknown" and row["cookie_expires"] == 4_000_000_000
    assert db.account_cookie(acc["id"]) == GROK and sync.store.key_of(acc["id"]) == key
    assert sync.account_labels(key) == ["g1"]

    assert sync.apply_key(acc, key) == [] and len(eng.pasted) == 1             # Lưu rồi OK liền nhau: không nạp lần hai
    sync.store.save_cookie("grok", GROK2, key)                                 # đổi cookie trong SYNC API…
    sync._on_saved(key)                                                        # …tài khoản đang gắn key được nạp lại
    assert eng.pasted[-1] == (acc["id"], ["sso=S2"], "https://grok.com/")
    assert db.one("SELECT cookie_expires FROM accounts WHERE id=?", (acc["id"],))["cookie_expires"] == 4_100_000_000

    with pytest.raises(SyncKeyError):
        sync.apply_key(_acc(db, home, "gpt", "c1"), key)                       # key Grok không gắn được cho Chat GPT
    with pytest.raises(SyncKeyError):
        sync.apply_key(acc, "sync-" + "2" * 48)


# ------------------------------------------------------------------ giao diện
def test_sync_window_get_cookie_save_copy(db, qapp, home, tmp_path, monkeypatch):
    from PySide6.QtGui import QDesktopServices, QGuiApplication
    from videoai.syncapi.service import SyncApi
    sync = SyncApi(db, FakeEngine(db, tmp_path))
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()) or True)
    w = sync.open_window("muse", lock=True)
    assert w.windowTitle() == "SYNC API" and not w.plat_cb.isEnabled() and w.key_edit.text() == ""
    assert [b.text() for b in (w.b_get, w.b_save, w.b_copy)] == ["Lấy Cookie", "Lưu", "Sao chép API Key"]
    w.b_get.click()
    assert opened == ["https://muse.ai/"]                                      # mở bằng trình duyệt mặc định của người dùng

    got = []
    w.key_copied.connect(got.append)
    w.b_copy.click()                                                           # chưa có cookie → báo lỗi, không sao chép
    assert got == [] and "Chưa dán cookie" in w.msg.text() and w.isVisible()

    w.edit.setPlainText(MUSE)
    w.b_save.click()
    key = w.key_edit.text()
    assert looks_like_key(key) and sync.store.cookie_text(key) == MUSE and "Đã lưu" in w.msg.text()

    w.edit.setPlainText(MUSE + "; more=2")                                     # sửa cookie rồi bấm sao chép → tự lưu trước
    w.b_copy.click()
    assert got == [key] and QGuiApplication.clipboard().text() == key
    assert sync.store.cookie_text(key) == MUSE + "; more=2"
    assert not w.isVisible()                                                   # cửa sổ ẩn (biểu tượng ở khay hệ thống)

    w2 = sync.open_window("muse", key, lock=True)                              # mở lại đúng key → hiện cookie đã lưu
    assert w2.edit.toPlainText() == MUSE + "; more=2" and w2.key_edit.text() == key
    w2.close()
    w3 = sync.open_window()                                                    # mở từ khay: chọn được nền tảng / key
    assert w3.plat_cb.isEnabled() and w3.key_cb.count() == 1
    w3.plat_cb.setCurrentIndex(w3.plat_cb.findData("muse"))
    assert w3.key_cb.count() == 2 and "chưa gắn tài khoản" in w3.key_cb.itemText(1)
    w3.close()


def test_api_key_dialog_validates_and_receives_key(db, qapp, home, tmp_path):
    from videoai.syncapi.service import SyncApi
    from videoai.ui.api_key_dialog import ApiKeyDialog
    sync = SyncApi(db, FakeEngine(db, tmp_path))
    kg, _, _ = sync.store.save_cookie("grok", GROK)
    km, _, _ = sync.store.save_cookie("muse", MUSE)
    dlg = ApiKeyDialog(sync, "grok", "tk1")
    assert [b.text() for b in (dlg.b_get, dlg.b_ok, dlg.b_cancel)] == ["Lấy API Key", "OK", "Cancel"]
    for text, part in (("", "Chưa dán"), ("abc", "không đúng dạng"), ("sync-" + "3" * 48, "không có trong SYNC API"),
                       (km, "nền tảng Muse")):
        dlg.edit.setText(text)
        dlg._ok()
        assert dlg.result() != ApiKeyDialog.Accepted and part in dlg.msg.text(), text

    dlg.show()
    dlg._get_key()                                                             # «Lấy API Key» → mở SYNC API cho đúng nền tảng
    w = dlg._sync_win
    assert w.isVisible() and w.platform == "grok" and not w.plat_cb.isEnabled() and w.parent() is dlg
    w.edit.setPlainText(GROK2)
    w.b_copy.click()                                                           # Sao chép → SYNC API ẩn, khung API Key nhận key
    new = dlg.edit.text()
    assert looks_like_key(new) and new != kg and not w.isVisible() and dlg.isVisible()
    assert "Đã nhận API key" in dlg.msg.text()
    dlg._ok()
    assert dlg.result() == ApiKeyDialog.Accepted and dlg.key == new


@pytest.fixture()
def settings(db, qapp, home, tmp_path):
    from videoai.ui.main_window import Ctx
    from videoai.ui.pages.settings_page import SettingsPage

    from PySide6.QtCore import QObject, Signal

    class QtEngine(QObject):               # trang Cài đặt nối vào tín hiệu account_updated của engine
        account_updated = Signal(str)

        def __init__(self):
            super().__init__()
            self.fake = FakeEngine(db, tmp_path)
            self.pasted = self.fake.pasted

        def paste_cookies(self, *a):
            self.fake.paste_cookies(*a)
    eng = QtEngine()
    ctx = Ctx(None, db, eng, None, None)
    ctx.toasts = []
    ctx.toast = lambda kind, text: ctx.toasts.append((kind, text))
    sp = SettingsPage(ctx)
    return sp, ctx, eng


def test_add_account_requires_api_key(settings, db, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from videoai.syncapi import service as sync_service
    from videoai.ui import api_key_dialog
    sp, ctx, eng = settings
    key, _, _ = sync_service.get(ctx).store.save_cookie("grok", GROK)
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Grok", True)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("acc grok", True)))
    seen = []

    def fake_exec(self):
        seen.append((self.platform, self.windowTitle()))
        return api_key_dialog.ApiKeyDialog.Rejected
    monkeypatch.setattr(api_key_dialog.ApiKeyDialog, "exec", fake_exec)
    sp._add_account()
    assert seen and seen[0][0] == "grok" and "acc grok" in seen[0][1]          # nhập tên xong → hiện khung API Key
    assert db.accounts("grok") == []                                           # Cancel → không tạo tài khoản

    def ok_exec(self):
        self.key = key
        return api_key_dialog.ApiKeyDialog.Accepted
    monkeypatch.setattr(api_key_dialog.ApiKeyDialog, "exec", ok_exec)
    sp._add_account()
    accs = db.accounts("grok")
    assert len(accs) == 1 and accs[0]["label"] == "acc grok"
    assert sync_service.get(ctx).store.key_of(accs[0]["id"]) == key
    assert eng.pasted == [(accs[0]["id"], ["sso=S1"], "https://grok.com/")]    # cookie của key được nạp cho tài khoản
    assert db.account_cookie(accs[0]["id"]) == GROK

    sp._acc_checked = {accs[0]["id"]}                                          # nút «API Key» trên tài khoản đã có key
    cur = []

    def edit_exec(self):
        cur.append(self.edit.text())
        return api_key_dialog.ApiKeyDialog.Rejected
    monkeypatch.setattr(api_key_dialog.ApiKeyDialog, "exec", edit_exec)
    sp._login()
    assert cur == [key]                                                        # khung hiện sẵn key đang gắn


# ------------------------------------------------------------------ API HTTP
def _http(port, method, path, key=None, body=None, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode())
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_api_all_platforms(db, qapp, home, tmp_path):
    from videoai.syncapi.service import SyncApi
    eng = FakeEngine(db, tmp_path / "out")
    sync = SyncApi(db, eng)
    db.set_setting("sync_api_port", 0)
    assert sync.start_http()
    port = sync.http.port
    try:
        keys = {}
        for plat, ck in (("flow", "SID=1; __Secure-1PSID=2"), ("gpt", GPT), ("grok", GROK), ("muse", MUSE)):
            keys[plat], _, _ = sync.store.save_cookie(plat, ck)

        assert _http(port, "GET", "/v1/models")[0] == 401
        assert _http(port, "GET", "/v1/models", "sync-" + "0" * 48)[0] == 401
        assert _http(port, "GET", "/v1/models", keys["grok"], host="evil.example")[0] == 403
        st, r = _http(port, "POST", "/v1/images/generations", keys["grok"], {"prompt": "mèo"})
        assert st == 409 and r["error"]["code"] == "key_not_linked"           # key chưa gắn tài khoản nào

        accs = {p: _acc(db, home, p, "a_" + p) for p in keys}
        for p, a in accs.items():
            sync.apply_key(a, keys[p])

        st, r = _http(port, "GET", "/v1/models", keys["flow"])
        assert st == 200 and [m["id"] for m in r["data"]] == ["flow_image", "flow_video"]
        assert [m["id"] for m in _http(port, "GET", "/v1/models", keys["gpt"])[1]["data"]] == ["gpt_image", "chat"]

        for plat, page in (("flow", "flow_image"), ("gpt", "gpt_image"), ("grok", "grok_image"), ("muse", "muse_image")):
            st, r = _http(port, "POST", "/v1/images/generations", keys[plat], {"prompt": "một quả táo", "size": "1024x1024"})
            assert st == 200 and len(r["data"]) == 1, (plat, r)
            assert eng.ensured[-1] == (page, accs[plat]["id"])
            b = db.one("SELECT * FROM batches WHERE page=? ORDER BY created_at DESC", (page,))
            p = json.loads(b["params"])
            assert p["pin_account"] == accs[plat]["id"] and p["ratio"].startswith("1:1") and b["source"] == "webhook"
            assert _http(port, "GET", r["data"][0]["url"].split(str(port), 1)[1])[1][:3] == b"\xff\xd8\xff"

        # Grok: 3 ảnh + ảnh tham chiếu + trả base64
        st, r = _http(port, "POST", "/v1/images/generations", keys["grok"],
                      {"prompt": "x", "n": 3, "ratio": "16:9", "response_format": "b64_json",
                       "images": ["data:image/png;base64," + base64.b64encode(PNG).decode()],
                       "params": {"_x": 1, "pin_account": "kẻ khác", "note": "giữ"}})
        assert st == 200 and len(r["data"]) == 3 and base64.b64decode(r["data"][0]["b64_json"])[:3] == b"\xff\xd8\xff"
        job = db.one("SELECT j.*, b.params AS bp FROM jobs j JOIN batches b ON b.id=j.batch_id ORDER BY j.created_at DESC")
        bp = json.loads(job["bp"])
        assert job["count"] == 3 and len(json.loads(job["refs"])) == 1 and bp["ratio"] == "16:9 Ngang"
        assert bp["pin_account"] == accs["grok"]["id"] and "_x" not in bp and bp["note"] == "giữ"

        for plat, page in (("flow", "flow_video"), ("grok", "grok_video"), ("muse", "meta_muse")):
            st, r = _http(port, "POST", "/v1/videos/generations", keys[plat], {"prompt": "flycam", "ratio": "9:16"})
            assert st == 200 and r["data"][0]["url"].endswith(".mp4"), (plat, r)
            assert eng.ensured[-1] == (page, accs[plat]["id"])
        assert db.one("SELECT mode FROM jobs ORDER BY created_at DESC")["mode"] == "t2v"
        st, r = _http(port, "POST", "/v1/videos/generations", keys["grok"],
                      {"prompt": "động", "image": base64.b64encode(PNG).decode()})
        assert st == 200 and db.one("SELECT mode FROM jobs ORDER BY created_at DESC")["mode"] == "i2v"
        st, r = _http(port, "POST", "/v1/videos/generations", keys["gpt"], {"prompt": "x"})
        assert st == 400 and r["error"]["code"] == "unsupported"              # Chat GPT không có trang video

        st, r = _http(port, "POST", "/v1/images/generations", keys["muse"], {"prompt": "x", "ratio": "21:9"})
        assert st == 400 and r["error"]["code"] == "bad_ratio" and "1:1" in r["error"]["message"]
        assert _http(port, "POST", "/v1/images/generations", keys["muse"], {"prompt": "  "})[0] == 400
        assert _http(port, "POST", "/v1/images/generations", keys["muse"], {"prompt": "x", "images": ["@@@"]})[0] == 400

        eng.fail = ("blocked", "[a_muse] Muse từ chối")
        st, r = _http(port, "POST", "/v1/images/generations", keys["muse"], {"prompt": "bị chặn"})
        assert st == 502 and r["error"]["code"] == "blocked" and "Muse từ chối" in r["error"]["message"]

        db.update_account(accs["muse"]["id"], enabled=0)                       # tài khoản của key bị tắt
        assert _http(port, "POST", "/v1/images/generations", keys["muse"], {"prompt": "x"})[0] == 409

        # AI Agent qua API key của tài khoản Chat GPT
        st, r = _http(port, "POST", "/v1/chat/completions", keys["gpt"],
                      {"messages": [{"role": "system", "content": "ngắn gọn"}, {"role": "user", "content": "xin chào"}]})
        assert st == 200 and r["choices"][0]["message"]["content"] == "câu trả lời"
        assert eng.asked[-1][:4] == (accs["gpt"]["id"], "ngắn gọn", "xin chào", 0)
        assert _http(port, "POST", "/v1/chat/completions", keys["grok"], {"messages": [{"role": "user", "content": "x"}]})[0] == 400
        assert _http(port, "GET", "/files/khong-co")[0] == 404
    finally:
        sync.shutdown()
    assert not sync.http.running()


# ------------------------------------------------------------------ engine: ghim tác vụ vào tài khoản của key
def test_engine_pins_api_jobs_to_key_account(db, qapp, home):
    from videoai.core.engine import PIN_FAILED, Engine, PageRun
    eng = Engine(db)
    try:
        a1, a2 = _acc(db, home, "grok", "k1"), _acc(db, home, "grok", "k2")
        r = PageRun("grok_image", [a1["id"], a2["id"]], 1, (0, 0))

        def job(params):
            bid = db.create_batch("grok", "grok_image", params, str(home / "o"), "flat",
                                  [{"mode": "t2i", "prompt": "p", "count": 1}], source="webhook")
            return db.one("SELECT j.*, b.params AS batch_params FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.id=?", (bid,))

        assert eng._key_pin(r, job({})) is None                                # tác vụ thường: không ghim
        assert eng._key_pin(r, job({"pin_account": a2["id"]})) == a2["id"]
        r.down[a2["id"]] = "not_logged_in"                                     # tài khoản của key không dùng được
        j = job({"pin_account": a2["id"]})
        assert eng._key_pin(r, j) == PIN_FAILED
        row = db.one("SELECT status, error_code, error_text FROM jobs WHERE id=?", (j["id"],))
        assert row["status"] == "failed" and row["error_code"] == "not_logged_in" and "k2" in row["error_text"]
        j = job({"pin_account": "tai-khoan-da-xoa"})
        assert eng._key_pin(r, j) == PIN_FAILED
        assert db.one("SELECT error_code FROM jobs WHERE id=?", (j["id"],))["error_code"] == "no_account"

        eng.ensure_page("grok_image", a1["id"]).result(10)                     # chưa chạy → bật trang với tài khoản này
        run = eng.runs["grok_image"]
        assert run.active and run.account_ids == [a1["id"]] and run.failover is False
        run.concurrency, run.delay, run.down = 3, (7, 9), {a2["id"]: "quota"}
        eng.ensure_page("grok_image", a2["id"]).result(10)                     # đang chạy → chỉ thêm tài khoản, giữ cấu hình
        assert run.account_ids == [a1["id"], a2["id"]] and run.concurrency == 3 and run.delay == (7, 9)
        assert a2["id"] not in run.down
    finally:
        eng.shutdown()


def test_http_api_runs_real_engine_on_key_account(db, qapp, mock_site, home):
    """Đầu-cuối với engine thật + trang AI giả lập: key → nạp cookie vào hồ sơ tài khoản → gọi API HTTP → có tệp ảnh,
    và tác vụ chạy đúng trên tài khoản của key dù nền tảng có tài khoản khác."""
    import time
    from videoai.core.engine import Engine
    from videoai.syncapi.service import SyncApi
    db.set_setting("platform_urls", {"grok_image": mock_site, "grok_video": mock_site})
    db.set_setting("default_delay", [0, 0])
    db.set_setting("sync_api_port", 0)
    eng = Engine(db)
    sync = SyncApi(db, eng)
    try:
        other = _acc(db, home, "grok", "khac")                                 # tài khoản khác cùng nền tảng (tạo trước)
        acc = _acc(db, home, "grok", "cua_key")
        key, _, _ = sync.store.save_cookie("grok", GROK)
        sync.apply_key(acc, key)                                               # nạp cookie thật vào hồ sơ + tự kiểm tra
        t = time.time()
        while time.time() - t < 90 and db.one("SELECT last_check_at FROM accounts WHERE id=?", (acc["id"],))["last_check_at"] is None:
            time.sleep(0.5)
        assert db.one("SELECT status FROM accounts WHERE id=?", (acc["id"],))["status"] == "ok"

        assert sync.start_http()
        st, r = _http(sync.http.port, "POST", "/v1/images/generations", key, {"prompt": "Phở bò Hà Nội", "n": 2, "timeoutSec": 120})
        assert st == 200 and len(r["data"]) == 2, r
        assert all(Path(d["path"]).stat().st_size > 0 for d in r["data"])
        assert _http(sync.http.port, "GET", r["data"][0]["url"].split(str(sync.http.port), 1)[1])[1][:3] == b"\xff\xd8\xff"
        job = db.one("SELECT * FROM jobs ORDER BY created_at DESC")
        assert job["status"] == "done" and job["account_id"] == acc["id"] and job["account_id"] != other["id"]

        st, r = _http(sync.http.port, "POST", "/v1/images/generations", key, {"prompt": "BLOCKME xin lỗi", "timeoutSec": 120})
        assert st == 502 and r["error"]["code"] == "blocked", r               # lỗi của nền tảng trả về đúng mã
    finally:
        sync.shutdown()
        eng.shutdown()


# ------------------------------------------------------------------ AI Agent: API chính thức trước, rồi tới tài khoản
def test_ai_agent_prefers_official_api_then_account(db, qapp, home, tmp_path, monkeypatch):
    from videoai.services import api_llm, llm
    eng = FakeEngine(db, tmp_path)
    acc = _acc(db, home, "gpt", "chat1")
    db.update_account(acc["id"], status="ok")
    calls = []
    monkeypatch.setattr(api_llm, "ask", lambda db_, prov, *a, **k: calls.append(prov) or "từ API chính thức")

    assert llm.ask(db, eng, "hệ thống", "câu hỏi") == "câu trả lời"            # chưa có API key chính thức → dùng tài khoản
    assert calls == [] and eng.asked[-1][0] == acc["id"]

    api_llm.save(db, "gemini", "khóa-gemini", "")
    api_llm.mark_ok("gemini")
    n = len(eng.asked)
    assert llm.ask(db, eng, "hệ thống", "câu hỏi") == "từ API chính thức"      # có API key chính thức → dùng trước
    assert calls == ["gemini"] and len(eng.asked) == n                         # không đụng tới tài khoản

    def boom(db_, prov, *a, **k):
        raise api_llm.ApiError(prov, "quota", "hết lượt")
    monkeypatch.setattr(api_llm, "ask", boom)
    assert llm.ask(db, eng, "hệ thống", "câu hỏi") == "câu trả lời"            # API chính thức lỗi → chuyển sang tài khoản
    assert len(eng.asked) == n + 1
    api_llm.mark_ok("gemini")


def test_ai_agent_ready_with_official_api_only(db, qapp, home, tmp_path, monkeypatch):
    """Có API key chính thức thì AI Agent chạy được dù KHÔNG có tài khoản Chat GPT nào (trước đây popup Quy trình tự
    động chặn lại và báo "chưa có tài khoản Chat GPT nào đăng nhập"). API lỗi + tài khoản lỗi → báo cả hai, API trước."""
    from videoai.services import api_llm, llm
    assert llm.pick_account(db) is None and not llm.ready(db)
    api_llm.save(db, "openai", "sk-khóa-chính-thức", "")
    api_llm.mark_ok("openai")
    assert llm.pick_account(db) is None and llm.ready(db)                      # không cần tài khoản
    monkeypatch.setattr(api_llm, "ask", lambda db_, prov, *a, **k: "từ API chính thức")
    assert llm.ask(db, FakeEngine(db, tmp_path), "s", "u") == "từ API chính thức"

    api_llm.save(db, "openai", "sk-khóa-chính-thức", "", on=False)             # tắt API, chưa có tài khoản → chưa sẵn sàng
    assert not llm.ready(db)
    acc = _acc(db, home, "gpt", "c1")
    db.update_account(acc["id"], status="ok")
    assert llm.ready(db)                                                       # không có API chính thức → dùng tài khoản

    api_llm.save(db, "openai", "sk-khóa-chính-thức", "", on=True)

    def boom(db_, prov, *a, **k):
        raise api_llm.ApiError(prov, "auth", "API key không đúng")
    monkeypatch.setattr(api_llm, "ask", boom)

    class Down(FakeEngine):
        def ask_ai(self, *a, **k):
            from concurrent.futures import Future
            from videoai.core.errors import JobError
            f = Future()
            f.set_exception(JobError("not_logged_in", "Tài khoản AI Agent (c1) đã hết phiên đăng nhập"))
            return f
    with pytest.raises(RuntimeError) as e:
        llm.ask(db, Down(db, tmp_path), "s", "u")
    msg = str(e.value)
    assert msg.index("API chính thức lỗi") < msg.index("Tài khoản Chat GPT cũng lỗi")
    assert "API key không đúng" in msg and "hết phiên đăng nhập" in msg
    api_llm.mark_ok("openai")


# ------------------------------------------------------------------ Chat GPT: không chạy ngầm, nhận ra trang Cloudflare
def test_chatgpt_never_headless_and_cloudflare_page_needs_user(db, qapp, home, monkeypatch):
    import asyncio
    from videoai.adapters import gpt
    from videoai.core.engine import Engine
    eng = Engine(db)
    try:
        assert db.get_setting("run_headless", True) is True
        assert eng._use_headless({"id": "a", "platform": "grok"}) is True
        assert eng._use_headless({"id": "b", "platform": "gpt"}) is False       # Chat GPT luôn dùng Chrome thường (ẩn)
    finally:
        eng.shutdown()

    class Loc:
        def __init__(self, n=0):
            self.n = n

        async def count(self):
            return self.n

        def nth(self, i):
            return self

        @property
        def first(self):
            return self

        async def is_visible(self):
            return self.n > 0

    class Page:
        """Trang Cloudflare đo được ngày 27/11/2026: tiêu đề "Just a moment...", thân trang trống, không iframe."""
        url = "https://chatgpt.com/images/"

        def __init__(self, titles):
            self.titles = list(titles)

        async def title(self):
            return self.titles.pop(0) if len(self.titles) > 1 else self.titles[0]

        def locator(self, sel):
            return Loc(0)

    class Clock:
        t = 0.0

        def monotonic(self):
            Clock.t += 5.0
            return Clock.t

    async def no_sleep(_):
        return None
    monkeypatch.setattr(gpt, "time", Clock())
    monkeypatch.setattr(gpt.asyncio, "sleep", no_sleep)
    ad = gpt.GptAdapter()
    assert asyncio.run(ad.check_login(Page(["Just a moment..."]))) == "needs_user"      # không còn báo "chưa xác định"
    assert asyncio.run(ad.is_logged_in(Page(["Just a moment..."]))) is False
    assert asyncio.run(ad._challenge(Page(["Just a moment...", "ChatGPT"]), wait_s=20)) is False   # tự qua trong lúc chờ
