"""v2.2.1: Authentication Engine – làm mới phiên Google hợp lệ khi trang bị đẩy về accounts.google.com, không lách."""
import asyncio

from videoai.adapters.flow import FlowAdapter, HOME


class _FakePage:
    def __init__(self, cookie=True, recover_after=1):
        self.url = "https://accounts.google.com/signin"
        self._cookie = cookie
        self._recover_after = recover_after      # số lần goto HOME trước khi phiên "sống lại"
        self._goto = 0

    async def goto(self, url, **kw):
        self._goto += 1
        if url == HOME and self._cookie and self._goto >= self._recover_after:
            self.url = HOME + "project/abc"
        else:
            self.url = url

    @property
    def context(self):
        page = self

        class _Ctx:
            async def cookies(self):
                import time
                return [{"domain": ".google.com", "name": "__Secure-1PSID", "expires": time.time() + 3600}] if page._cookie else []
        return _Ctx()

    def locator(self, *_a, **_k):
        raise AssertionError("refresh không được bấm nút nào")


def test_refresh_session_recovers_valid_login(monkeypatch):
    ad = FlowAdapter()

    async def no_onboard(page, *a, **k):
        return 0
    monkeypatch.setattr(FlowAdapter, "onboarding", no_onboard)
    p = _FakePage(cookie=True, recover_after=1)
    assert asyncio.run(ad._refresh_session(p)) is True
    assert "/project/" in p.url


def test_refresh_session_gives_up_without_cookie(monkeypatch):
    ad = FlowAdapter()
    p = _FakePage(cookie=False)
    assert asyncio.run(ad._refresh_session(p)) is False      # thật sự đã đăng xuất → không cố, không lách
    assert p._goto == 0                                       # không cookie thì không tải lại
