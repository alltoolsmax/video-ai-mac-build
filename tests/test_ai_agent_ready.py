"""v2.2.6 – AI Agent: đã đăng nhập nhưng ChatGPT chưa vào đúng khung chat thì KHÔNG báo "chưa đăng nhập".
Tự đóng bảng thông báo che khung chat; chỉ báo hết phiên khi trang thật sự hiện nút Đăng nhập và không còn phiên."""
import pytest

from videoai.adapters import chat
from videoai.core.errors import JobError


def _eng(db, url):
    from videoai.core.engine import Engine
    db.set_setting("ai_chat_urls", {"gpt": url})
    return Engine(db)


def _ask(db, eng, home, name):
    aid = db.add_account("gpt", name, str(home / ("p" + name)))
    db.update_account(aid, status="ok")
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    return eng.ask_ai(acc, "Bạn là trợ lý.", "Improve prompts:\n1. a red apple").result(240)


def test_popup_over_chat_is_dismissed(db, qapp, mock_site, home):
    eng = _eng(db, mock_site.replace("index.html", "chat/index.html") + "?popup=1")
    try:
        assert _ask(db, eng, home, "pop").strip()          # đã đóng bảng thông báo và nhận được câu trả lời
    finally:
        eng.shutdown()


def test_logged_in_but_no_chat_is_not_reported_as_logged_out(db, qapp, mock_site, home, monkeypatch):
    eng = _eng(db, mock_site.replace("index.html", "chat/index.html") + "?nochat=1")
    real = chat._not_ready

    async def not_ready(page, platform, name, url, inputs, say, on_verify):
        return await real(page, platform, name, url, inputs, say, None)   # không hiện cửa sổ chờ
    monkeypatch.setattr(chat, "_not_ready", not_ready)
    try:
        with pytest.raises(JobError) as e:
            _ask(db, eng, home, "noc")
        assert e.value.code == "ui_changed"
        assert "không phải lỗi đăng nhập" in e.value.detail
    finally:
        eng.shutdown()


def test_really_logged_out_is_reported(db, qapp, mock_site, home):
    eng = _eng(db, mock_site.replace("index.html", "chat/index.html") + "?nochat=1&loggedout=1")
    try:
        with pytest.raises(JobError) as e:
            _ask(db, eng, home, "out")
        assert e.value.code == "not_logged_in"
    finally:
        eng.shutdown()


def test_same_page():
    assert chat._same_page("https://chatgpt.com/?model=x", "https://chatgpt.com/")
    assert not chat._same_page("https://chatgpt.com/images/", "https://chatgpt.com/")
    assert not chat._same_page("https://chatgpt.com/gpts", "https://chatgpt.com/")
