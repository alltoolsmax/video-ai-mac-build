"""Tài khoản Gemini: loại tài khoản RIÊNG chỉ dùng cho AI Agent, cookie lấy ở gemini.google.com, không dùng chung
với tài khoản Google của Flow. Thứ tự AI Agent: API key chính thức → tài khoản Chat GPT → tài khoản Gemini."""
import json
from concurrent.futures import Future

import pytest

GEM_COOKIE = json.dumps([{"domain": ".google.com", "name": "SID", "value": "s", "expirationDate": 4_000_000_000},
                         {"domain": ".google.com", "name": "__Secure-1PSID", "value": "p", "expirationDate": 4_000_000_000},
                         {"domain": "gemini.google.com", "name": "OSID", "value": "g", "hostOnly": True}])


class Eng:
    def __init__(self, fail=()):
        self.used, self.fail = [], set(fail)

    def ask_ai(self, acc, system, user, timeout_s=240, on_status=None, files=None, **kw):
        f = Future()
        self.used.append(acc["label"])
        if acc["id"] in self.fail:
            f.set_exception(RuntimeError("không gửi được"))
        else:
            f.set_result("OK " + acc["label"])
        return f


def _add(db, platform, name, status="ok"):
    aid = db.add_account(platform, name, f"/tmp/{platform}_{name}")
    db.update_account(aid, status=status)
    return aid


def test_gemini_is_its_own_agent_only_platform():
    from videoai.adapters import chat
    from videoai.core import cookies
    from videoai.core.platforms import AGENT_ONLY_PLATFORMS, PAGES, PLATFORM_LABELS
    from videoai.services import llm
    from videoai.syncapi.store import PLATFORMS
    assert llm.CHAT_PLATFORMS == ("gpt", "gemini") and "flow" not in llm.CHAT_PLATFORMS
    assert AGENT_ONLY_PLATFORMS == {"gemini": "https://gemini.google.com/app"} and PLATFORM_LABELS["gemini"] == "Gemini"
    assert all(p.platform != "gemini" for p in PAGES)                         # không có trang tạo ảnh / video
    assert cookies.PLATFORM_HOSTS["gemini"] == "https://gemini.google.com/"   # nút «Lấy Cookie» mở đúng trang Gemini
    assert cookies.PLATFORM_DOMAINS["gemini"] == (".google.com",) and "gemini" in PLATFORMS
    assert chat.SITES["gemini"][1] == "https://gemini.google.com/app" and chat.LABEL["gemini"] == "Gemini"
    assert "gemini" in chat.PASTE_SITES and chat.TEMP_CHAT["gemini"] and chat.ATTACH_OPEN["gemini"]


def test_agent_uses_gemini_accounts_never_flow_accounts(db, monkeypatch):
    from videoai.services import api_llm, llm
    monkeypatch.setattr(llm, "_busy", {}); monkeypatch.setattr(llm, "_bad", {}); monkeypatch.setattr(llm, "_next", {})
    _add(db, "flow", "google-flow"), _add(db, "grok", "grok"), _add(db, "muse", "muse")
    assert llm.candidates(db) == [] and not llm.ready(db)                     # tài khoản Flow không dùng cho AI Agent
    # chỉ có tài khoản Google (Flow) – kể cả khi người dùng đặt tên nó là "Gemini" – thì báo rõ phải thêm loại «Gemini»
    with pytest.raises(RuntimeError, match=r"Google \(Flow\) chỉ tạo ảnh / video.*«Gemini»"):
        llm.ask(db, Eng(), "s", "u")
    assert "gemini.google.com" in llm.missing_hint(db)

    _add(db, "gemini", "gem1"), _add(db, "gemini", "gem2")
    assert [a["label"] for a in llm.candidates(db)] == ["gem1", "gem2"] and llm.ready(db)
    e = Eng()
    assert [llm.ask(db, e, "s", "u") for _ in range(3)] == ["OK gem1", "OK gem2", "OK gem1"]   # luân phiên

    gpt = _add(db, "gpt", "chat1")                                            # có Chat GPT → Chat GPT trước, Gemini sau
    assert [a["platform"] for a in llm.candidates(db)] == ["gpt", "gemini", "gemini"]
    e = Eng()
    assert llm.ask(db, e, "s", "u") == "OK chat1" and e.used == ["chat1"]
    e = Eng(fail={gpt})                                                       # Chat GPT lỗi → chuyển sang Gemini
    assert llm.ask(db, e, "s", "u").startswith("OK gem") and e.used[0] == "chat1"
    llm._bad.clear()

    monkeypatch.setattr(api_llm, "ask", lambda db_, prov, *a, **k: "từ API chính thức")
    api_llm.save(db, "openai", "sk-x", "")
    api_llm.mark_ok("openai")
    e = Eng()
    assert llm.ask(db, e, "s", "u") == "từ API chính thức" and e.used == []   # API chính thức vẫn đứng đầu
    api_llm.save(db, "openai", "", "")


