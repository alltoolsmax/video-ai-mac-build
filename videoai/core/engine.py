"""Bộ chạy tác vụ: một luồng riêng với vòng lặp asyncio, điều khiển trình duyệt qua adapter.

Giao diện gọi các hàm public (an toàn từ luồng UI). Engine phát tín hiệu Qt để giao diện cập nhật.
Quy tắc:
- Mỗi trang chạy trên MỘT tài khoản do người dùng chọn; không tự đổi tài khoản khi hết lượt.
- "Số hàng tạo đồng thời" = số tab cùng lúc trong tài khoản đó (giới hạn tối đa trong Cài Đặt).
- Gặp captcha/đăng xuất: tạm dừng tác vụ đó, đưa cửa sổ lên, chờ người dùng.
"""
from __future__ import annotations

import asyncio
import os
import json
import random
import re
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import log
from .db import Database, now
from .errors import JobError, friendly
from .platforms import PAGE_BY_KEY
from ..adapters.base import WebAdapter
from ..adapters.flow import FlowAdapter


def make_adapter(platform: str, url: str):
    if platform == "flow":
        return FlowAdapter(platform, url)
    u = (url or "").lower()
    if platform == "gpt" and ("chatgpt.com" in u or "/gpt/" in u or not u):
        from ..adapters.gpt import GptAdapter
        return GptAdapter(platform, url)
    if platform == "muse" and ("muse.ai" in u or "/muse/" in u or not u):
        from ..adapters.muse import MuseAdapter
        return MuseAdapter(platform, url)
    if platform == "grok" and ("grok.com" in u or "/grok/" in u or not u):
        from ..adapters.grok import GrokAdapter
        return GrokAdapter(platform, url)
    return WebAdapter(platform, url)
from ..browser.manager import BrowserManager

L = log.get("engine")


