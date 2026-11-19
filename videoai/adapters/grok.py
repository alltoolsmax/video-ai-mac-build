"""Tạo ảnh Grok (grok.com/imagine) bằng tài khoản Grok của chính người dùng, qua giao diện web.

Bản thử nghiệm: chưa đọc được trang thật khi viết (Cloudflare chặn trình duyệt kiểm tra), nên adapter
dò phần tử theo nhiều cách và GHI CHẨN ĐOÁN vào Log khi không tìm thấy thứ cần — gửi log để chỉnh cho khớp.
- Ô nhập: textarea / ô contenteditable ở thanh dưới trang Imagine.
- Chế độ: bấm nút "Image"/"Hình ảnh" nếu trang có nút chọn Image/Video.
- Tỷ lệ: bấm nút đang ghi tỷ lệ (vd "2:3") rồi chọn tỷ lệ cần.
- Kết quả: các ảnh MỚI xuất hiện sau khi gửi (không có trước đó), đợi số ảnh ổn định rồi tải.
Xác minh Cloudflare / đăng nhập: hiện trình duyệt cho người dùng tự làm, không tự vượt qua.
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

HOME = "https://grok.com/imagine"
BLOCK_RE = re.compile(r"(moderat|violat|content polic|not allowed|can't generate|unable to generate|vi phạm|chính sách)", re.I)
QUOTA_RE = re.compile(r"(rate limit|limit reached|reached (your|the) limit|upgrade to (supergrok|premium)|out of (credits|generations)|"
                      r"try again (later|in)|hết lượt|đạt giới hạn)", re.I)

JS_IMGS = r"""(minPx) => [...document.querySelectorAll('main img, img')].filter(i => {
    const w = i.naturalWidth || 0, h = i.naturalHeight || 0; const r = i.getBoundingClientRect();
    return (w >= minPx || h >= minPx) && r.width >= 60 && r.height >= 60;
  }).map(i => i.currentSrc || i.src).filter(Boolean)"""

JS_BUSY = r"""() => {
  const t = (document.querySelector('main') || document.body).innerText || '';
  const busy = /(Generating|Đang tạo|Creating|\b\d{1,3}\s*%)/i.test(t) ||
               !!document.querySelector('[aria-busy=true], [role=progressbar], .animate-pulse');
  const alerts = [...document.querySelectorAll('[role=alert], [role=status], [data-sonner-toast], .toast, [aria-live]')]
                   .map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400);
  return {busy, alerts};
}"""

JS_DIAG = r"""() => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  return {
    url: location.href,
    buttons: [...document.querySelectorAll('button,[role=button],[role=radio],[role=tab]')].filter(vis).slice(0, 60)
      .map(b => [(b.getAttribute('aria-label') || ''), (b.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30),
                 b.getAttribute('aria-pressed') || b.getAttribute('aria-checked') || b.getAttribute('data-state') || ''].join('|')),
    inputs: [...document.querySelectorAll('textarea,[contenteditable=true],input')].slice(0, 12)
      .map(e => e.tagName + ' ' + (e.type || '') + ' ' + (e.getAttribute('placeholder') || e.getAttribute('aria-label') || '') + (vis(e) ? '' : ' (ẩn)')),
    imgs: [...document.querySelectorAll('img')].slice(-12).map(i => (i.currentSrc || i.src || '').slice(0, 60) + ' ' + i.naturalWidth + 'x' + i.naturalHeight),
    text: ((document.querySelector('main') || document.body).innerText || '').replace(/\s+/g, ' ').slice(0, 400),
  };
}"""

# bấm nút chọn theo chữ (Image / Hình ảnh…) nếu chưa được chọn
JS_PICK = r"""(names) => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  const els = [...document.querySelectorAll('button,[role=radio],[role=tab],[role=option],[role=menuitemradio],[role=menuitem]')].filter(vis);
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  for (const n of names) {
    const el = els.find(e => norm(e.innerText) === n.toLowerCase() || norm(e.getAttribute('aria-label')) === n.toLowerCase());
    if (!el) continue;
    const on = ['true', 'on', 'active', 'checked'].includes(el.getAttribute('aria-pressed') || el.getAttribute('aria-checked') ||
               el.getAttribute('aria-selected') || el.getAttribute('data-state') || '');
    if (!on) el.click();
    return on ? 'already' : 'clicked';
  }
  return null;
}"""

JS_RATIO_BTN = r"""() => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  const b = [...document.querySelectorAll('button,[role=button],[role=combobox]')].filter(vis)
    .find(e => /^(\d{1,2}:\d{1,2})$/.test((e.innerText || '').trim()) || /aspect|tỷ lệ/i.test(e.getAttribute('aria-label') || ''));
  if (!b) return null;
  b.click();
  return (b.innerText || '').trim() || 'aspect';
}"""


class GrokAdapter(WebAdapter):
    def __init__(self, platform: str = "grok", url_override: str | None = None):
        super().__init__("grok", url_override)
        self.url = (url_override or "").strip() or HOME

    async def _diag(self, page, why: str):
        try:
            d = await page.evaluate(JS_DIAG)
            L.warning("Grok chẩn đoán (%s): %s", why, json.dumps(d, ensure_ascii=False)[:3000])
        except Exception as e:
            L.warning("Grok chẩn đoán lỗi: %s", e)

    async def is_logged_in(self, page) -> bool:
        if "grok.com" not in page.url and "/grok/" not in page.url:
            return False
        if await self._any_visible(page, "captcha_markers") or await self._any_visible(page, "logged_out_markers"):
            return False
        return await self._first(page, "prompt", timeout=1500) is not None

    async def run_and_save(self, page, job: dict, refs: list[str], params: dict, want: int,
                           on_progress, on_user, timeout_s: int, dest_dir: Path, base_name: str,
                           kind: str) -> list[Path]:
        if not page.url.rstrip("/").endswith("/imagine"):
            await page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(2.5)
        await self.guard(page, on_user)
        if await self._any_visible(page, "logged_out_markers") and not await self._first(page, "prompt", timeout=3000):
            raise JobError("not_logged_in", "Grok chưa đăng nhập")
        box = await self._first(page, "prompt", timeout=20000)
        if box is None:
            await self._diag(page, "không thấy ô nhập")
            raise JobError("ui_changed", "không thấy ô nhập prompt của Grok Imagine (xem chẩn đoán trong Log)")

        got = await page.evaluate(JS_PICK, ["Image", "Images", "Hình ảnh", "Ảnh"])
        L.info("Grok: chế độ Ảnh → %s", got or "không có nút chọn (giữ nguyên)")
        ratio = (params.get("ratio") or "").split(" ")[0]
        if ratio:
            cur = await page.evaluate(JS_RATIO_BTN)
            if cur:
                await asyncio.sleep(0.6)
                if cur != ratio:
                    ok = await page.evaluate(JS_PICK, [ratio])
                    if not ok:
                        L.warning("Grok: không chọn được tỷ lệ %s (đang %s)", ratio, cur)
                await page.keyboard.press("Escape")
            else:
                L.info("Grok: không thấy nút tỷ lệ khung hình, dùng mặc định của Grok")

        if refs:
            fi = await self._first(page, "file_input", timeout=4000, visible=False)
            if fi is None:
                btn = await self._first(page, "attach_button", timeout=3000)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.8)
                    fi = await self._first(page, "file_input", timeout=4000, visible=False)
            if fi is None:
                await self._diag(page, "không thấy ô tải ảnh")
                raise JobError("ui_changed", "không thấy ô tải ảnh tham chiếu của Grok")
            await fi.set_input_files(refs[:4])
            await asyncio.sleep(3)

        min_px = int(self.sel.get("imagine_min_px", 400))
        before = set(await page.evaluate(JS_IMGS, min_px))
        box = await self._first(page, "prompt", timeout=8000)
        await box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(job["prompt"].strip())
        await asyncio.sleep(0.6)
        btn = await self._first(page, "submit", timeout=4000)
        if btn is not None and not await btn.is_disabled():
            await btn.click()
        else:
            await page.keyboard.press("Enter")
        on_progress(4)

        start = time.monotonic()
        found: list[str] = []
        stable = None
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(2.5)
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_BUSY)
            if st["alerts"]:
                if BLOCK_RE.search(st["alerts"]):
                    raise JobError("blocked", st["alerts"][:250])
                if QUOTA_RE.search(st["alerts"]):
                    raise JobError("quota", st["alerts"][:250])
            now = [s for s in await page.evaluate(JS_IMGS, min_px) if s not in before]
            final = [s for s in now if not s.startswith("data:")] or now   # ảnh xem trước dạng data: được thay bằng ảnh thật
            on_progress(min(92, 5 + int((time.monotonic() - start) * 1.5)))
            if final != found:
                found, stable = final, time.monotonic()
                continue
            if found and not st["busy"] and time.monotonic() - stable > 6:
                break
            if found and time.monotonic() - stable > 25:      # vẫn báo bận nhưng ảnh không đổi nữa
                break
            if not found and time.monotonic() - start > 90 and not st["busy"]:
                await self._diag(page, "không có ảnh mới sau 90 giây")
                raise JobError("unknown", "Grok không trả về ảnh (xem chẩn đoán trong Log)")
        if not found:
            await self._diag(page, "hết thời gian")
            raise JobError("timeout")
        on_progress(96)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for n, src in enumerate(found[:max(1, want)], 1):
            out.append(await self.download(page, src, dest_dir / f"{base_name}_{n}"))
        return out