def test_gemini_account_end_to_end_on_mock_page(db, qapp, mock_site, home):
    """Engine thật + trang Gemini giả lập: tài khoản Gemini riêng → kiểm tra đăng nhập "ok" → AI Agent sửa prompt
    (câu trả lời nằm trong shadow DOM như trang giả lập mô phỏng)."""
    import time
    from videoai.core.engine import Engine
    from videoai.core.platforms import platform_url
    from videoai.services import llm
    url = mock_site.replace("index.html", "chat/gemini.html")
    db.set_setting("ai_chat_urls", {"gemini": url})
    assert platform_url(db, "gemini") == url
    eng = Engine(db)
    try:
        aid = db.add_account("gemini", "gem", str(home / "pgem"))
        acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
        eng.check_account(acc, url)
        t = time.time()
        while time.time() - t < 90 and db.one("SELECT last_check_at FROM accounts WHERE id=?", (aid,))["last_check_at"] is None:
            time.sleep(0.5)
        assert db.one("SELECT status FROM accounts WHERE id=?", (aid,))["status"] == "ok"
        assert llm.pick_account(db)["id"] == aid
        out = llm.fix_prompts(db, ["a red apple", "cat on sofa"], eng)
        assert out == ["Improved: a red apple", "Improved: cat on sofa"]
    finally:
        eng.shutdown()


class _Loc:
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

    async def wait_for(self, **k):
        if not self.n:
            raise TimeoutError


def test_gemini_signin_redirect_is_reported_as_not_logged_in(monkeypatch):
    """Đo trên trang thật 27/11/2026: phiên không hợp lệ cho Gemini → chuyển sang accounts.google.com dù cookie SID còn.
    Kiểm tra tài khoản phải báo "chưa đăng nhập" (không dựa vào cookie SID), và AI Agent báo rõ phải lấy cookie ở Gemini."""
    import asyncio
    from videoai.adapters import chat, gemini
    from videoai.core.errors import JobError

    class Ctx:
        async def cookies(self, *a):
            return [{"name": "__Secure-1PSID", "value": "x", "domain": ".google.com", "expires": -1}]

    class Page:
        context = Ctx()

        def __init__(self, url, prompt=False):
            self.url, self.prompt = url, prompt

        async def title(self):
            return "Sign in - Google Accounts"

        def locator(self, s):
            return _Loc(1 if self.prompt and "contenteditable" in s else 0)

        async def screenshot(self, **k):
            return b""

        def is_closed(self):
            return False

    async def no_sleep(_):
        return None
    monkeypatch.setattr(gemini.asyncio, "sleep", no_sleep)
    ad = gemini.GeminiAdapter()
    signin = "https://accounts.google.com/v3/signin/identifier?continue=https://gemini.google.com/app"
    assert ad.LOGIN_COOKIES == () and ad.url == "https://gemini.google.com/app"
    assert asyncio.run(ad.check_login(Page(signin))) == "expired"
    assert asyncio.run(ad.is_logged_in(Page(signin))) is False
    assert asyncio.run(ad.has_login_cookie(Page(signin))) is False            # cookie SID không được coi là đã đăng nhập
    assert asyncio.run(ad.check_login(Page("https://gemini.google.com/app", prompt=True))) == "ok"

    called = []

    async def on_verify(show, msg=None):
        called.append(show)
    with pytest.raises(JobError) as e:
        asyncio.run(chat._not_ready(Page(signin), "gemini", "Gemini", "https://gemini.google.com/app", [], lambda m: None, on_verify))
    assert e.value.code == "not_logged_in" and "gemini.google.com" in e.value.detail and called == []


