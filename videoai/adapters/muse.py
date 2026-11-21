"""Tạo ảnh / video Muse (muse.ai — trợ lý AI của Meta) bằng tài khoản Meta của chính người dùng, qua giao diện web.

Cơ chế (đọc từ trang thật 11/2026):
- Muse là MỘT cuộc trò chuyện dài: ô `textarea[placeholder=Message]`, nút gửi aria-label "Send", ô file ẩn (Attach file).
- Gửi yêu cầu bằng lời ("Create 2 images: … Aspect ratio 16:9.") — Muse làm theo tỷ lệ ghi trong yêu cầu, tối đa 4 ảnh/lần.
- Ảnh: khối `[data-testid=hatch-chat-attachment-presentation-image]` (ảnh nhỏ); bấm vào mở hộp xem có ảnh đầy đủ (vd 2048×1152).
- Video: khối `[data-testid=hatch-chat-attachment-presentation-video]` chứa <video> mp4 (1280×720, 10 giây).
- Kết quả của lần gửi = các khối đính kèm nằm SAU tin nhắn vừa gửi (tìm theo nội dung tin nhắn), không lẫn kết quả cũ.
Muse chỉ mở ở một số nước (Mỹ, Canada, Nhật, Singapore — 11/2026). Xác minh / đăng nhập: người dùng tự làm.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from ..core import log
from ..core.errors import JobError
from .base import WebAdapter

L = log.get("muse")

HOME = "https://muse.ai/"
RATIO_TEXT = {"16:9": "16:9 landscape", "9:16": "9:16 vertical", "1:1": "1:1 square", "4:3": "4:3 landscape",
              "3:4": "3:4 portrait", "3:2": "3:2 landscape", "2:3": "2:3 portrait"}
QUOTA_RE = re.compile(r"(limit|quota|try again (later|tomorrow|in)|reached|upgrade|hết lượt|giới hạn|thử lại sau)", re.I)
BLOCK_RE = re.compile(r"(chưa (tạo|làm) được|không (tạo|làm) được|mình không thể|tôi không thể|"
                      r"can[’']?t (help|create|make|generate)|cannot (create|make|generate)|violat|polic|not able to (create|make)|"
                      r"không thể (tạo|giúp)|vi phạm|chính sách)", re.I)
# Muse hỏi lại / đề xuất hướng khác và chờ xác nhận ("Bạn có muốn mình tạo theo hướng đó không?")
ASK_RE = re.compile(r"(bạn có muốn|có muốn mình|bạn muốn mình|muốn mình[^?]{0,80}không|mình[^?]{0,60}(nhé|không|được không)\s*\?|"
                    r"bạn (thấy )?(ok|được|đồng ý)[^?]{0,30}\?|xác nhận|do you want|would you like|shall i|should i|"
                    r"want me to|is that ok|sound good|okay with you|let me know if)", re.I)
VI_RE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)


def confirm_text(reply: str, kind: str) -> str:
    """Câu xác nhận gửi lại Muse, cùng ngôn ngữ với câu hỏi."""
    if VI_RE.search(reply):
        return f"Đồng ý, bạn tạo {'video' if kind == 'video' else 'ảnh'} theo đúng hướng bạn vừa đề xuất ngay bây giờ nhé."
    return f"Yes, please go ahead and create the {'video' if kind == 'video' else 'image'} exactly as you just suggested, right now."


def asks_confirmation(reply: str) -> bool:
    r = (reply or "").strip()
    return "?" in r[-160:] and bool(ASK_RE.search(r[-400:]))


REGION_RE = re.compile(r"(not (yet )?available in your (country|region)|chưa (có|hỗ trợ) ở (quốc gia|khu vực))", re.I)

IMG_SEL = "[data-testid='hatch-chat-attachment-presentation-image']"
VID_SEL = "[data-testid='hatch-chat-attachment-presentation-video']"

# Kết quả nằm sau tin nhắn có đoạn `snippet` (tin nhắn gửi gần nhất); trả về trạng thái để chờ / tải
JS_STATE = r"""([snippet, imgSel, vidSel]) => {
  const root = document.querySelector('[role=log]') || document.body;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  let anchor = null;
  for (const el of root.querySelectorAll('div, p, span')) {             // phần tử sâu nhất, cuối cùng chứa đoạn đã gửi
    if (el.children.length > 8) continue;
    if (norm(el.innerText).includes(snippet)) anchor = el;
  }
  const after = el => anchor && (anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) && !anchor.contains(el);
  const imgs = [...root.querySelectorAll(imgSel)].filter(after).map((e, i) => {
    const im = e.querySelector('img'); const b = e.querySelector('button');
    return {i, ready: !!(im && im.naturalWidth > 0) && (!b || b.getAttribute('aria-busy') !== 'true'),
            label: b ? (b.getAttribute('aria-label') || '') : ''};
  });
  const vids = [...root.querySelectorAll(vidSel)].filter(after).map((e, i) => {
    const v = e.querySelector('video');
    return {i, ready: !!(v && (v.currentSrc || v.src) && v.readyState >= 1), src: v ? (v.currentSrc || v.src) : null};
  });
  let reply = '';
  if (anchor) {                                                          // chữ Muse trả lời sau tin nhắn đã gửi
    const all = norm(root.innerText); const k = all.lastIndexOf(snippet);
    reply = k >= 0 ? all.slice(k + snippet.length).slice(0, 600) : '';
  }
  const busy = !!root.querySelector('[aria-busy=true]');
  return {found: !!anchor, imgs, vids, reply, busy};
}"""

# đánh dấu khối ảnh thứ k (sau tin nhắn đã gửi) để bấm mở
JS_TAG_IMG = r"""([snippet, imgSel, k]) => {
  const root = document.querySelector('[role=log]') || document.body;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  let anchor = null;
  for (const el of root.querySelectorAll('div, p, span')) { if (el.children.length > 8) continue; if (norm(el.innerText).includes(snippet)) anchor = el; }
  const list = [...root.querySelectorAll(imgSel)].filter(el => anchor && (anchor.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING));
  document.querySelectorAll('[data-va-muse]').forEach(e => e.removeAttribute('data-va-muse'));
  const t = list[k]; if (!t) return false;
  (t.querySelector('button') || t).setAttribute('data-va-muse', '1');
  return true;
}"""

JS_DIALOG_BEST = r"""() => {
  const d = [...document.querySelectorAll('[role=dialog]')].pop(); if (!d) return null;
  let best = null, area = 0;
  for (const i of d.querySelectorAll('img')) { const a = (i.naturalWidth || 0) * (i.naturalHeight || 0); if (a > area) { area = a; best = i.currentSrc || i.src; } }
  return best;
}"""


class MuseAdapter(WebAdapter):
    def __init__(self, platform: str = "muse", url_override: str | None = None):
        super().__init__("muse", url_override)
        self.url = (url_override or "").strip() or HOME

    async def _logged_out(self, page) -> bool:
        try:
            if await page.locator("input[placeholder*='Mobile number or email' i]").count():
                return True
        except Exception:
            pass
        return await self._any_visible(page, "logged_out_markers")

    async def is_logged_in(self, page) -> bool:
        if "muse.ai" not in page.url and "/muse/" not in page.url:
            return False
        if await self._any_visible(page, "captcha_markers") or await self._logged_out(page):
            return False
        return await self._first(page, "prompt", timeout=1500) is not None

    async def check_login(self, page) -> str:
        await asyncio.sleep(3)
        if await self._any_visible(page, "captcha_markers"):
            return "needs_user"
        if await self._logged_out(page):
            return "expired"
        return "ok" if await self._first(page, "prompt", timeout=8000) else "unknown"

    def _message(self, job: dict, params: dict, want: int, kind: str, refs: list[str]) -> str:
        ratio = (params.get("ratio") or "").split(" ")[0]
        rt = RATIO_TEXT.get(ratio)
        p = job["prompt"].strip().rstrip(".")
        if kind == "video":
            head = "Animate the attached image into a video" if refs else "Create a video"
        else:
            n = max(1, min(4, want))
            head = (f"Create {n} images" if n > 1 else "Create an image") + (" using the attached image(s) as reference" if refs else "")
        msg = f"{head}: {p}."
        if rt:
            msg += f" Aspect ratio {rt}."
        return msg

    async def run_and_save(self, page, job: dict, refs: list[str], params: dict, want: int,
                           on_progress, on_user, timeout_s: int, dest_dir: Path, base_name: str,
                           kind: str) -> list[Path]:
        if kind == "video" and params.get("keyframe") and refs:
            return await self.keyframe_video(page, job, refs, params, want, on_progress, on_user, timeout_s,
                                             dest_dir, base_name, 4)
        await page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)   # tải lại cho nhẹ (chat rất dài)
        await asyncio.sleep(3)
        await self.guard(page, on_user)
        body = (await page.locator("body").inner_text())[:3000]
        if REGION_RE.search(body):
            raise JobError("unknown", "Muse chưa mở ở quốc gia của tài khoản / mạng này (chỉ Mỹ, Canada, Nhật, Singapore)")
        if await self._logged_out(page):
            raise JobError("not_logged_in", "Muse chưa đăng nhập")
        box = await self._first(page, "prompt", timeout=20000)
        if box is None:
            raise JobError("ui_changed", "không thấy ô nhập tin nhắn của Muse")

        if refs:
            fi = await self._first(page, "file_input", timeout=4000, visible=False)
            if fi is None:
                raise JobError("ui_changed", "không thấy ô đính kèm ảnh của Muse")
            await fi.set_input_files(refs[:1] if kind == "video" else refs[:4])
            await asyncio.sleep(3)

        msg = self._message(job, params, want, kind, refs)
        snippet = re.sub(r"\s+", " ", msg)[:60].strip()
        await self._send(page, box, msg)
        on_progress(4)

        need = 1 if kind == "video" else max(1, min(4, want))
        start = asked_at = time.monotonic()
        confirms = 0
        stable = None
        last_sig = None
        st = {}
        while time.monotonic() - asked_at < timeout_s:
            await asyncio.sleep(3)
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_STATE, [snippet, IMG_SEL, VID_SEL])
            items = st["vids"] if kind == "video" else st["imgs"]
            ready = [x for x in items if x["ready"]]
            on_progress(min(92, 5 + int((time.monotonic() - start) * (0.9 if kind == "video" else 2.5))))
            sig = (len(items), len(ready))
            if ready and len(ready) == len(items) and (len(ready) >= need or not st["busy"]):
                if sig == last_sig and stable and time.monotonic() - stable > 5:
                    break
                if sig != last_sig:
                    last_sig, stable = sig, time.monotonic()
                continue
            last_sig = sig
            reply = st.get("reply") or ""
            if not items and time.monotonic() - asked_at > 25 and len(reply) > 20 and not st["busy"]:
                if REGION_RE.search(reply):
                    raise JobError("unknown", "Muse chưa mở ở quốc gia này: " + reply[:200])
                if asks_confirmation(reply) and confirms < 2:
                    # Muse hỏi lại / tự đề xuất hướng khác hợp chính sách của Muse → tools xác nhận để Muse tạo.
                    # Không viết lại câu lệnh để lách: chỉ đồng ý với chính phương án Muse đưa ra.
                    confirms += 1
                    L.warning("Muse hỏi lại trước khi tạo – tools tự xác nhận (lần %d). Muse: %s", confirms, reply[:300])
                    yes = confirm_text(reply, kind)
                    box = await self._first(page, "prompt", timeout=10000)
                    if box is None:
                        raise JobError("ui_changed", "không thấy ô nhập tin nhắn của Muse")
                    await self._send(page, box, yes)
                    snippet = re.sub(r"\s+", " ", yes)[:60].strip()
                    asked_at = time.monotonic()
                    last_sig = stable = None
                    continue
                if REGION_RE.search(reply):
                    raise JobError("unknown", "Muse chưa mở ở quốc gia này: " + reply[:200])
                if BLOCK_RE.search(reply):
                    hint = (" → Muse (Meta) không tạo video có người thật nói / diễn từ ảnh chân dung. Dùng Tạo Video Flow, "
                            "hoặc bỏ ảnh nhân vật để Muse chỉ quay sản phẩm / bối cảnh." if kind == "video" and refs else "")
                    raise JobError("blocked", "Muse từ chối: " + reply[:200] + hint)
                if QUOTA_RE.search(reply) and time.monotonic() - asked_at > 40:
                    raise JobError("quota", reply[:250])
        else:
            raise JobError("timeout", ("Muse trả lời: " + st.get("reply", "")[:200]) if st.get("reply") else "")
        on_progress(95)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out: list[Path] = []
        if kind == "video":
            for n, v in enumerate(st["vids"][:1], 1):
                out.append(await self.download(page, v["src"], dest_dir / f"{base_name}_{n}"))
            return out
        for n, im in enumerate(st["imgs"][:need], 1):
            out.append(await self._save_full_image(page, snippet, im["i"], dest_dir / f"{base_name}_{n}"))
        return out

    async def _send(self, page, box, msg: str):
        await box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(msg)
        await asyncio.sleep(0.6)
        send = None
        end = time.monotonic() + 60                  # chờ ảnh đính kèm tải lên xong
        while time.monotonic() < end:
            send = await self._first(page, "submit", timeout=2000)
            if send is not None and not await send.is_disabled():
                break
            await asyncio.sleep(1)
        if send is None:
            await page.keyboard.press("Enter")
        else:
            await send.click()

    async def _save_full_image(self, page, snippet: str, k: int, out_noext: Path) -> Path:
        """Mở ảnh trong hộp xem để lấy bản đầy đủ (ảnh trong khung chat chỉ là ảnh nhỏ)."""
        if not await page.evaluate(JS_TAG_IMG, [snippet, IMG_SEL, k]):
            raise JobError("download", "không tìm thấy ảnh kết quả của Muse")
        btn = page.locator("[data-va-muse='1']").first
        thumb = await btn.locator("img").first.get_attribute("src")
        await btn.click()
        best = None
        for _ in range(20):
            await asyncio.sleep(0.5)
            best = await page.evaluate(JS_DIALOG_BEST)
            if best and best != thumb:
                await asyncio.sleep(0.8)
                best = await page.evaluate(JS_DIALOG_BEST)
                break
        src = best or thumb
        try:
            path = await self.download(page, src, out_noext)
        finally:
            close = page.locator("[role=dialog] button[aria-label='Close']").first
            if await close.count():
                await close.click()
            else:
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        return path
