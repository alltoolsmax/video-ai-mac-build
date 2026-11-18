"""Quản lý trình duyệt Playwright: mỗi tài khoản một hồ sơ Chrome riêng (giữ phiên đăng nhập).

Nguyên tắc:
- Luôn mở cửa sổ thật (headless=False) để người dùng thấy và can thiệp.
- Không giả mạo dấu vân tay, không plugin vượt chặn bot.
- Mỗi hồ sơ chỉ một tiến trình (Chrome tự khóa thư mục hồ sơ).
Tất cả hàm async chạy trong vòng lặp asyncio của Engine.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..core import log
from ..core.errors import JobError

L = log.get("browser")


class BrowserManager:
    def __init__(self):
        self._pw = None
        self._contexts: dict[str, object] = {}   # account_id -> BrowserContext
        self._lock = asyncio.Lock()
        self._claimed: set[int] = set()

    async def _ensure_pw(self):
        if self._pw is None:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
        return self._pw

    async def context(self, account: dict):
        async with self._lock:
            ctx = self._contexts.get(account["id"])
            if ctx is not None:
                try:
                    _ = ctx.pages  # còn sống?
                    return ctx
                except Exception:
                    self._contexts.pop(account["id"], None)
            pw = await self._ensure_pw()
            prof = Path(account["profile_dir"])
            prof.mkdir(parents=True, exist_ok=True)
            kwargs = dict(
                user_data_dir=str(prof),
                headless=os.environ.get("VIDEOAI_HEADLESS") == "1",   # chỉ dùng khi chạy kiểm thử tự động
                viewport=None,
                accept_downloads=True,
                args=["--start-maximized"],
            )
            last_err = None
            channels = (None,) if os.environ.get("VIDEOAI_HEADLESS") == "1" else ("chrome", "msedge", None)
            for channel in channels:
                try:
                    if channel:
                        ctx = await pw.chromium.launch_persistent_context(channel=channel, **kwargs)
                    else:
                        ctx = await pw.chromium.launch_persistent_context(**kwargs)
                    L.info("Mở trình duyệt (%s) cho %s", channel or "chromium", account["label"])
                    break
                except Exception as e:  # thử kênh tiếp theo
                    last_err = e
                    ctx = None
            if ctx is None:
                raise JobError("browser", str(last_err))
            ctx.on("close", lambda *_: self._contexts.pop(account["id"], None))
            self._contexts[account["id"]] = ctx
            return ctx

    async def new_page(self, account: dict, url: str):
        ctx = await self.context(account)
        async with self._lock:   # tránh hai tác vụ cùng lấy một tab trống
            pages = [p for p in ctx.pages if p.url in ("about:blank", "chrome://newtab/") and id(p) not in self._claimed]
            page = pages[0] if pages else await ctx.new_page()
            self._claimed.add(id(page))
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        return page

    async def close_account(self, account_id: str):
        ctx = self._contexts.pop(account_id, None)
        if ctx:
            try:
                await ctx.close()
            except Exception:
                pass

    async def close_all(self):
        for aid in list(self._contexts):
            await self.close_account(aid)
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def is_open(self, account_id: str) -> bool:
        return account_id in self._contexts
