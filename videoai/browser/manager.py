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
import sys
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
IS_MAC = sys.platform == "darwin"
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


MAC_IGNORE_ARGS = ["--use-mock-keychain"]


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
    if os.name == "nt":                       # Chrome cài ở chỗ khác: hỏi Windows (App Paths) chrome.exe nằm đâu
        try:
            import winreg
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for name in ("chrome.exe", "msedge.exe"):
                    try:
                        with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as k:
                            v = winreg.QueryValue(k, None)
                        if v:
                            cands.insert(0 if name == "chrome.exe" else len(cands), Path(v.strip('"')))
                    except OSError:
                        pass
        except Exception:
            pass
    for c in cands:
        if c.exists():
            return str(c)
    return None


def _profile_locked(prof: Path) -> bool:
    """Hồ sơ Chrome đang được một Chrome mở (Windows: tệp lockfile bị khóa · Mac/Linux: SingletonLock)."""
    if os.name == "nt":
        lf = prof / "lockfile"
        if not lf.exists():
            return False
        try:
            with open(lf, "a"):            # Chrome giữ tệp này độc quyền → mở không được nghĩa là đang bị giữ
                return False
        except OSError:
            return True
    return os.path.lexists(prof / "SingletonLock")


async def _cdp_targets(port: int):
    """Danh sách tab đang mở (chỉ hỏi qua HTTP, KHÔNG gắn vào trang); None nếu Chrome chưa / không còn mở cổng."""
    import json
    import urllib.request

    def get():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # máy cục bộ: bỏ qua proxy của máy
        with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            return [t for t in json.loads(r.read().decode("utf-8", "replace")) if t.get("type") == "page"]
    try:
        return await asyncio.to_thread(get)
    except Exception:
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
        self._login_gen: dict[str, int] = {}      # bấm "Mở để đăng nhập" lần nữa → lần mở cũ bị thay
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
            if self.login_open(account["id"]):
                # người dùng đang đăng nhập trong cửa sổ Chrome thường: KHÔNG tắt cửa sổ đó để chạy ẩn
                # (trước đây AI Agent / kiểm tra tài khoản mở ẩn → cửa sổ đăng nhập biến mất sau vài giây)
                raise JobError("login_open", account["label"])
            await self._stop_login(account["id"])     # hồ sơ chỉ mở được một nơi
            pw = await self._ensure_pw()
            prof = Path(account["profile_dir"])
            prof.mkdir(parents=True, exist_ok=True)
            quiet_downloads(prof)
            hidden = bool(self.hide_default())
            args = list(KEEP_ALIVE_ARGS)
            if hidden and IS_MAC:
                args += ["--window-size=1366,900"]          # macOS không cho cửa sổ nằm ngoài màn hình → thu nhỏ xuống Dock
            elif hidden:
                args += [f"--window-position={OFFSCREEN[0]},{OFFSCREEN[1]}", "--window-size=1366,900"]
            else:
                args += ["--start-maximized"]
            # khung trang cố định 1366x820: Flow luôn hiện giao diện máy tính (cửa sổ ẩn ngoài màn hình
            # có thể bị Windows thu nhỏ → Flow chuyển sang giao diện điện thoại, các nút khác hẳn)
            kwargs = dict(user_data_dir=str(prof), headless=TEST_HEADLESS, viewport={"width": 1366, "height": 820},
                          accept_downloads=True, args=args)
            if sys.platform == "darwin":
                # macOS: lúc đăng nhập Chrome mã hóa cookie bằng khóa trong Keychain thật; Playwright mặc định bật
                # Keychain giả → không giải mã được cookie → tài khoản đã đăng nhập vẫn báo "chưa đăng nhập".
                # Dùng Keychain thật như lúc đăng nhập (cùng ứng dụng Chrome nên macOS không hỏi lại).
                kwargs["ignore_default_args"] = MAC_IGNORE_ARGS
            last_err = None
            ctx = None
            # chạy ẩn bằng ĐÚNG trình duyệt đã dùng lúc đăng nhập (find_browser_exe). Trước đây thử kênh "chrome" rồi
            # "msedge" của Playwright: máy khách cài Chrome ở chỗ Playwright không tìm thấy (cài riêng cho người dùng…)
            # → chạy ẩn bằng Edge / Chromium, không đọc được cookie Chrome đã mã hóa → mới cài luôn báo "chưa đăng nhập"
            exe = None if TEST_HEADLESS else (find_browser_exe() or pw.chromium.executable_path)
            for channel in ((None,) if TEST_HEADLESS else (["exe"] if exe else []) + ["chrome", "msedge", None]):
                try:
                    if channel == "exe":
                        ctx = await pw.chromium.launch_persistent_context(executable_path=exe, **kwargs)
                    elif channel:
                        ctx = await pw.chromium.launch_persistent_context(channel=channel, **kwargs)
                    else:
                        ctx = await pw.chromium.launch_persistent_context(**kwargs)
                    L.info("Mở trình duyệt (%s, %s) cho %s", Path(exe).name if channel == "exe" else (channel or "chromium"), "ẩn" if hidden else "hiện", account["label"])
                    break
                except Exception as e:  # thử kênh tiếp theo
                    last_err = e
                    ctx = None
            if ctx is None:
                raise JobError("browser", str(last_err))
            ctx.on("close", lambda *_: (self._contexts.pop(account["id"], None), self._hidden.pop(account["id"], None)))
            self._contexts[account["id"]] = ctx
            self._hidden[account["id"]] = hidden
            if hidden and IS_MAC and not TEST_HEADLESS:
                for pg in list(ctx.pages):
                    await self._minimize(ctx, pg)
            return ctx

    async def new_page(self, account: dict, url: str):
        ctx = await self.context(account)
        async with self._lock:   # tránh hai tác vụ cùng lấy một tab trống
            pages = [p for p in ctx.pages if p.url in ("about:blank", "chrome://newtab/") and id(p) not in self._claimed]
            page = pages[0] if pages else await ctx.new_page()
            self._claimed.add(id(page))
        if IS_MAC and self._hidden.get(account["id"], True) and not TEST_HEADLESS:
            await self._minimize(ctx, page)            # tab / cửa sổ mới trên Mac cũng thu nhỏ luôn
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except Exception as e:
            # trang tự chuyển hướng ngay khi mở (vd. muse.ai → trang đăng nhập) → Chrome báo ERR_ABORTED dù trang vẫn mở
            if "ERR_ABORTED" not in str(e) and "interrupted by another navigation" not in str(e):
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:
                pass
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
            elif IS_MAC:
                await cdp.detach()
                await self._minimize(ctx, page)
                self._hidden[account_id] = True
                return
            else:
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"left": OFFSCREEN[0], "top": OFFSCREEN[1]}})
            await cdp.detach()
            self._hidden[account_id] = not visible
        except Exception as e:
            L.warning("Không đổi được trạng thái cửa sổ: %s", e)

    async def _minimize(self, ctx, page):
        """macOS: giấu cửa sổ Chrome. Thử đẩy ra ngoài màn hình (trang vẫn vẽ bình thường như trên Windows);
        nếu macOS kéo cửa sổ vào lại màn hình thì thu nhỏ xuống Dock."""
        try:
            cdp = await ctx.new_cdp_session(page)
            wid = (await cdp.send("Browser.getWindowForTarget"))["windowId"]
            await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
            await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"left": OFFSCREEN[0], "top": OFFSCREEN[1]}})
            b = (await cdp.send("Browser.getWindowBounds", {"windowId": wid})).get("bounds", {})
            if b.get("left", 0) > -5000 and b.get("top", 0) > -5000:
                await cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
                L.info("macOS: thu nhỏ cửa sổ trình duyệt xuống Dock")
            await cdp.detach()
        except Exception as e:
            L.warning("Không giấu được cửa sổ trình duyệt: %s", e)

    def login_open(self, account_id: str) -> bool:
        """Cửa sổ Chrome đăng nhập của tài khoản còn đang mở?"""
        proc = self._logins.get(account_id)
        return proc is not None and proc.poll() is None

    def is_hidden(self, account_id: str) -> bool:
        return self._hidden.get(account_id, True)

    # ================================================================ đăng nhập
    async def login_session(self, account: dict, url: str, is_logged_in: Callable[[object], Awaitable[bool]],
                            timeout_s: int = 7200, wait_close: bool = True) -> str:
        """Mở Chrome THƯỜNG để người dùng tự đăng nhập. Trả về 'ok' | 'closed' | 'timeout'.
        wait_close=True (mặc định): giữ cửa sổ tới khi người dùng tự đóng rồi trả 'closed' (người gọi tự kiểm tra).
          · KHÔNG gắn công cụ điều khiển vào trang (chỉ hỏi danh sách tab qua cổng gỡ lỗi) → trang đăng nhập (Google,
            Chat GPT / Cloudflare) thấy đây là Chrome bình thường, ít bị bắt kiểm tra robot.
          · hồ sơ tài khoản còn bị một Chrome khác giữ (Chrome ẩn của tools chưa tắt hẳn) → Chrome mới chỉ chuyển trang
            sang cửa sổ cũ rồi tự thoát, người dùng không thấy gì: tự tắt Chrome đang giữ hồ sơ rồi mở lại."""
        gen = self._login_gen[account["id"]] = self._login_gen.get(account["id"], 0) + 1
        await self.close_account(account["id"])
        await self._stop_login(account["id"])
        pw = await self._ensure_pw()
        exe = find_browser_exe() or pw.chromium.executable_path
        prof = Path(account["profile_dir"])
        prof.mkdir(parents=True, exist_ok=True)
        await self._free_profile(prof)
        proc, port = None, 0
        for attempt in range(2):
            port = _free_port()
            args = [exe, f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
                    "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check",
                    "--new-window", "--window-position=40,30", "--window-size=1366,900", "--start-maximized"]
            # vị trí cửa sổ ghi rõ: Chrome ẩn của tools lưu vị trí ngoài màn hình (-32000) vào hồ sơ, nếu không ghi
            # thì cửa sổ đăng nhập mở lại đúng chỗ đó → người dùng không thấy cửa sổ
            if TEST_HEADLESS:
                args += ["--headless=new"]
            args.append(url)
            flags = 0x08000000 if os.name == "nt" else 0
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            if self._login_gen.get(account["id"]) != gen:      # đã có lần mở mới hơn
                proc.terminate()
                return "replaced"
            self._logins[account["id"]] = proc
            L.info("Mở Chrome để %s đăng nhập (%s)", account["label"], Path(exe).name)
            ok = False
            for _ in range(40):                     # chờ Chrome mở cổng gỡ lỗi (= cửa sổ của chính nó đã lên)
                await asyncio.sleep(0.5)
                if await _cdp_targets(port) is not None:
                    ok = True
                    break
                if proc.poll() is not None:
                    break
            if ok:
                break
            L.warning("Chrome đăng nhập không tự mở được cửa sổ (hồ sơ đang bị Chrome khác giữ) – tắt Chrome đó rồi mở lại")
            await self._free_profile(prof, force=True)
        else:
            return "closed"
        if not wait_close:
            return await self._login_poll_cdp(account, pw, port, proc, is_logged_in, timeout_s)
        try:
            end = time.monotonic() + timeout_s
            seen = False
            miss = empty = 0
            while time.monotonic() < end:
                await asyncio.sleep(1.5)
                if self._login_gen.get(account["id"]) != gen:  # người dùng bấm mở lại: lần mới lo tiếp
                    return "replaced"
                if proc.poll() is not None:
                    return "closed"
                pages = await _cdp_targets(port)
                if pages is None:                   # cổng không trả lời: Chrome đang thoát HOẶC trang đăng nhập đang tải nặng
                    miss += 1
                    if miss >= 4:                   # ~10 giây liền không trả lời mới coi là đã đóng
                        return "closed"
                    continue
                miss = 0
                if pages:
                    seen, empty = True, 0
                elif seen:                          # không còn tab nào (trên Mac Chrome còn chạy nền)
                    empty += 1
                    if empty >= 2:
                        return "closed"
            return "timeout"
        finally:
            if self._login_gen.get(account["id"]) == gen:
                browser = None
                if proc.poll() is None:
                    # Chrome còn chạy (Mac giữ Chrome sau khi đóng cửa sổ / hết giờ): yêu cầu Chrome tự thoát êm
                    # (Browser.close) để cookie đăng nhập được ghi xuống đĩa, không tắt cưỡng bức
                    try:
                        browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=5000)
                    except Exception:
                        browser = None
                await self._close_login_browser(account["id"], browser)

    async def _login_poll_cdp(self, account, pw, port, proc, is_logged_in, timeout_s) -> str:
        """Chế độ cũ (wait_close=False): gắn vào trang để tự nhận biết đăng nhập xong rồi đóng."""
        browser = None
        try:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=5000)
            end = time.monotonic() + timeout_s
            while time.monotonic() < end:
                await asyncio.sleep(2.5)
                if proc.poll() is not None or not browser.is_connected():
                    return "closed"
                for c in browser.contexts:
                    for p in c.pages:
                        try:
                            if await is_logged_in(p):
                                await asyncio.sleep(2)
                                return "ok"
                        except Exception:
                            pass
            return "timeout"
        except Exception:
            return "closed"
        finally:
            await self._close_login_browser(account["id"], browser)

    async def _free_profile(self, prof: Path, force: bool = False):
        """Tắt mọi Chrome đang mở hồ sơ tài khoản này (hồ sơ riêng của tools – không đụng Chrome của người dùng)."""
        key = str(prof)
        try:
            if os.name == "nt":
                ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | "
                      "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($env:VAI_PROF) } | "
                      "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
                cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
                env = dict(os.environ, VAI_PROF=f"--user-data-dir={key}")
                flags = 0x08000000
            else:
                cmd = ["pkill", "-f", "--", f"--user-data-dir={key}"]
                env, flags = None, 0
            if not force and not _profile_locked(prof):
                return
            r = await asyncio.to_thread(subprocess.run, cmd, env=env, capture_output=True, timeout=20, creationflags=flags)
            L.info("Đã tắt Chrome đang giữ hồ sơ %s (mã %s)", prof.name, r.returncode)
            for _ in range(20):
                if not _profile_locked(prof):
                    break
                await asyncio.sleep(0.25)
        except Exception as e:
            L.warning("Không tắt được Chrome đang giữ hồ sơ: %s", e)

    async def _close_login_browser(self, account_id: str, browser):
        proc = self._logins.pop(account_id, None)
        try:
            if browser is not None and browser.is_connected():
                s = await browser.new_browser_cdp_session()
                await s.send("Browser.close")
        except Exception:
            pass
        if proc is not None:
            # chờ Chrome tự thoát hẳn: lúc thoát Chrome mới ghi cookie đăng nhập xuống đĩa – tắt cưỡng bức sớm
            # (trước đây sau 5 giây) làm mất phiên vừa đăng nhập → lần đầu luôn báo "chưa đăng nhập"
            for _ in range(80):
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
