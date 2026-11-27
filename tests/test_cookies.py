"""Dán cookie thay cho mở Chrome đăng nhập: đọc cookie, nạp vào hồ sơ tài khoản, tự kiểm tra, rồi chạy tác vụ."""
import json
import os
import time

import pytest

from videoai.core.cookies import CookieError, has_session, parse


def test_parse_header_string_uses_platform_domain():
    cks, warns = parse("Cookie: SID=a; HSID=b; __Secure-1PSID=c; __Host-GAPS=d; rác", "flow")
    assert [c["name"] for c in cks] == ["SID", "HSID", "__Secure-1PSID", "__Host-GAPS"]
    assert cks[0]["domain"] == ".google.com" and cks[0]["path"] == "/"
    assert cks[3]["url"] == "https://flow.google.com/" and "domain" not in cks[3]
    assert any("gán vào .google.com" in w for w in warns)
    assert has_session(cks, "flow")


def test_parse_cookie_editor_json():
    data = [
        {"domain": ".grok.com", "name": "sso", "value": "v", "sameSite": "no_restriction", "secure": False,
         "expirationDate": 1999999999.5, "hostOnly": False, "path": "/"},
        {"domain": "grok.com", "name": "x", "value": "y", "hostOnly": True, "sameSite": None, "session": True},
    ]
    cks, warns = parse(json.dumps(data), "grok")
    assert cks[0] == {"name": "sso", "value": "v", "secure": True, "httpOnly": False, "domain": ".grok.com",
                      "path": "/", "expires": 1999999999.5, "sameSite": "None"}
    assert cks[1]["url"] == "https://grok.com/" and "expires" not in cks[1]
    assert warns == []


def test_parse_warns_when_session_cookie_missing():
    cks, warns = parse('[{"domain": ".google.com", "name": "NID", "value": "1"}]', "flow")
    assert not has_session(cks, "flow")
    assert any("__Secure-1PSID" in w for w in warns)


@pytest.mark.parametrize("bad", ["", "   ", "[1]", "{không phải json", "[]", '[{"name": "a"}]'])
def test_parse_rejects_bad_input(bad):
    with pytest.raises(CookieError):
        parse(bad, "flow")


@pytest.fixture()
def engine(db, qapp, mock_site, home):
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"grok_image": mock_site, "grok_video": mock_site})
    eng = Engine(db)
    yield eng
    eng.shutdown()


def test_paste_cookies_loads_profile_checks_and_runs(db, engine, home, mock_site):
    """Dán cookie → nạp vào hồ sơ (cookie cũ của tên miền bị thay) → tự kiểm tra 'ok' → tác vụ chạy ẩn,
    không mở cửa sổ đăng nhập nào."""
    import asyncio
    aid = db.add_account("grok", "cookie", str(home / "pck"))
    acc = db.one("SELECT * FROM accounts WHERE id=?", (aid,))

    async def seed_old():
        ctx = await engine.browser.context(acc)
        await ctx.add_cookies([{"name": "sso", "value": "CU", "domain": ".grok.com", "path": "/"},
                               {"name": "keep", "value": "1", "domain": ".example.com", "path": "/"}])
    asyncio.run_coroutine_threadsafe(seed_old(), engine.loop).result(60)

    cks, _ = parse(json.dumps([
        {"domain": ".grok.com", "name": "sso", "value": "MOI", "expirationDate": 3_000_000_000},
        {"domain": ".grok.com", "name": "sso-rw", "value": "MOI2", "expirationDate": 3_000_000_000}]), "grok")
    engine.paste_cookies(acc, cks, mock_site).result(90)
    a = db.one("SELECT * FROM accounts WHERE id=?", (aid,))
    assert a["status"] == "ok" and a["last_check_at"]
    # Kiểm tra ghi lại hạn THẬT trong hồ sơ: Chrome giới hạn hạn cookie tối đa 400 ngày kể từ lúc nạp
    assert 399 * 86400 < a["cookie_expires"] - time.time() <= 400 * 86400 + 60
    assert not engine.browser._logins                       # không có cửa sổ đăng nhập nào

    async def read():
        ctx = await engine.browser.context(acc)
        return {c["name"]: c["value"] for c in await ctx.cookies(["https://grok.com/", "https://example.com/"])}
    got = asyncio.run_coroutine_threadsafe(read(), engine.loop).result(30)
    assert got["sso"] == "MOI" and got["sso-rw"] == "MOI2"   # cookie mới thay cookie cũ
    assert got["keep"] == "1"                               # tên miền khác không bị đụng

    bid = db.create_batch("grok", "grok_image", {}, str(home / "co"), "flat",
                          [{"mode": "t2i", "prompt": "sau khi dán cookie", "count": 1}])
    engine.start_page("grok_image", aid, 1, (0, 0))
    t = time.time()
    while time.time() - t < 60:
        row = db.one("SELECT * FROM jobs WHERE batch_id=?", (bid,))
        if row["status"] in ("done", "failed", "blocked", "cancelled"):
            break
        time.sleep(0.5)
    assert row["status"] == "done", row["error_text"]
    assert engine.browser_hidden(aid) is True


