"""Tạo ảnh / video Grok (grok.com) bằng tài khoản Grok của chính người dùng, qua khung CHAT.

Cơ chế (đọc từ log chẩn đoán trên máy người dùng 11/2026):
- grok.com/imagine chuyển về grok.com/ (trang chat) với tài khoản thường → tạo ảnh/video NGAY TRONG CHAT.
- Trang chat: ô `div[contenteditable]` ("Message Grok"), nút aria-label "Send", ô file ẩn (Add files…), thông báo cookie
  (nút "Reject All").
- Gửi yêu cầu rõ ràng: "Generate a video: … Aspect ratio 9:16 (vertical)." / "Generate 2 images: … Aspect ratio 16:9."
  → Grok trả lời trong cuộc chat mới /c/<id>; dưới câu trả lời có nút "Download", "Copy response".
- Kết quả của lần gửi = ảnh / video nằm SAU tin nhắn vừa gửi (tìm theo nội dung), không lẫn ảnh mẫu của trang hay ảnh đính kèm.
Khi không khớp giao diện: Log ghi "Grok chẩn đoán". Xác minh Cloudflare / đăng nhập: người dùng tự làm, không lách.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from ..core import log
from ..core.errors import JobError
from .base import WebAdapter

L = log.get("grok")

HOME = "https://grok.com/"
RATIO_TEXT = {"16:9": "16:9 (landscape, horizontal)", "9:16": "9:16 (portrait, vertical)", "1:1": "1:1 (square)",
              "2:3": "2:3 (portrait)", "3:2": "3:2 (landscape)", "4:3": "4:3 (landscape)", "3:4": "3:4 (portrait)"}
BLOCK_RE = re.compile(r"(moderat|violat|content polic|not allowed|can[’']?t (generate|create|help)|unable to (generate|create)|"
                      r"vi phạm|chính sách|không thể tạo)", re.I)
QUOTA_RE = re.compile(r"(rate limit|limit reached|reached (your|the) (limit|daily)|upgrade to (supergrok|premium)|"
                      r"out of (credits|generations)|try again (later|in)|hết lượt|đạt giới hạn)", re.I)

# Kết quả nằm sau tin nhắn có đoạn `snippet`
JS_STATE = r"""([snippet, minPx]) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const root = document.querySelector('main') || document.body;
  let anchor = null;
  for (const el of root.querySelectorAll('div, p, span')) {
    if (el.children.length > 8 || el.isContentEditable || el.closest('[contenteditable=true]')) continue;
    if (norm(el.innerText).includes(snippet)) anchor = el;
  }
  if (!anchor) return {found: false};
  const after = el => (anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) && !anchor.contains(el)
                      && !el.closest('[contenteditable=true], form');
  const vids = [...root.querySelectorAll('video')].filter(after).map(v => v.currentSrc || v.src || (v.querySelector('source') || {}).src || '')
                 .filter(s => s && !s.startsWith('data:'));
  const imgs = [...root.querySelectorAll('img')].filter(after).filter(i => {
      const r = i.getBoundingClientRect(); const s = i.currentSrc || i.src || '';
      return (i.naturalWidth >= minPx || i.naturalHeight >= minPx) && r.width >= 80 && !/\/_next\/static\//.test(s);
    }).map(i => i.currentSrc || i.src);
  const btns = [...root.querySelectorAll('button')].filter(after).map(b => (b.getAttribute('aria-label') || '') + '|' + norm(b.innerText));
  const done = btns.some(b => /Copy response|Good response|Regenerate|Download/i.test(b));
  const all = norm(root.innerText); const k = all.lastIndexOf(snippet);
  const reply = k >= 0 ? all.slice(k + snippet.length, k + snippet.length + 600) : '';
  const busy = /(Generating|Đang tạo|Creating|Thinking|\b\d{1,3}\s*%)/i.test(reply) && !done;
  return {found: true, vids, imgs, done, busy, reply};
}"""

JS_DIAG = r"""() => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  return {
    url: location.href,
    buttons: [...document.querySelectorAll('main button, form button')].filter(vis).slice(-40)
      .map(b => [(b.getAttribute('aria-label') || ''), (b.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30)].join('|')),
    inputs: [...document.querySelectorAll('textarea,[contenteditable=true],input[type=file]')].slice(0, 8)
      .map(e => e.tagName + ' ' + (e.type || '') + ' ' + (e.getAttribute('placeholder') || e.getAttribute('aria-label') || '') + (vis(e) ? '' : ' (ẩn)')),
    media: [...document.querySelectorAll('main img, main video')].slice(-10)
      .map(i => i.tagName + ' ' + (i.currentSrc || i.src || '').slice(0, 70) + ' ' + (i.naturalWidth || i.videoWidth || 0) + 'x' + (i.naturalHeight || i.videoHeight || 0)),
    text: ((document.querySelector('main') || document.body).innerText || '').replace(/\s+/g, ' ').slice(-500),
  };
}"""


class GrokAdapter(WebAdapter):
    def __init__(self, platform: str = "grok", url_override: str | None = None):
        super().__init__("grok", url_override)
        u = (url_override or "").strip()
        self.url = HOME if (not u or u.rstrip("/").endswith("/imagine")) else u   # /imagine → chat

    async def _diag(self, page, why: str):
        try:
            d = await page.evaluate(JS_DIAG)
            L.warning("Grok chẩn đoán (%s): %s", why, json.dumps(d, ensure_ascii=False)[:3500])
        except Exception as e:
            L.warning("Grok chẩn đoán lỗi: %s", e)

    async def is_logged_in(self, page) -> bool:
        if "grok.com" not in page.url and "/grok/" not in page.url:
            return False
        if await self._any_visible(page, "captcha_markers") or await self._any_visible(page, "logged_out_markers"):
            return False
        return await self._first(page, "prompt", timeout=1500) is not None

    def _message(self, job: dict, params: dict, want: int, video: bool, refs: list[str]) -> str:
        ratio = (params.get("ratio") or "").split(" ")[0]
        p = job["prompt"].strip().rstrip(".")
        if video:
            head = "Animate the attached image into a video" if refs else "Generate a video"
        else:
            n = max(1, min(4, want))
            head = (f"Generate {n} images" if n > 1 else "Generate an image") + (" based on the attached image" if refs else "")
        msg = f"{head}: {p}."
        if ratio in RATIO_TEXT:
            msg += f" Aspect ratio {RATIO_TEXT[ratio]}."
        return msg

    async def _dismiss_cookies(self, page):
        for name in ("Reject All", "Accept All Cookies"):
            try:
                b = page.locator(f"button:has-text('{name}')").first
                if await b.count() and await b.is_visible():
                    await b.click()
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                pass

    async def run_and_save(self, page, job: dict, refs: list[str], params: dict, want: int,
                           on_progress, on_user, timeout_s: int, dest_dir: Path, base_name: str,
                           kind: str) -> list[Path]:
        video = kind == "video"
        await page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)   # mỗi tác vụ: cuộc chat mới
        await asyncio.sleep(2.5)
        await self.guard(page, on_user)
        await self._dismiss_cookies(page)
        if await self._any_visible(page, "logged_out_markers") and not await self._first(page, "prompt", timeout=3000):
            raise JobError("not_logged_in", "Grok chưa đăng nhập")
        box = await self._first(page, "prompt", timeout=20000)
        if box is None:
            await self._diag(page, "không thấy ô nhập")
            raise JobError("ui_changed", "không thấy ô nhập tin nhắn của Grok (xem chẩn đoán trong Log)")

        if refs:
            fi = await self._first(page, "file_input", timeout=4000, visible=False)
            if fi is None:
                await self._diag(page, "không thấy ô tải ảnh")
                raise JobError("ui_changed", "không thấy ô tải ảnh tham chiếu của Grok")
            await fi.set_input_files(refs[:1] if video else refs[:4])
            await asyncio.sleep(3)

        msg = self._message(job, params, want, video, refs)
        snippet = re.sub(r"\s+", " ", msg)[:60].strip()
        await box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(msg)
        await asyncio.sleep(0.6)
        send = None
        end = time.monotonic() + 60                    # chờ ảnh đính kèm tải lên xong
        while time.monotonic() < end:
            send = await self._first(page, "submit", timeout=2000)
            if send is not None and not await send.is_disabled():
                break
            await asyncio.sleep(1)
        if send is not None and not await send.is_disabled():
            await send.click()
        else:
            await page.keyboard.press("Enter")
        on_progress(4)
        L.info("Grok: đã gửi %s", msg[:140])

        min_px = int(self.sel.get("imagine_min_px", 400))
        start = time.monotonic()
        last, stable, st = None, None, {}
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(2.5)
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_STATE, [snippet, min_px])
            on_progress(min(92, 5 + int((time.monotonic() - start) * (0.6 if video else 1.5))))
            if not st.get("found"):
                if time.monotonic() - start > 40:
                    await self._diag(page, "không thấy tin nhắn vừa gửi")
                    raise JobError("ui_changed", "không thấy tin nhắn vừa gửi trên Grok (xem chẩn đoán trong Log)")
                continue
            items = st["vids"] if video else [s for s in st["imgs"] if not s.startswith("data:")] or st["imgs"]
            if items:
                if items != last:
                    last, stable = items, time.monotonic()
                elif (st["done"] and time.monotonic() - stable > 3) or time.monotonic() - stable > 20:
                    break
                continue
            reply = st.get("reply") or ""
            if st["done"] or (not st["busy"] and time.monotonic() - start > 30 and len(reply) > 40):
                if BLOCK_RE.search(reply):
                    raise JobError("blocked", reply[:250])
                if QUOTA_RE.search(reply):
                    raise JobError("quota", reply[:250])
                if st["done"]:
                    if not video and st["vids"]:
                        raise JobError("unknown", "Grok trả về video thay vì ảnh")
                    if video and st["imgs"]:
                        raise JobError("unknown", "Grok trả về ảnh thay vì video (tài khoản có thể chưa được tạo video)")
                    await self._diag(page, "Grok trả lời nhưng không có kết quả")
                    raise JobError("unknown", "Grok trả lời mà không tạo " + ("video" if video else "ảnh") + ": " + reply[:180])
        else:
            await self._diag(page, "hết thời gian")
            raise JobError("timeout")
        on_progress(96)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for n, src in enumerate(last[:1 if video else max(1, want)], 1):
            out.append(await self.download(page, src, dest_dir / f"{base_name}_{n}"))
        return out
