"""Bộ chạy tác vụ: một luồng riêng với vòng lặp asyncio, điều khiển trình duyệt qua adapter.

Giao diện gọi các hàm public (an toàn từ luồng UI). Engine phát tín hiệu Qt để giao diện cập nhật.
Quy tắc:
- Mỗi trang chạy trên MỘT tài khoản do người dùng chọn; không tự đổi tài khoản khi hết lượt.
- "Số hàng tạo đồng thời" = số tab cùng lúc trong tài khoản đó (giới hạn tối đa trong Cài Đặt).
- Gặp captcha/đăng xuất: tạm dừng tác vụ đó, đưa cửa sổ lên, chờ người dùng.
"""
from __future__ import annotations

import asyncio
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
from ..browser.manager import BrowserManager

L = log.get("engine")


def slugify(text: str, n: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return (t[:n] or "prompt").rstrip("_")


class PageRun:
    def __init__(self, page_key: str, account_id: str, concurrency: int, delay: tuple[int, int]):
        self.page_key = page_key
        self.account_id = account_id
        self.concurrency = max(1, concurrency)
        self.delay = delay
        self.tasks: set[asyncio.Task] = set()
        self.tabs: list = []          # tab rảnh để dùng lại
        self.active = True


class Engine(QObject):
    job_updated = Signal(str)               # job_id
    page_state = Signal(str, str)           # page_key, running|paused|stopped|idle
    toast = Signal(str, str)                # kind(info|ok|warn|error), message
    account_updated = Signal(str)           # account_id

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.browser = BrowserManager()
        self.runs: dict[str, PageRun] = {}
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._thread_main, name="engine", daemon=True)
        self._thread.start()

    # ================= public (luồng UI) =================
    def start_page(self, page_key: str, account_id: str, concurrency: int, delay: tuple[int, int]):
        self._call(self._start_page(page_key, account_id, concurrency, delay))

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

    def is_running(self, page_key: str) -> bool:
        r = self.runs.get(page_key)
        return bool(r and r.active)

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
        return urls.get(page_key) or pdef.url

    async def _start_page(self, page_key, account_id, concurrency, delay):
        r = self.runs.get(page_key)
        if r and r.account_id == account_id:
            r.active, r.concurrency, r.delay = True, max(1, concurrency), delay
        else:
            self.runs[page_key] = PageRun(page_key, account_id, concurrency, delay)
        self.page_state.emit(page_key, "running")
        L.info("Bắt đầu %s (đồng thời %s, nghỉ %s-%ss)", page_key, concurrency, *delay)

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
        L.info("Dừng %s, hủy %d tác vụ (%s)", page_key, len(rows), pdef.label)

    async def _open_login(self, account, url):
        try:
            page = await self.browser.new_page(account, url)
            await page.bring_to_front()
            self.toast.emit("info", f"Đã mở trình duyệt cho {account['label']}. Hãy đăng nhập rồi bấm 'Kiểm tra'.")
        except Exception as e:
            L.exception("open_login")
            self.toast.emit("error", friendly(getattr(e, "code", "browser")))

    async def _check_account(self, account, url):
        try:
            ad = WebAdapter(account["platform"], url)
            page = await self.browser.new_page(account, url)
            status = await ad.check_login(page)
            credits = await ad.read_credits(page)
            self.db.update_account(account["id"], status=status, credits_left=credits, last_check_at=now())
            self.account_updated.emit(account["id"])
            self.toast.emit("ok" if status == "ok" else "warn",
                            f"{account['label']}: " + {"ok": "đã đăng nhập", "expired": "chưa đăng nhập",
                                                        "needs_user": "cần xác minh trong trình duyệt",
                                                        "unknown": "chưa xác định được (kiểm tra selector)"}[status])
        except Exception as e:
            L.exception("check_account")
            self.toast.emit("error", friendly(getattr(e, "code", "browser")))

    async def _scheduler(self):
        while True:
            try:
                for key, r in list(self.runs.items()):
                    r.tasks = {t for t in r.tasks if not t.done()}
                    if not r.active:
                        continue
                    free = r.concurrency - len(r.tasks)
                    if free <= 0:
                        continue
                    queued = self.db.query(
                        "SELECT j.*, b.save_dir, b.save_mode, b.params AS batch_params, b.created_at AS batch_at"
                        " FROM jobs j JOIN batches b ON b.id=j.batch_id"
                        " WHERE b.page=? AND j.status='queued' ORDER BY b.created_at, j.row_no LIMIT ?",
                        (key, free))
                    if not queued and not r.tasks:
                        r.active = False
                        self.page_state.emit(key, "idle")
                        self.toast.emit("ok", f"{PAGE_BY_KEY[key].label}: đã chạy xong hàng đợi.")
                        continue
                    for job in queued:
                        self.db.update_job(job["id"], status="running", progress=0, started_at=now(),
                                           account_id=r.account_id, error_code=None, error_text=None)
                        self.job_updated.emit(job["id"])
                        t = self.loop.create_task(self._run_job(r, job))
                        r.tasks.add(t)
            except Exception:
                L.exception("scheduler")
            await asyncio.sleep(1.0)

    async def _get_tab(self, r: PageRun, account: dict, url: str):
        while r.tabs:
            tab = r.tabs.pop()
            if not tab.is_closed():
                return tab
        return await self.browser.new_page(account, url)

    async def _run_job(self, r: PageRun, job: dict):
        jid = job["id"]
        pdef = PAGE_BY_KEY[r.page_key]
        account = self.db.one("SELECT * FROM accounts WHERE id=?", (r.account_id,))
        tab = None
        try:
            if not account:
                raise JobError("no_account")
            url = self._url_for(r.page_key)
            params = {**json.loads(job["batch_params"] or "{}"), **json.loads(job["params"] or "{}")}
            refs = [p for p in json.loads(job["refs"] or "[]") if Path(p).exists()]
            mode = next((m for m in pdef.modes if m.key == job["mode"]), None)
            if mode and mode.needs_ref and not refs:
                raise JobError("ref_missing")
            adapter = WebAdapter(pdef.platform, url)
            tab = await self._get_tab(r, account, url)
            timeout = int(params.get("timeout_s") or (600 if pdef.kind == "video" or job["mode"] in ("t2v", "i2v", "compose") else 240))

            def prog(p):
                self.db.update_job(jid, progress=int(p))
                self.job_updated.emit(jid)

            def user(state):
                if state == "needs_user":
                    self.db.update_job(jid, status="needs_user")
                    self.toast.emit("warn", f"{pdef.label} · hàng {job['row_no']}: {friendly('needs_user')}")
                    self.db.update_account(account["id"], status="needs_user")
                else:
                    self.db.update_job(jid, status="running")
                    self.db.update_account(account["id"], status="ok")
                self.job_updated.emit(jid)
                self.account_updated.emit(account["id"])

            srcs = await adapter.run(tab, job, refs, params, int(job["count"]), prog, user, timeout)
            dest = self._dest_dir(job, r.page_key)
            base = f"{job['row_no']:03d}_{slugify(job['prompt'])}"
            saved = 0
            for n, src in enumerate(srcs, 1):
                out = await adapter.download(tab, src, dest / f"{base}_{n}")
                kind = "video" if out.suffix in (".mp4", ".webm") else "image"
                self.db.add_output(jid, kind, str(out))
                saved += 1
            self.db.update_job(jid, status="done", progress=100, finished_at=now())
            self.db.bump_stat(pdef.platform, True)
            L.info("%s hàng %s: xong, lưu %d file vào %s", pdef.label, job["row_no"], saved, dest)
        except asyncio.CancelledError:
            self.db.update_job(jid, status="cancelled")
            raise
        except JobError as e:
            status = "blocked" if e.code == "blocked" else "failed"
            self.db.update_job(jid, status=status, error_code=e.code, error_text=e.detail[:500],
                               attempts=job["attempts"] + 1, finished_at=now())
            self.db.bump_stat(pdef.platform, False)
            L.warning("%s hàng %s: %s (%s)", pdef.label, job["row_no"], e.friendly, e.detail)
            if e.code in ("quota", "no_account", "browser", "needs_user"):
                r.active = False
                self.page_state.emit(r.page_key, "paused")
                self.toast.emit("error", f"{pdef.label}: {e.friendly}")
        except Exception as e:
            self.db.update_job(jid, status="failed", error_code="unknown", error_text=str(e)[:500],
                               attempts=job["attempts"] + 1, finished_at=now())
            self.db.bump_stat(pdef.platform, False)
            L.exception("%s hàng %s lỗi", pdef.label, job["row_no"])
        finally:
            self.job_updated.emit(jid)
            if tab is not None and not tab.is_closed():
                r.tabs.append(tab)
            lo, hi = r.delay
            if r.active and hi > 0:
                await asyncio.sleep(random.uniform(lo, max(lo, hi)))

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