def slugify(text: str, n: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return (t[:n] or "prompt").rstrip("_")


# lỗi kỹ thuật: được thử lại trên tài khoản khác (nếu bật tự chuyển). "blocked" (vi phạm nội dung) thì KHÔNG.
# v2.1.12: bỏ "download" – video đã tạo xong mà tải lỗi thì KHÔNG tạo lại trên tài khoản khác (tốn tín dụng, dồn nhiều
# lượt tạo trong thời gian ngắn → Google dễ báo "hoạt động bất thường")
FAILOVER_CODES = {"quota", "not_logged_in", "timeout", "ui_changed", "browser", "unknown", "needs_user"}
FLAG_COOLDOWN_S = 2 * 3600            # tài khoản bị báo "hoạt động bất thường": nghỉ 2 giờ (lưu lại, mở lại tools vẫn nhớ)
# lỗi làm tài khoản không dùng được tiếp trong lần chạy này
ACCOUNT_DOWN_CODES = {"quota", "not_logged_in", "browser", "needs_user", "flagged"}


class PageRun:
    """Một trang đang chạy trên một hoặc nhiều tài khoản của người dùng (mỗi tài khoản một trình duyệt)."""

    def __init__(self, page_key: str, account_ids: list[str], concurrency: int, delay: tuple[int, int],
                 failover: bool = True):
        self.page_key = page_key
        self.account_ids = list(dict.fromkeys(account_ids))
        self.concurrency = max(1, concurrency)          # số hàng đồng thời MỖI tài khoản
        self.delay = delay
        self.failover = failover
        self.tasks: dict[asyncio.Task, str] = {}         # task -> account_id
        self.tabs: dict[str, list] = {}                  # account_id -> tab rảnh
        self.down: dict[str, str] = {}                   # account_id -> mã lỗi (tạm ngưng trong lần chạy)
        self.tried: dict[str, set[str]] = {}             # job_id -> các tài khoản đã thử
        self.active = True
        self.auto_platform: str | None = None             # tự lấy mọi tài khoản sẵn sàng của nền tảng này

    def usable(self) -> list[str]:
        return [a for a in self.account_ids if a not in self.down]

    def busy(self, aid: str) -> int:
        return sum(1 for t, a in self.tasks.items() if a == aid and not t.done())

    @property
    def account_id(self) -> str | None:   # tương thích cũ
        return self.account_ids[0] if self.account_ids else None


class Engine(QObject):
    job_updated = Signal(str)               # job_id
    page_state = Signal(str, str)           # page_key, running|paused|stopped|idle
    toast = Signal(str, str)                # kind(info|ok|warn|error), message
    account_updated = Signal(str)           # account_id

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.browser = BrowserManager(lambda: True)          # luôn ẩn trình duyệt (chỉ hiện khi cần người dùng đăng nhập / xác minh)
        self.runs: dict[str, PageRun] = {}
        self.max_total = 0          # >0: tổng số tác vụ chạy cùng lúc tối đa (gói Miễn phí = 1)
        self.close_when_idle = os.environ.get("VIDEOAI_KEEP_BROWSERS") != "1"  # chạy xong hàng đợi / AI Agent trả lời xong → đóng trình duyệt ẩn của tài khoản
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._thread_main, name="engine", daemon=True)
        self._thread.start()

    # ================= public (luồng UI) =================
    def start_page(self, page_key: str, account_ids, concurrency: int, delay: tuple[int, int], failover: bool = True):
        if isinstance(account_ids, str):
            account_ids = [account_ids]
        self._call(self._start_page(page_key, list(account_ids), concurrency, delay, failover))

    def pause_page(self, page_key: str):
        self._call(self._pause_page(page_key))

    def stop_page(self, page_key: str):
        self._call(self._stop_page(page_key))

    def open_login(self, account: dict, url: str):
        self._call(self._open_login(account, url))

    def check_account(self, account: dict, url: str):
        self._call(self._check_account(account, url))

    def close_account_browser(self, account_id: str):
        self._call(self.browser.close_account(account_id))

    def set_browser_visible(self, account_id: str, visible: bool):
        self._call(self.browser.set_visible(account_id, visible))

    def browser_hidden(self, account_id: str) -> bool:
        return self.browser.is_hidden(account_id)

    def is_running(self, page_key: str) -> bool:
        r = self.runs.get(page_key)
        return bool(r and r.active)

    def ask_ai(self, account: dict, system: str, user: str, timeout_s: int = 240, on_status=None, files=None,
               check=None, want_json: bool = False):
        """AI Agent qua tài khoản đã đăng nhập: trả về Future (gọi .result() ở luồng nền). files: ảnh đính kèm.
        check(ans) báo ValueError khi sai định dạng → AI được nhắc sửa trong cùng cuộc chat."""
        return self._call(self._ask_ai(account, system, user, timeout_s, on_status, files, check, want_json))

    def flow_voice_preview(self, account: dict, voice: str, text: str, on_status=None):
        """Nghe thử giọng Flow với câu thoại của người dùng (chạy trên tài khoản Flow) → Future[bytes âm thanh]."""
        return self._call(self._flow_voice_preview(account, voice, text, on_status))

    async def _flow_voice_preview(self, account, voice, text, on_status):
        from ..adapters.flow import FlowAdapter
        url = self._url_for("flow_video")
        ad = FlowAdapter("flow", url)
        ad.terms_ok = bool(self.db.get_setting("flow_terms_ok", False))
        page = await self.browser.new_page(account, url)
        try:
            return await ad.voice_preview(page, voice, text, on_status)
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await self.close_if_idle(account["id"])

    async def _ask_ai(self, account, system, user, timeout_s, on_status, files=None, check=None, want_json=False):
        from ..adapters import chat
        url = (self.db.get_setting("ai_chat_urls", {}) or {}).get(account["platform"]) or chat.SITES[account["platform"]][1]
        page = await self.browser.new_page(account, url)

        async def on_verify(show: bool):
            # trang hỏi "Verify you are human": hiện cửa sổ để người dùng TỰ tick, xong thì ẩn lại
            if show:
                self.toast.emit("warn", f"{account['label']}: Chat GPT cần xác minh – hãy tick ô xác minh trong cửa sổ "
                                        "Chrome vừa hiện, tools sẽ tự chạy tiếp.")
            try:
                await self.browser.set_visible(account["id"], show, page)
            except Exception:
                pass
        try:
            return await chat.ask(page, account["platform"], system, user, timeout_s, on_status, url=url, files=files,
                                  check=check, want_json=want_json, on_verify=on_verify)
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await self.close_if_idle(account["id"])

    def shutdown(self):
        fut = asyncio.run_coroutine_threadsafe(self.browser.close_all(), self.loop)
        try:
            fut.result(timeout=10)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)

    # ================= nội bộ =================
    def _call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _thread_main(self):
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._scheduler())
        self.loop.run_forever()

    def _url_for(self, page_key: str) -> str:
        pdef = PAGE_BY_KEY[page_key]
        urls = self.db.get_setting("platform_urls", {}) or {}
        u = urls.get(page_key) or pdef.url
        if "labs.google/fx/tools/flow" in u:   # địa chỉ cũ của Flow
            u = pdef.url
        return u

    async def _start_page(self, page_key, account_ids, concurrency, delay, failover=True):
        r = self.runs.get(page_key)
        if r and r.tasks:      # đang chạy: cập nhật danh sách tài khoản, giữ tab cũ
            for a in account_ids:
                if a not in r.account_ids:
                    r.account_ids.append(a)
            r.active, r.concurrency, r.delay, r.failover = True, max(1, concurrency), delay, failover
            r.down = {}
        else:
            old_tabs = r.tabs if r else {}
            r = PageRun(page_key, account_ids, concurrency, delay, failover)
            r.tabs = old_tabs
            self.runs[page_key] = r
        for a in self.flag_cooled(r.account_ids):     # tài khoản đang nghỉ vì "hoạt động bất thường"
            r.down[a] = "flagged"
        if page_key.startswith("flow_"):
            r.auto_platform = PAGE_BY_KEY[page_key].platform
        self.page_state.emit(page_key, "running")
        if r.auto_platform:
            self._refresh_accounts(r)
        n_q = self.db.one("SELECT COUNT(*) n FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.page=? AND j.status='queued'",
                          (page_key,))
        n_q = n_q["n"] if n_q else 0
        L.info("Bắt đầu %s: %d tác vụ chờ · %d tài khoản đang đăng nhập → chạy cùng lúc %d tác vụ "
               "(1 tác vụ / 1 tài khoản, xong nghỉ %s–%s giây rồi nhận tác vụ kế, tự chuyển tài khoản khi lỗi: %s)",
               page_key, n_q, len(r.usable()), min(n_q, len(r.usable())) if self.max_total == 0 else min(1, n_q),
               *delay, "bật" if failover else "tắt")

    async def _pause_page(self, page_key):
        r = self.runs.get(page_key)
        if r:
            r.active = False
        self.page_state.emit(page_key, "paused")
        L.info("Tạm dừng %s (tác vụ đang chạy sẽ làm xong)", page_key)

    async def _stop_page(self, page_key):
        r = self.runs.get(page_key)
        if r:
            r.active = False
            for t in list(r.tasks):
                t.cancel()
        pdef = PAGE_BY_KEY[page_key]
        rows = self.db.query(
            "SELECT j.id FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.page=? AND j.status IN ('queued','running','needs_user')",
            (page_key,))
        for row in rows:
            self.db.update_job(row["id"], status="cancelled", progress=0)
            self.job_updated.emit(row["id"])
        self.page_state.emit(page_key, "stopped")
        if r:
            self.loop.create_task(self._close_idle(r, wait=3))
        L.info("Dừng %s, hủy %d tác vụ (%s)", page_key, len(rows), pdef.label)

    async def _open_login(self, account, url):
        """Mở Chrome thường để người dùng tự đăng nhập. Cửa sổ giữ nguyên tới khi người dùng TỰ ĐÓNG,
        rồi tools tự kiểm tra trạng thái (chạy ẩn). Các tác vụ sau dùng lại phiên đăng nhập trong cửa sổ ẩn."""
        try:
            ad = make_adapter(account["platform"], url)
            self.toast.emit("info", f"Đã mở Chrome cho {account['label']}. Đăng nhập xong hãy ĐÓNG cửa sổ Chrome – "
                                    "tools sẽ tự kiểm tra trạng thái.")
            self.db.update_account(account["id"], status="needs_user")
            self.account_updated.emit(account["id"])
            login_url = "https://chatgpt.com/" if account["platform"] == "gpt" else (ad.url or url)   # trang chính Chat GPT
            res = await self.browser.login_session(account, login_url, ad.is_logged_in)
            if res == "replaced":              # người dùng đã bấm mở lại: lần mở mới sẽ tự kiểm tra
                return
            if res == "timeout":
                self.toast.emit("warn", f"{account['label']}: cửa sổ đăng nhập mở quá lâu nên đã được đóng – đang kiểm tra…")
            await asyncio.sleep(1)
            await self._check_account(account, url, retry=True)
        except Exception as e:
            L.exception("open_login")
            self.toast.emit("error", friendly(getattr(e, "code", "browser")))

    async def _check_account(self, account, url, retry: bool = False):
        page = None
        try:
            ad = make_adapter(account["platform"], url)
            page = await self.browser.new_page(account, url)
            status = await ad.check_login(page)
            if retry and status in ("expired", "unknown"):
                # vừa đăng nhập lần đầu: trang có thể còn chuyển hướng / màn chào → tải lại và kiểm tra thêm 1 lần
                L.info("Kiểm tra %s: %s – kiểm tra lại sau vài giây", account["label"], status)
                await asyncio.sleep(5)
                try:
                    await page.goto(ad.url or url, wait_until="domcontentloaded", timeout=90_000)
                except Exception:
                    pass
                status = await ad.check_login(page)
            if status == "unknown" and await ad.has_login_cookie(page):
                status = "ok"                    # có phiên đăng nhập, chỉ là giao diện đang có màn chào / hộp thoại
            credits = await ad.read_credits(page)
            self.db.update_account(account["id"], status=status, credits_left=credits, last_check_at=now())
            self.account_updated.emit(account["id"])
            self.toast.emit("ok" if status == "ok" else "warn",
                            f"{account['label']}: " + {"ok": "đã đăng nhập", "expired": "chưa đăng nhập",
                                                        "needs_user": "cần xác minh trong trình duyệt",
                                                        "unknown": "chưa xác định được (kiểm tra selector)"}[status])
        except Exception as e:
            L.exception("check_account")
            row = self.db.one("SELECT status FROM accounts WHERE id=?", (account["id"],))
            if row and row["status"] == "needs_user":
                self.db.update_account(account["id"], status="unknown", last_check_at=now())
                self.account_updated.emit(account["id"])
            self.toast.emit("error", friendly(getattr(e, "code", "browser")))
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
                await self.close_if_idle(account["id"])

    async def _scheduler(self):
        while True:
            try:
                for key, r in list(self.runs.items()):
                    r.tasks = {t: a for t, a in r.tasks.items() if not t.done()}
                    if not r.active:
                        continue
                    if r.auto_platform:
                        self._refresh_accounts(r)
                    usable = r.usable()
                    if not usable:
                        if not r.tasks:
                            r.active = False
                            self.page_state.emit(key, "paused")
                            self.toast.emit("error", f"{PAGE_BY_KEY[key].label}: không còn tài khoản nào dùng được "
                                                     f"(hết tín dụng / chưa đăng nhập). Hàng đợi đã tạm dừng.")
                        continue
                    # mỗi tài khoản = 1 trình duyệt = tối đa r.concurrency tác vụ, tính chung mọi trang
                    # (ảnh + video) để 2 tác vụ không bao giờ dồn vào cùng một tài khoản
                    slots = [(a, r.concurrency - self._busy_all(a)) for a in usable]
                    free = sum(max(0, n) for _, n in slots)
                    if self.max_total:
                        running_all = sum(1 for rr in self.runs.values() for t in rr.tasks if not t.done())
                        free = min(free, max(0, self.max_total - running_all))
                    queued = []
                    if free > 0:
                        queued = self.db.query(
                            "SELECT j.*, b.save_dir, b.save_mode, b.params AS batch_params, b.created_at AS batch_at"
                            " FROM jobs j JOIN batches b ON b.id=j.batch_id"
                            " WHERE b.page=? AND j.status='queued' ORDER BY b.created_at, j.row_no LIMIT ?",
                            (key, free + 50))
                        queued = [j for j in queued if not self._waiting_chain(j)][:free]
                    if not queued and not r.tasks and free <= 0:
                        # mọi tài khoản đang bận ở trang khác: chỉ dừng khi thật sự hết hàng chờ
                        left = self.db.one("SELECT COUNT(*) n FROM jobs j JOIN batches b ON b.id=j.batch_id"
                                           " WHERE b.page=? AND j.status='queued'", (key,))
                        if left and left["n"]:
                            continue
                    if not queued and not r.tasks:
                        r.active = False
                        self.page_state.emit(key, "idle")
                        self.loop.create_task(self._close_idle(r))
                        self.toast.emit("ok", f"{PAGE_BY_KEY[key].label}: đã chạy xong hàng đợi.")
                        continue
                    # chia đều, ưu tiên tài khoản chưa thử hàng này và đang rảnh nhất
                    free_slots = {a: n for a, n in slots if n > 0}
                    for job in queued:
                        cands = [a for a, n in free_slots.items() if n > 0]
                        if not cands:
                            break
                        tried = r.tried.get(job["id"], set())
                        aid = min(cands, key=lambda a: (a in tried, self._busy_all(a) + (r.concurrency - free_slots[a]),
                                                        r.account_ids.index(a)))
                        free_slots[aid] -= 1
                        self.db.update_job(job["id"], status="running", progress=0, started_at=now(),
                                           account_id=aid)
                        self.job_updated.emit(job["id"])
                        t = self.loop.create_task(self._run_job(r, job, aid))
                        r.tasks[t] = aid
            except Exception:
                L.exception("scheduler")
            await asyncio.sleep(1.0)

    def _chain_prev(self, job: dict) -> dict | None:
        """Nối cảnh liền mạch: tác vụ của cảnh trước trong cùng kịch bản (khung cuối của nó = khung đầu tác vụ này)."""
        try:
            p = json.loads(job["params"] or "{}")
        except Exception:
            return None
        if not p.get("chain") or not p.get("script_id") or int(p.get("scene") or 1) <= 1:
            return None
        want = int(p["scene"]) - 1
        rows = self.db.query("SELECT * FROM jobs WHERE params LIKE ? ORDER BY created_at DESC",
                             (f'%"script_id": "{p["script_id"]}"%',))
        rows.sort(key=lambda r: r["batch_id"] != job["batch_id"])     # ưu tiên cùng lô
        for r in rows:
            try:
                if int(json.loads(r["params"] or "{}").get("scene") or 0) == want:
                    return r
            except Exception:
                continue
        return None

    def _waiting_chain(self, job: dict) -> bool:
        pj = self._chain_prev(job)
        return bool(pj and pj["status"] in ("queued", "running", "needs_user"))

    def _in_use(self, aid: str, skip=None) -> bool:
        """Tài khoản còn đang được dùng: có tác vụ đang chạy, hoặc thuộc một trang đang chạy hàng đợi."""
        if self._busy_all(aid):
            return True
        return any(rr is not skip and rr.active and aid in rr.account_ids for rr in self.runs.values())

    async def close_if_idle(self, aid: str, skip=None):
        if self.close_when_idle and not self._in_use(aid, skip):
            for rr in self.runs.values():
                for tab in rr.tabs.pop(aid, []):
                    try:
                        await tab.close()
                    except Exception:
                        pass
            await self.browser.close_account(aid)

    async def _close_idle(self, r: PageRun, wait: float = 1.5):
        """Tạo xong và đã lưu kết quả → đóng trình duyệt ẩn của các tài khoản không còn việc."""
        if not self.close_when_idle:
            return
        await asyncio.sleep(wait)
        if r.active:
            return
        for aid in set(r.account_ids) | set(r.tabs):
            await self.close_if_idle(aid, skip=r)
        L.info("%s: đã xong, đóng trình duyệt ẩn", PAGE_BY_KEY[r.page_key].label)

    def _busy_all(self, aid: str) -> int:
        return sum(r.busy(aid) for r in self.runs.values())

    def _refresh_accounts(self, r: PageRun):
        rows = [a for a in self.db.accounts(r.auto_platform) if a["enabled"]
                and a["status"] in ("ok", "unknown", "needs_user")]
        ids = [a["id"] for a in rows]
        for a in ids:
            if a not in r.account_ids:
                r.account_ids.append(a)
                L.info("%s: thêm tài khoản %s vào hàng chạy", PAGE_BY_KEY[r.page_key].label,
                       next(x["label"] for x in rows if x["id"] == a))
        for a in list(r.account_ids):   # tài khoản bị tắt/xóa: không nhận tác vụ mới
            if a not in ids and not r.busy(a) and a not in r.down:
                r.account_ids.remove(a)
        for a in self.flag_cooled(r.account_ids):
            r.down.setdefault(a, "flagged")

    async def _get_tab(self, r: PageRun, account: dict, url: str):
        pool = r.tabs.setdefault(account["id"], [])
        while pool:
            tab = pool.pop()
            if not tab.is_closed():
                return tab
        return await self.browser.new_page(account, url)

    async def _run_job(self, r: PageRun, job: dict, account_id: str):
        jid = job["id"]
        pdef = PAGE_BY_KEY[r.page_key]
        account = self.db.one("SELECT * FROM accounts WHERE id=?", (account_id,))
        tab = None
        try:
            if not account:
                raise JobError("no_account")
            url = self._url_for(r.page_key)
            params = {**json.loads(job["batch_params"] or "{}"), **json.loads(job["params"] or "{}")}
            params["flow_rights_ok"] = bool(self.db.get_setting("flow_rights_ok", False))   # đã xác nhận quyền sử dụng tệp tải lên
            params["flow_terms_ok"] = bool(self.db.get_setting("flow_terms_ok", False))     # đã đồng ý điều khoản Google khi lần đầu vào Flow
            refs = [p for p in json.loads(job["refs"] or "[]") if Path(p).exists()]
            pj = self._chain_prev(job)
            if pj is not None:
                job = await self._apply_chain(job, pj, params)
                refs = json.loads(job["refs"] or "[]")
            mode = next((m for m in pdef.modes if m.key == job["mode"]), None)
            if mode and mode.needs_ref and not refs:
                raise JobError("ref_missing")
            adapter = make_adapter(pdef.platform, url)
            tab = await self._get_tab(r, account, url)
            timeout = int(params.get("timeout_s") or (600 if pdef.kind == "video" or job["mode"] in ("t2v", "i2v", "compose", "extend") else 240))

            def prog(p):
                self.db.update_job(jid, progress=int(p))
                self.job_updated.emit(jid)

            def user(state):
                if state == "needs_user":
                    self.loop.create_task(self.browser.set_visible(account["id"], True, tab))
                    self.db.update_job(jid, status="needs_user")
                    self.toast.emit("warn", f"{pdef.label} · hàng {job['row_no']}: {friendly('needs_user')}")
                    self.db.update_account(account["id"], status="needs_user")
                else:
                    if True:                                     # luôn ẩn lại sau khi người dùng xác minh xong
                        self.loop.create_task(self.browser.set_visible(account["id"], False, tab))
                    self.db.update_job(jid, status="running")
                    self.db.update_account(account["id"], status="ok")
                self.job_updated.emit(jid)
                self.account_updated.emit(account["id"])

            dest = self._dest_dir(job, r.page_key)
            base = f"{job['row_no']:03d}_{slugify(job['prompt'])}"
            saved = 0
            is_video = pdef.kind == "video" or job["mode"] in ("t2v", "i2v", "compose", "extend")
            if hasattr(adapter, "run_and_save"):
                files = await adapter.run_and_save(tab, job, refs, params, int(job["count"]), prog, user, timeout,
                                                   dest, base, "video" if is_video else "image")
            else:
                srcs = await adapter.run(tab, job, refs, params, int(job["count"]), prog, user, timeout)
                files = [await adapter.download(tab, src, dest / f"{base}_{n}") for n, src in enumerate(srcs, 1)]
            from ..media.images import to_jpg
            for out in files:
                kind = "video" if out.suffix.lower() in (".mp4", ".webm", ".mov") else "image"
                if kind == "image" and out.suffix.lower() != ".jpg":
                    out = await asyncio.get_running_loop().run_in_executor(None, to_jpg, out)
                self.db.add_output(jid, kind, str(out))
                saved += 1
            self.db.update_job(jid, status="done", progress=100, finished_at=now(), error_code=None, error_text=None)
            self.db.bump_stat(pdef.platform, True)
            L.info("%s hàng %s: xong, lưu %d file vào %s", pdef.label, job["row_no"], saved, dest)
        except asyncio.CancelledError:
            self.db.update_job(jid, status="cancelled")
            raise
        except JobError as e:
            self._handle_failure(r, job, account, e.code, e.detail, e.friendly)
        except Exception as e:
            L.exception("%s hàng %s lỗi", pdef.label, job["row_no"])
            self._handle_failure(r, job, account, "unknown", str(e), friendly("unknown"))
        finally:
            self.job_updated.emit(jid)
            if tab is not None and not tab.is_closed() and account:
                r.tabs.setdefault(account["id"], []).append(tab)
            lo, hi = r.delay
            if r.active and hi > 0:
                # tài khoản vẫn được tính là "đang bận" trong lúc nghỉ → không nhận tác vụ mới cho tới khi nghỉ xong
                rest = random.uniform(lo, max(lo, hi))
                left = self.db.one("SELECT COUNT(*) n FROM jobs j JOIN batches b ON b.id=j.batch_id"
                                   " WHERE b.page=? AND j.status='queued'", (r.page_key,))
                if left and left["n"]:
                    L.info("%s: tài khoản %s nghỉ %.0f giây rồi nhận tác vụ tiếp (còn %d tác vụ chờ)",
                           pdef.label, account["label"] if account else "?", rest, left["n"])
                await asyncio.sleep(rest)

    async def _apply_chain(self, job: dict, pj: dict, params: dict) -> dict:
        """Lấy khung cuối video cảnh trước làm khung đầu cảnh này (Ảnh → Video). Cảnh trước lỗi → tạo bình thường."""
        out = self.db.one("SELECT path FROM outputs WHERE job_id=? AND kind='video' ORDER BY rowid DESC LIMIT 1", (pj["id"],))
        if pj["status"] != "done" or not out or not Path(out["path"]).exists():
            L.info("Hàng %s: cảnh trước chưa có video → tạo cảnh này không nối khung", job["row_no"])
            return job
        from ..media import ffmpeg
        frame = Path(out["path"]).with_name(Path(out["path"]).stem + "_khungcuoi.jpg")
        try:
            await asyncio.get_running_loop().run_in_executor(None, ffmpeg.extract_frame, out["path"], str(frame), "last")
        except Exception as e:
            L.warning("Hàng %s: không lấy được khung cuối cảnh trước (%s) → tạo không nối khung", job["row_no"], e)
            return job
        params["keyframe"] = False
        L.info("Hàng %s: nối liền mạch – khung đầu = khung cuối cảnh %s", job["row_no"], pj["row_no"])
        return dict(job, mode="i2v", refs=json.dumps([str(frame)], ensure_ascii=False))

    def flag_cooled(self, ids) -> list[str]:
        """Các tài khoản còn trong thời gian nghỉ sau khi Google báo "hoạt động bất thường"."""
        cd = self.db.get_setting("flag_cooldown", {}) or {}
        now_ = time.time()
        live = {k: v for k, v in cd.items() if v > now_}
        if len(live) != len(cd):
            self.db.set_setting("flag_cooldown", live)
        return [a for a in ids if a in live]

    def _handle_failure(self, r: PageRun, job: dict, account: dict | None, code: str, detail: str, msg: str):
        jid = job["id"]
        pdef = PAGE_BY_KEY[r.page_key]
        label = account["label"] if account else "?"
        attempts = job["attempts"] + 1
        if account:
            r.tried.setdefault(jid, set()).add(account["id"])
        if account and code == "flagged":
            cd = self.db.get_setting("flag_cooldown", {}) or {}
            cd[account["id"]] = time.time() + FLAG_COOLDOWN_S
            self.db.set_setting("flag_cooldown", cd)
            msg = msg + " Tài khoản này tự nghỉ 2 giờ rồi mới được dùng lại."
        if account and code in ACCOUNT_DOWN_CODES:
            r.down[account["id"]] = code
            if code == "not_logged_in":
                self.db.update_account(account["id"], status="expired")
            self.account_updated.emit(account["id"])
            self.toast.emit("warn", f"{pdef.label}: tài khoản {label} tạm ngưng — {msg}")
        others = [a for a in r.usable() if not account or a != account["id"]] or r.usable()
        can_retry = (r.failover and code in FAILOVER_CODES and others
                     and attempts <= max(2, len(r.account_ids)))
        if can_retry:
            self.db.update_job(jid, status="queued", progress=0, attempts=attempts, account_id=None,
                               error_code=code, error_text=f"[{label}] {detail}"[:500])
            L.warning("%s hàng %s: %s trên %s → chuyển sang tài khoản khác (%s)", pdef.label, job["row_no"], code, label, detail)
            return
        status = "blocked" if code == "blocked" else "failed"
        self.db.update_job(jid, status=status, error_code=code, error_text=f"[{label}] {detail}"[:500],
                           attempts=attempts, finished_at=now())
        self.db.bump_stat(pdef.platform, False)
        L.warning("%s hàng %s: %s (%s)", pdef.label, job["row_no"], msg, detail)
        if code in ("no_account",) or (code in ACCOUNT_DOWN_CODES and not r.usable()):
            r.active = False
            self.page_state.emit(r.page_key, "paused")
            self.toast.emit("error", f"{pdef.label}: {msg}")

    def _dest_dir(self, job: dict, page_key: str) -> Path:
        base = Path(job["save_dir"])
        mode = job["save_mode"]
        if mode == "per_task":
            return base / f"{job['row_no']:03d}_{slugify(job['prompt'], 30)}"
        if mode == "per_batch":
            try:
                t = datetime.strptime(job["batch_at"][:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                t = datetime.now()
            return base / t.strftime("%Y-%m-%d_%H%M")
        return base