def test_add_gemini_account_gets_cookie_from_gemini_site(db, qapp, home, tmp_path, monkeypatch):
    """Thêm tài khoản → có lựa chọn "Gemini (chỉ dùng cho AI Agent)" → SYNC API mở đúng trang gemini.google.com để lấy
    cookie → key Gemini không gắn được cho tài khoản Flow và ngược lại."""
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QInputDialog
    from videoai.syncapi import service as sync_service
    from videoai.syncapi.store import SyncKeyError
    from videoai.ui import api_key_dialog
    from videoai.ui.main_window import Ctx
    from videoai.ui.pages.settings_page import SettingsPage

    class QtEngine(QObject):
        account_updated = Signal(str)
        pasted = []

        def paste_cookies(self, account, cookies, url):
            self.pasted.append((account["platform"], sorted(c["name"] for c in cookies), url))
    eng = QtEngine()
    ctx = Ctx(None, db, eng, None, None)
    ctx.toast = lambda kind, text: None
    sp = SettingsPage(ctx)
    sync = sync_service.get(ctx)

    offered = []
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda p, t, l, names, *a, **k: (offered.extend(names) or names[-1], True)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("gem@gmail.com", True)))
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()) or True)

    def exec_(self):
        assert self.platform == "gemini"
        self._get_key()                                                       # «Lấy API Key» → SYNC API cho Gemini
        w = self._sync_win
        w.b_get.click()                                                       # «Lấy Cookie»
        w.edit.setPlainText(GEM_COOKIE)
        w.b_copy.click()
        self._ok()
        return self.result()
    monkeypatch.setattr(api_key_dialog.ApiKeyDialog, "exec", exec_)
    sp._add_account()
    assert offered[-1] == "Gemini – chỉ dùng cho AI Agent (cookie ở gemini.google.com)"
    assert offered[0] == "Google Flow – tạo ảnh / video (cookie ở flow.google.com)"   # hai loại tài khoản Google ghi rõ khác nhau
    assert opened == ["https://gemini.google.com/"]                          # cookie lấy ở trang Gemini, không phải Flow
    accs = db.accounts("gemini")
    assert len(accs) == 1 and accs[0]["label"] == "gem@gmail.com" and db.accounts("flow") == []
    assert eng.pasted == [("gemini", ["OSID", "SID", "__Secure-1PSID"], "https://gemini.google.com/app")]
    key = sync.store.key_of(accs[0]["id"])
    assert sync.store.get(key)["platform"] == "gemini"

    fid = db.add_account("flow", "flow1", str(home / "pflow"))
    with pytest.raises(SyncKeyError):                                         # key Gemini không dùng chung cho tài khoản Flow
        sync.apply_key(db.one("SELECT * FROM accounts WHERE id=?", (fid,)), key)
    fkey, _, _ = sync.store.save_cookie("flow", "SID=1; __Secure-1PSID=2")
    with pytest.raises(SyncKeyError):                                         # và key Flow không gắn được cho tài khoản Gemini
        sync.apply_key(accs[0], fkey)

    rows = [sp.ai_list.item(r, 1).text() for r in range(sp.ai_list.rowCount())]
    sp._reload_ai_accounts()
    rows = [sp.ai_list.item(r, 1).text() for r in range(sp.ai_list.rowCount())]
    assert rows == ["Gemini · gem@gmail.com"] and not hasattr(sp, "gemini_cb")   # tài khoản Flow không có trong danh sách


def test_sync_http_chat_with_gemini_key_and_no_generation(db, qapp, home, tmp_path):
    import urllib.error
    import urllib.request
    from videoai.syncapi.service import SyncApi

    class E:
        asked = []

        def paste_cookies(self, *a):
            pass

        def ask_ai(self, account, system, user, timeout_s=240, on_status=None, files=None, **kw):
            f = Future()
            self.asked.append(account["platform"])
            f.set_result("xin chào từ Gemini")
            return f
    eng = E()
    sync = SyncApi(db, eng)
    db.set_setting("sync_api_port", 0)
    assert sync.start_http()

    def call(path, key, body):
        req = urllib.request.Request(f"http://127.0.0.1:{sync.http.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())
    try:
        key, _, _ = sync.store.save_cookie("gemini", GEM_COOKIE)
        aid = db.add_account("gemini", "gem", str(home / "pg"))
        sync.apply_key(db.one("SELECT * FROM accounts WHERE id=?", (aid,)), key)
        st, r = call("/v1/chat/completions", key, {"messages": [{"role": "user", "content": "chào"}]})
        assert st == 200 and r["choices"][0]["message"]["content"] == "xin chào từ Gemini" and eng.asked == ["gemini"]
        st, r = call("/v1/images/generations", key, {"prompt": "x"})
        assert st == 400 and r["error"]["code"] == "unsupported" and "AI Agent" in r["error"]["message"]
    finally:
        sync.shutdown()
