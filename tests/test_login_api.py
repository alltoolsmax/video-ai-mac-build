"""v2.1.6: đăng nhập lần đầu không báo nhầm + AI Agent qua API key (Gemini / Chat GPT)."""
import asyncio
import io
import json
import time
import urllib.error

import pytest

from videoai.adapters.flow import FlowAdapter
from videoai.adapters.gpt import GptAdapter
from videoai.services import api_llm, llm


class _Ctx:
    def __init__(self, cookies):
        self._c = cookies

    async def cookies(self):
        return self._c


class _Page:
    def __init__(self, cookies, url="https://flow.google.com/about"):
        self.context = _Ctx(cookies)
        self.url = url


def test_login_cookie_detection():
    ad = FlowAdapter()
    future = time.time() + 3600
    page = _Page([{"domain": ".google.com", "name": "__Secure-1PSID", "expires": future}])
    assert asyncio.run(ad.has_login_cookie(page))
    assert not asyncio.run(ad.has_login_cookie(_Page([{"domain": ".google.com", "name": "NID", "expires": future}])))
    assert not asyncio.run(ad.has_login_cookie(_Page([{"domain": ".google.com", "name": "SID", "expires": time.time() - 5}])))
    g = GptAdapter()
    assert asyncio.run(g.has_login_cookie(_Page([{"domain": "chatgpt.com", "name": "__Secure-next-auth.session-token.0",
                                                 "expires": -1}])))


# ------------------------------------------------------------------ API
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_http(monkeypatch):
    calls = []
    replies = []

    def urlopen(req, timeout=0):
        body = json.loads(req.data.decode()) if req.data else None
        calls.append((req.full_url, dict(req.header_items()), body))
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Resp(json.dumps(r).encode())
    monkeypatch.setattr(api_llm.urllib.request, "urlopen", urlopen)
    api_llm._bad.clear()
    return calls, replies


def _gem(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _http(code, body):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps(body).encode()))


def test_gemini_used_first_without_browser(db, fake_http):
    calls, replies = fake_http
    api_llm.save(db, "gemini", "AIzaTEST", "", True)
    replies.append(_gem("A cinematic shot"))
    out = llm.ask(db, None, "Sửa prompt", "chó chạy")
    assert out == "A cinematic shot"
    url, headers, body = calls[0]
    assert "models/gemini-flash-latest:generateContent" in url
    assert headers.get("X-goog-api-key") == "AIzaTEST"
    assert body["contents"][0]["parts"][0]["text"] == "chó chạy"


def test_api_format_retry_then_fallback_to_openai(db, fake_http):
    calls, replies = fake_http
    api_llm.save(db, "gemini", "AIzaTEST", "gemini-x", True)
    api_llm.save(db, "openai", "sk-test", "gpt-test", True)

    def check(ans):
        json.loads(ans)
    replies += [_http(429, {"error": {"message": "Quota exceeded"}}),           # Gemini hết lượt miễn phí
                {"choices": [{"message": {"content": "không phải json"}}]},    # OpenAI sai định dạng → nhắc sửa
                {"choices": [{"message": {"content": '{"ok": 1}'}}]}]
    out = llm.ask(db, None, "Viết", "kịch bản", check=check, want_json=True)
    assert out == '{"ok": 1}'
    assert api_llm.is_bad("gemini") and not api_llm.is_bad("openai")
    last = calls[-1][2]
    assert last["model"] == "gpt-test" and last["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in last["messages"]] == ["system", "user", "assistant", "user"]
    # lần sau: Gemini đang tạm nghỉ → OpenAI được thử trước
    assert api_llm.active(db) == ["openai", "gemini"]


def test_openai_without_credit_message(db, fake_http):
    calls, replies = fake_http
    api_llm.save(db, "openai", "sk-test", "", True)
    replies.append(_http(429, {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}}))
    with pytest.raises(RuntimeError) as e:
        llm.ask(db, None, "s", "u")
    assert "chưa nạp tiền" in str(e.value)


def test_disabled_or_empty_key_skipped(db, fake_http):
    api_llm.save(db, "gemini", "AIza", "", False)
    api_llm.save(db, "openai", "", "", True)
    assert api_llm.active(db) == []
    with pytest.raises(RuntimeError):
        llm.ask(db, None, "s", "u")
