"""Tạo ảnh ChatGPT (chatgpt.com/images) bằng tài khoản ChatGPT của chính người dùng, qua giao diện web.

Cơ chế (đọc từ trang thật 11/2026):
- Trang chatgpt.com/images/ có ô soạn `div.ProseMirror` ("Describe a new image") và nút gửi aria-label "Send".
- Ảnh tham chiếu: ô `input[type=file]` ẩn (Attach photos, accept image/*).
- Bấm gửi → trang chuyển sang cuộc trò chuyện mới /c/<id>, hiện "Creating image NN%".
- Xong: `img[alt^="Generated image"]` (ảnh PNG đầy đủ dạng blob:). Tỷ lệ khung hình ghi trong prompt.
- Mỗi tác vụ mở cuộc trò chuyện mới để không bị lẫn ảnh cũ.
Xác minh Cloudflare / đăng nhập: hiện trình duyệt cho người dùng tự làm, không tự vượt qua.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from ..core import log
from ..core.errors import JobError
from .base import WebAdapter

L = log.get("gpt")

HOME = "https://chatgpt.com/images/"
RATIO_TEXT = {
    "1:1": "Aspect ratio 1:1 (square).",
    "3:2": "Aspect ratio 3:2 (landscape).",
    "2:3": "Aspect ratio 2:3 (portrait).",
    "16:9": "Aspect ratio 16:9 (landscape).",
    "9:16": "Aspect ratio 9:16 (portrait, vertical).",
    "4:3": "Aspect ratio 4:3 (landscape).",
    "3:4": "Aspect ratio 3:4 (portrait).",
}
QUOTA_RE = re.compile(r"(hit (the|your) (image|daily|free)|reached (the|your) (limit|image)|image generation limit|"
                      r"limit (for|on) image|try again (later|in|after)|upgrade to (plus|pro|get more)|"
                      r"đã đạt giới hạn|hết lượt)", re.I)
BLOCK_RE = re.compile(r"(content polic|violat|can[’']?t (help|create|generate|make) (that|this|images? of)|"
                      r"unable to (create|generate)|not able to (create|generate)|vi phạm|chính sách nội dung)", re.I)

JS_STATE = r"""() => {
  const main = document.querySelector('main') || document.body;
  const imgs = [...main.querySelectorAll('img[alt^="Generated image"]')]
                 .filter(i => i.naturalWidth > 0).map(i => i.currentSrc || i.src);
  const t = (main.innerText || '');
  const m = t.match(/Creating image\s*(\d{1,3})\s*%/i);
  const creating = /Creating image|Đang tạo hình ảnh/i.test(t);
  const stop = !!document.querySelector('button[data-testid="stop-button"], button[aria-label*="Stop" i]');
  const turns = [...main.querySelectorAll('[data-message-author-role="assistant"]')];
  const reply = turns.length ? (turns[turns.length - 1].innerText || '') : t.split(/You said:/).pop();
  return {imgs, creating, pct: m ? +m[1] : null, stop, reply: reply.slice(-600), url: location.href};
}"""

JS_FILE_INPUT = r"""() => {
  const ins = [...document.querySelectorAll('input[type=file]')];
  const score = i => {
    const a = (i.getAttribute('aria-label') || i.getAttribute('placeholder') || '').toLowerCase();
    const acc = (i.getAttribute('accept') || '').toLowerCase();
    if (i.hasAttribute('capture') || a.includes('take a photo') || a.includes('camera')) return -1;
    if (a.includes('attach photos') && !a.includes('video')) return 3;
    if (acc.startsWith('image')) return 2;
    if (!acc) return 1;
    return 0;
  };
  let best = -1, idx = -1;
  ins.forEach((i, k) => { const s = score(i); if (s > best) { best = s; idx = k; } });
  ins.forEach(i => i.removeAttribute('data-va-file'));
  if (idx >= 0) ins[idx].setAttribute('data-va-file', '1');
  return idx;
}"""


class GptAdapter(WebAdapter):
    def __init__(self, platform: str = "gpt", url_override: str | None = None):
        super().__init__("gpt", url_override)
        u = (url_override or "").strip()
        self.url = u or HOME

    # ---------------------------------------------------------- đăng nhập
    async def _login_button(self, page) -> bool:
        try:
            loc = page.locator("[data-testid='login-button'], button:has-text('Log in')")
            n = await loc.count()
            for i in range(n):
                if await loc.nth(i).is_visible():
                    return True
        except Exception:
            pass
        return False

    async def is_logged_in(self, page) -> bool:
        if "chatgpt.com" not in page.url or "/auth" in page.url:
            return False
        if await self._any_visible(page, "captcha_markers") or await self._login_button(page):
            return False
        return await self._first(page, "prompt", timeout=1500) is not None

    async def check_login(self, page) -> str:
        await asyncio.sleep(3)
        if await self._any_visible(page, "captcha_markers"):
            return "needs_user"
        if await self._login_button(page):
            return "expired"
        if await self._first(page, "prompt", timeout=8000):
            return "ok"
        return "unknown"

    # ---------------------------------------------------------- chạy
    async def run_and_save(self, page, job: dict, refs: list[str], params: dict, want: int,
                           on_progress, on_user, timeout_s: int, dest_dir: Path, base_name: str,
                           kind: str) -> list[Path]:
        await page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)   # cuộc trò chuyện mới cho mỗi tác vụ
        await asyncio.sleep(2)
        await self.guard(page, on_user)
        if await self._login_button(page):
            raise JobError("not_logged_in", "ChatGPT chưa đăng nhập")
        box = await self._first(page, "prompt", timeout=20000)
        if box is None:
            raise JobError("ui_changed", "không thấy ô nhập prompt của ChatGPT")

        if refs:
            idx = await page.evaluate(JS_FILE_INPUT)
            if idx < 0:
                raise JobError("ui_changed", "không thấy ô tải ảnh của ChatGPT")
            await page.locator("input[type=file][data-va-file='1']").set_input_files(refs[:10])
            await asyncio.sleep(2)

        ratio = (params.get("ratio") or "").split(" ")[0]
        text = job["prompt"].strip()
        if ratio in RATIO_TEXT and "aspect ratio" not in text.lower():
            text = f"{text}\n{RATIO_TEXT[ratio]}"
        await box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(text)
        await asyncio.sleep(0.8)

        send = None
        end = time.monotonic() + 90           # chờ ảnh tham chiếu tải lên xong thì nút gửi mới bật
        while time.monotonic() < end:
            send = await self._first(page, "submit", timeout=2000)
            if send is not None and not await send.is_disabled():
                break
            await asyncio.sleep(1)
        else:
            raise JobError("ui_changed", "nút gửi của ChatGPT không bật (ảnh tham chiếu chưa tải lên xong?)")
        start_url = page.url
        await send.click()
        on_progress(3)

        start = time.monotonic()
        stable = None
        last: list[str] = []
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(2.5)
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_STATE)
            if st["pct"] is not None:
                on_progress(max(5, min(95, st["pct"])))
            else:
                on_progress(min(90, 5 + int((time.monotonic() - start) * 0.6)))
            busy = st["creating"] or st["stop"]
            if st["imgs"] and not busy:
                if st["imgs"] == last:
                    if stable and time.monotonic() - stable > 3:
                        break
                else:
                    last, stable = st["imgs"], time.monotonic()
                continue
            if not busy and time.monotonic() - start > 12 and st["url"] != start_url:
                reply = st["reply"] or ""
                if QUOTA_RE.search(reply):
                    raise JobError("quota", reply.strip()[:250])
                if BLOCK_RE.search(reply):
                    raise JobError("blocked", reply.strip()[:250])
                if time.monotonic() - start > 45 and reply.strip():
                    raise JobError("unknown", "ChatGPT trả lời mà không tạo ảnh: " + reply.strip()[:220])
        else:
            raise JobError("timeout")
        if not last:
            raise JobError("timeout")
        on_progress(97)
        dest_dir.mkdir(parents=True, exist_ok=True)
        return [await self.download(page, src, dest_dir / f"{base_name}_{n}")
                for n, src in enumerate(last[:max(1, want)], 1)]