def _wait_job(db, bid, timeout=90):
    t = time.time()
    while time.time() - t < timeout:
        row = db.one("SELECT * FROM jobs WHERE batch_id=?", (bid,))
        if row["status"] in ("done", "failed", "blocked", "cancelled"):
            return row
        time.sleep(0.5)
    raise AssertionError(f"hết thời gian: {row['status']}")


def test_run_headless_real_browser_no_window(db, engine, home, monkeypatch):
    """Chạy ngầm hoàn toàn bằng Chrome/Edge thật (không cửa sổ): tạo xong ảnh; nút Hiện trình duyệt chỉ báo, không lỗi."""
    from videoai.browser import manager
    if not manager.find_browser_exe():
        pytest.skip("máy kiểm thử không có Chrome / Edge")
    monkeypatch.setattr(manager, "TEST_HEADLESS", False)
    db.set_setting("run_headless", True)
    aid = db.add_account("grok", "ngam", str(home / "pngam"))
    toasts = []
    engine.toast.connect(lambda k, m: toasts.append(m))
    bid = db.create_batch("grok", "grok_image", {}, str(home / "ngam_out"), "flat",
                          [{"mode": "t2i", "prompt": "chạy ngầm", "count": 1}])
    engine.start_page("grok_image", aid, 1, (0, 0))
    row = _wait_job(db, bid)
    assert row["status"] == "done", row["error_text"]
    assert engine.browser.is_headless(aid) is True
    engine.set_browser_visible(aid, True)                    # không có cửa sổ: chỉ báo, không ném lỗi
    from videoai.core.engine import HEADLESS_NO_WINDOW
    assert HEADLESS_NO_WINDOW in toasts


def test_headless_verify_stops_fast_instead_of_waiting(db, qapp, mock_site, home, monkeypatch):
    """Đang chạy ngầm mà trang bắt xác minh: tác vụ dừng ngay (không chờ 15 phút một cửa sổ không tồn tại),
    tài khoản chuyển 'cần xác minh'."""
    from videoai.core.engine import Engine
    db.set_setting("platform_urls", {"grok_image": mock_site.replace("index.html", "verify.html")})
    eng = Engine(db)
    try:
        aid = db.add_account("grok", "xacminh", str(home / "pxm"))
        monkeypatch.setattr(eng.browser, "is_headless", lambda _aid: True)
        bid = db.create_batch("grok", "grok_image", {}, str(home / "xm"), "flat",
                              [{"mode": "t2i", "prompt": "cần xác minh", "count": 1}])
        t0 = time.time()
        eng.start_page("grok_image", aid, 1, (0, 0))
        row = _wait_job(db, bid, 60)
        assert time.time() - t0 < 60
        assert row["status"] == "failed" and row["error_code"] == "needs_user", (row["status"], row["error_text"])
        assert "xác minh" in row["error_text"]
        assert db.one("SELECT status FROM accounts WHERE id=?", (aid,))["status"] == "needs_user"
        # mở hồ sơ của tài khoản bằng Google Chrome THƯỜNG (tiến trình chrome riêng, không gắn Playwright) ở đúng trang
        # cần xác minh, và không bị tự đóng vì "rảnh"
        t = time.time()
        while time.time() - t < 30 and not eng.browser.login_open(aid):
            time.sleep(0.3)
        assert eng.browser.login_open(aid) and eng.browser.is_verify_open(aid)
        proc = eng.browser._logins[aid]
        args = " ".join(map(str, proc.args))
        assert "verify.html" in args and f"--user-data-dir={home / 'pxm'}" in args
        assert not eng.browser.is_open(aid)                      # không còn Chrome do Playwright điều khiển
        time.sleep(3)
        assert proc.poll() is None                               # vẫn mở chờ người dùng
        # người dùng đóng cửa sổ → tools tự kiểm tra lại tài khoản (trang giả vẫn đòi xác minh → mở lại cửa sổ)
        proc.terminate()
        t = time.time()
        while time.time() - t < 40:
            p2 = eng.browser._logins.get(aid)
            if p2 is not None and p2 is not proc and p2.poll() is None:
                break
            time.sleep(0.5)
        assert p2 is not None and p2 is not proc, "không tự kiểm tra lại sau khi đóng cửa sổ xác minh"
        # từ giờ tài khoản này không chạy ngầm nữa (giấy qua cửa xác minh chỉ dùng được với Chrome thường)
        assert aid in db.get_setting("headed_accounts", [])
        assert eng._use_headless({"id": aid}) is False and eng._use_headless({"id": "khac"}) is True
    finally:
        eng.shutdown()


