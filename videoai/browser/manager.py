"""Quản lý trình duyệt: mỗi tài khoản một hồ sơ Chrome riêng (giữ phiên đăng nhập).

Hai chế độ:
1. ĐĂNG NHẬP: mở Chrome bình thường (không ở chế độ điều khiển tự động) với hồ sơ của tài khoản, để
   người dùng tự đăng nhập như trên Chrome thường. Ứng dụng chỉ theo dõi địa chỉ trang qua cổng gỡ lỗi
   cục bộ; khi thấy đã đăng nhập thì tự đóng cửa sổ này.
2. CHẠY TÁC VỤ: Playwright mở cùng hồ sơ đó (đã có phiên đăng nhập). Cửa sổ được đặt ra ngoài màn hình
   (ẩn) nếu bật "Ẩn trình duyệt"; tự hiện lại khi trang cần người dùng xử lý (captcha, xác minh).

Không giả mạo dấu vân tay, không plugin vượt chặn bot. Mọi hàm async chạy trong vòng lặp của Engine.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Awaitable, Callable

from ..core import log
from ..core.errors import JobError

L = log.get("browser")

OFFSCREEN = (-32000, -32000)
# giữ trang chạy bình thường khi cửa sổ nằm ngoài màn hình (Chrome mặc định làm chậm cửa sổ bị che)
KEEP_ALIVE_ARGS = ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                   "--disable-background-timer-throttling"]
# (không thêm --disable-features: Chrome chỉ nhận cờ này 1 lần, sẽ đè danh sách tắt tính năng mặc định của Playwright)


def quiet_downloads(profile: Path):
    """Tắt bảng tải xuống tự bật lên của Chrome trong hồ sơ của tools (tải vẫn diễn ra bình thường, không hiện popup)."""
    import json
    f = profile / "Default" / "Preferences"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        dl = data.setdefault("download", {})
        bubble = data.setdefault("download_bubble", {})
        if dl.get("prompt_for_download") is False and bubble.get("partial_view_enabled") is False:
            return
        dl["prompt_for_download"] = False
        bubble["partial_view_enabled"] = False
        f.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
TEST_HEADLESS = os.environ.get("VIDEOAI_HEADLESS") == "1"


def find_browser_exe() -> str | None:
    """Tìm Chrome (ưu tiên) hoặc Edge đã cài trên máy."""
    cands = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands.append(Path(base) / "Google/Chrome/Application/chrome.exe")
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if base:
                cands.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            p = shutil.which(name)
            if p:
                cands.append(Path(p))
        cands.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for c in cands:
        if c.exists():
            return str(c)
    return None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class BrowserManager:
    def __init__(self, hide_default: Callable[[], bool] = lambda: True):
        self._pw = None
        self._contexts: dict[str, object] = {}   # account_id -> BrowserContext
        self._hidden: dict[str, bool] = {}
        self._lock = asyncio.Lock()
        self._claimed: set[int] = set()
        self._logins: dict[str, subprocess.Popen] = {}
        self.hide_default = hide_default

    async def _ensure_pw(self):
        if self._pw is None:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
        return self._pw

    # ================================================================ chạy tác vụ
    async def context(self, account: dict):
        async with self._lock:
            ctx = self._contexts.get(account["id"])
            if ctx is not None:
                try:
                    _ = ctx.pages  # còn sống?
                    return ctx
                except Exception:
                    self._contexts.pop(account["id"], None)
            await self._stop_login(account["id"])     # hồ sơ chỉ mở được một nơi
            pw = await self._ensure_pw()
            prof = Path(account["profile_dir"])
            prof.mkdir(parents=True, exist_ok=True)
            quiet_downloads(prof)
            hidden = bool(self.hide_default())
            args = list(KEEP_ALIVE_ARGS)
            if hidden:
                args += [f"--window-position={OFFSCREEN[0]},{OFFSCREEN[1]}", "--window-size=1366,900"]
            else:
                args += ["--start-maximized"]
            # khung trang cố định 1366x820: Flow luôn hiện giao diện máy tính (cửa sổ ẩn ngoài màn hình
            # có thể bị Windows thu nhỏ → Flow chuyển sang giao diện điện thoại, các nút khác hẳn)
            kwargs = dict(user_data_dir=str(prof), headless=TEST_HEADLESS, viewport={"width": 1366, "height": 820},
                          accept_downloads=True, args=args)
            last_err = None
            ctx = None
            for channel in ((None,) if TEST_HEADLESS else ("chrome", "msedge", None)):
                try:
                    if channel:
                        ctx = await pw.chromium.launch_persistent_context(channel=channel, **kwargs)
                    else:
                        ctx = await pw.chromium.launch_persistent_context(**kwargs)
                    L.info("Mở trình duyệt (%s, %s) cho %s", channel or "chromium", "ẩn" if hidden else "hiện", account["label"])
                    break
                except Exception as e:  # thử kênh tiếp theo
                    last_err = e
                    ctx = None
            if ctx is None:
                raise JobError("browser", str(last_err))
            ctx.on("close", lambda *_: (self._contexts.pop(account["id"], None), self._hidden.pop(account["id"], None)))
            self._contexts[account["id"]] = ctx
            self._hidden[account["id"]] = hidden
            return ctx

    async def new_page(self, account: dict, url: str):
        ctx = await self.context(account)
        async with self._lock:   # tránh hai tác vụ cùng lấy một tab trống
            pages = [p for p in ctx.pages if p.url in ("about:blank", "chrome://newtab/") and id(p) not in self._claimed]
            page = pages[0] if pages else await ctx.new_page()
            self._claimed.add(id(page))
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        return page

    async def set_visible(self, account_id: str, visible: bool, page=None):
        """Hiện / ẩn cửa sổ trình duyệt của tài khoản (đưa ra ngoài màn hình) mà không đóng phiên."""
        ctx = self._contexts.get(account_id)
        if ctx is None or TEST_HEADLESS:
            self._hidden[account_id] = not visible
            return
        try:
            page = page or (ctx.pages[0] if ctx.pages else await ctx.new_page())
            cdp = await ctx.new_cdp_session(page)
            win = await cdp.send("Browser.getWindowForTarget")
            wid = win["windowId"]
            if visible:
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"left": 60, "top": 40, "width": 1366, "height": 900}})
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "maximized"}})
                await page.bring_to_front()
            else:
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"left": OFFSCREEN[0], "top": OFFSCREEN[1]}})
            await cdp.detach()
            self._hidden[account_id] = not visible
        except Exception as e:
            L.warning("Không đổi được trạng thái cửa sổ: %s", e)

    def is_hidden(self, account_id: str) -> bool:
        return self._hidden.get(account_id, True)

    # ================================================================ đăng nhập
    async def login_session(self, account: dict, url: str, is_logged_in: Callable[[object], Awaitable[bool]],
                            timeout_s: int = 7200, wait_close: bool = True) -> str:
        """Mở Chrome thường để người dùng tự đăng nhập. Trả về 'ok' | 'closed' | 'timeout'.
        wait_close=True: KHÔNG tự đóng khi thấy đã đăng nhập – giữ cửa sổ tới khi người dùng tự đóng (để họ làm xong
        xác minh, đồng ý điều khoản…), trả về 'closed'; người gọi tự kiểm tra trạng thái sau đó."""
        await self.close_account(account["id"])
        await self._stop_login(account["id"])
        pw = await self._ensure_pw()
        exe = find_browser_exe() or pw.chromium.executable_path
        prof = Path(account["profile_dir"])
        prof.mkdir(parents=True, exist_ok=True)
        port = _free_port()
        args = [exe, f"--user-data-dir={prof}", f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
                "--no-first-run", "--no-default-browser-check", "--new-window", "--start-maximized"]
        if TEST_HEADLESS:
            args += ["--headless=new"]
        args.append(url)
        flags = 0x08000000 if os.name == "nt" else 0
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        self._logins[account["id"]] = proc
        L.info("Mở Chrome để %s đăng nhập (%s)", account["label"], Path(exe).name)
        browser = None
        try:
            for _ in range(60):          # chờ Chrome mở cổng gỡ lỗi
                await asyncio.sleep(0.5)
                if proc.poll() is not None:
                    return "closed"
                try:
                    browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=3000)
                    break
                except Exception:
                    continue
            if browser is None:
                return "closed"
            end = time.monotonic() + timeout_s
            seen = False
            while time.monotonic() < end:
                await asyncio.sleep(2.5)
                if proc.poll() is not None or not browser.is_connected():
                    return "closed"
                pages = [p for c in browser.contexts for p in c.pages]
                if wait_close:
                    if not pages:              # người dùng đã đóng hết cửa sổ (Chrome còn chạy nền)
                        if seen:
                            return "closed"
                    else:
                        seen = True
                    continue
                for c in browser.contexts:
                    for p in c.pages:
                        try:
                            if await is_logged_in(p):
                                await asyncio.sleep(2)          # để trang lưu xong cookie
                                return "ok"
                        except Exception:
                            pass
            return "timeout"
        finally:
            await self._close_login_browser(account["id"], browser)

    async def _close_login_browser(self, account_id: str, browser):
        proc = self._logins.pop(account_id, None)
        try:
            if browser is not None and browser.is_connected():
                s = await browser.new_browser_cdp_session()
                await s.send("Browser.close")
        except Exception:
            pass
        if proc is not None:
            for _ in range(20):
                if proc.poll() is not None:
                    break
                await asyncio.sleep(0.25)
            if proc.poll() is None:
                proc.terminate()

    async def _stop_login(self, account_id: str):
        proc = self._logins.pop(account_id, None)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            await asyncio.sleep(1)

    # ================================================================ đóng
    async def close_account(self, account_id: str):
        ctx = self._contexts.pop(account_id, None)
        self._hidden.pop(account_id, None)
        if ctx:
            try:
                await ctx.close()
            except Exception:
                pass

    async def close_all(self):
        for aid in list(self._contexts):
            await self.close_account(aid)
        for aid in list(self._logins):
            await self._stop_login(aid)
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def is_open(self, account_id: str) -> bool:
        return account_id in self._contexts
