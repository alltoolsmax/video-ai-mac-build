"""Tài khoản Gemini (gemini.google.com) – CHỈ dùng cho AI Agent, không có trang tạo ảnh / video.

Là loại tài khoản riêng: cookie lấy ở trang gemini.google.com, hồ sơ trình duyệt riêng, không dùng chung với tài khoản
Google của Flow. Adapter này chỉ lo việc kiểm tra đăng nhập; việc hỏi – đáp nằm ở adapters/chat.py (khóa "gemini").

Đo trên trang thật ngày 27/11/2026: phiên không hợp lệ cho Gemini → gemini.google.com chuyển sang
accounts.google.com/…/signin dù cookie SID của google.com vẫn còn. Vì vậy KHÔNG lấy cookie SID làm bằng chứng đã đăng
nhập (LOGIN_COOKIES để trống): phải thấy ô chat của Gemini mới là "đã đăng nhập".
"""
from __future__ import annotations

import asyncio

from .base import WebAdapter
from .chat import SITES

HOME = "https://gemini.google.com/app"
PROMPT = SITES["gemini"][2]            # cùng ô nhập mà AI Agent dùng để gửi tin nhắn


class GeminiAdapter(WebAdapter):
    LOGIN_COOKIES = ()

    def __init__(self, platform: str = "gemini", url_override: str | None = None):
        super().__init__("gemini", url_override)
        self.url = (url_override or "").strip() or HOME
        self.sel = dict(self.sel, prompt=PROMPT)

    @staticmethod
    def _on_signin(page) -> bool:
        return "accounts.google.com" in page.url

    async def _signed_out(self, page) -> bool:
        # trang đăng nhập Google, hoặc trang Gemini còn hiện nút / liên kết Đăng nhập (selector chung của mọi nền tảng)
        return self._on_signin(page) or await self._any_visible(page, "logged_out_markers")

    async def is_logged_in(self, page) -> bool:
        if await self._signed_out(page) or await self._any_visible(page, "captcha_markers"):
            return False
        return await self._first(page, "prompt", timeout=1500) is not None

    async def check_login(self, page) -> str:
        await asyncio.sleep(3)
        if await self._any_visible(page, "captcha_markers"):
            return "needs_user"
        if await self._signed_out(page):
            return "expired"
        if await self._first(page, "prompt", timeout=10000):
            return "ok"
        return "expired" if self._on_signin(page) else "unknown"