def test_cloudflare_challenge_detected_by_title_and_frame(qapp, mock_site, home):
    """Màn "Just a moment… / Verify you are human" của Cloudflare: chữ nằm trong iframe → nhận ra qua tiêu đề / khung."""
    import asyncio
    from playwright.async_api import async_playwright
    from videoai.adapters.chat import _challenge_page

    async def run():
        async with async_playwright() as p:
            b = await p.chromium.launch()
            pg = await b.new_page()
            await pg.set_content("<title>Just a moment...</title><div>chatgpt.com</div>")
            t1 = await _challenge_page(pg)
            await pg.set_content("<title>ChatGPT</title><iframe src='https://challenges.cloudflare.com/x'></iframe>")
            t2 = await _challenge_page(pg)
            await pg.set_content("<title>ChatGPT</title><textarea></textarea>")
            t3 = await _challenge_page(pg)
            await b.close()
            return t1, t2, t3
    assert asyncio.run(run()) == (True, True, False)


def test_only_google_chrome_never_edge_or_chromium(monkeypatch, tmp_path):
    """Tìm trình duyệt: chỉ Google Chrome. Máy chỉ có Edge → None (báo lỗi rõ), không lùi sang Edge / Chromium."""
    from videoai.browser import manager
    if os.name != "nt":
        pytest.skip("kiểm tra đường dẫn Windows")
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"")
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(tmp_path))
    import winreg
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert manager.find_browser_exe() is None
    chrome = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_bytes(b"")
    assert manager.find_browser_exe() == str(chrome)


def test_secret_roundtrip_and_db_cookie(db, home):
    from videoai.core.secret import decrypt, encrypt
    tok = encrypt("SID=bí mật")
    assert "bí mật" not in tok and decrypt(tok) == "SID=bí mật"
    assert decrypt("rác") == ""
    aid = db.add_account("flow", "a", str(home / "pa"))
    assert db.account_cookie(aid) == ""
    db.set_account_cookie(aid, '[{"name":"SID","value":"x"}]', 1999999999.0)
    row = db.one("SELECT cookie_enc, cookie_expires FROM accounts WHERE id=?", (aid,))
    assert "SID" not in row["cookie_enc"] and row["cookie_expires"] == 1999999999.0   # lưu mã hóa, không để chữ rõ
    assert db.account_cookie(aid) == '[{"name":"SID","value":"x"}]'


def test_session_expiry_and_describe():
    from videoai.core.cookies import describe_expiry, session_expiry
    cks = [{"name": "SID", "domain": ".google.com", "expires": 2_000_000_000},
           {"name": "__Secure-1PSID", "domain": ".google.com", "expires": 1_900_000_000},
           {"name": "NID", "domain": ".google.com", "expires": 1_000}]
    assert session_expiry(cks, "flow") == 1_900_000_000                     # hạn sớm nhất trong các cookie phiên
    assert session_expiry([{"name": "SID", "domain": ".google.com", "expires": -1}], "flow") is None
    assert session_expiry(cks, "muse") is None
    now = 1_800_000_000
    assert describe_expiry(None) == ("Không rõ", "unknown")
    assert describe_expiry(now + 30 * 86400, now)[1] == "ok" and "Còn 30 ngày" in describe_expiry(now + 30 * 86400, now)[0]
    assert describe_expiry(now + 3 * 86400, now)[1] == "soon"
    assert describe_expiry(now + 5 * 3600, now)[0].startswith("Còn 5 giờ")
    assert describe_expiry(now - 10, now)[1] == "expired"


def test_cookie_dialog_keeps_saved_cookie_and_shows_expiry(qapp):
    from videoai.ui.cookie_dialog import CookieDialog
    saved = json.dumps([{"domain": ".google.com", "name": "__Secure-1PSID", "value": "v", "expirationDate": 4_000_000_000}])
    dlg = CookieDialog({"id": "x", "label": "a@b", "platform": "flow"}, saved_text=saved, expires=4_000_000_000)
    assert dlg.edit.toPlainText() == saved                                   # khung nhập hiện lại cookie đã lưu
    assert "Còn" in dlg.exp_lbl.text()
    dlg._submit()
    assert dlg.result() == CookieDialog.Accepted
    assert dlg.text == saved and dlg.expires == 4_000_000_000
    assert dlg.edit.toPlainText() == saved                                   # không xóa sau khi nạp
    empty = CookieDialog({"id": "y", "label": "c", "platform": "flow"})
    assert "chưa có cookie" in empty.exp_lbl.text()
    empty.edit.setPlainText(json.dumps([{"domain": ".google.com", "name": "SID", "value": "1", "expirationDate": 4_100_000_000}]))
    assert "Còn" in empty.exp_lbl.text()                                    # dán xong thấy ngay hạn


def test_cookie_dialog_validates_and_returns_cookies(qapp):
    from videoai.ui.cookie_dialog import CookieDialog
    dlg = CookieDialog({"id": "x", "label": "a@b", "platform": "flow"})
    dlg.edit.setPlainText("{không hợp lệ")
    dlg._submit()
    assert dlg.result() != CookieDialog.Accepted and "JSON" in dlg.msg.text()
    dlg.edit.setPlainText("SID=1; __Secure-1PSID=2")
    dlg._submit()
    assert dlg.result() == CookieDialog.Accepted
    assert [c["name"] for c in dlg.cookies] == ["SID", "__Secure-1PSID"]
    assert dlg.text == "SID=1; __Secure-1PSID=2" and dlg.expires is None   # chuỗi header không mang hạn
