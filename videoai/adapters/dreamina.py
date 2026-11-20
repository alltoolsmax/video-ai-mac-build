"""Tạo video Dreamina (dreamina.capcut.com) bằng tài khoản Dreamina/CapCut của chính người dùng, qua giao diện web.

Cơ chế (đọc từ trang thật 11/2026):
- Trang tạo: /ai-tool/home?type=video — ô soạn `.tiptap.ProseMirror`, thanh chọn: model (lv-select "Dreamina Seedance …"),
  chế độ (lv-select "Omni reference" / "First and last frames" …), nút "16:9 · 720P" mở bảng tỷ lệ + độ phân giải
  (label.lv-radio), nút "5s" mở thanh thời lượng (0–15 giây), nút Generate (aria-label "Generate").
- Bấm Generate ở trang chủ chỉ mở một phiên /ai-tool/generate?workspace=…, prompt vẫn nằm trong ô → bấm Generate lần nữa.
- Mỗi lần tạo là một khối `div[class*="video-record"]` trong phiên (đầu khối ghi prompt, model, thời lượng, tỷ lệ, độ phân giải):
  xong → có thẻ <video>; lỗi → có `[class*="error-tips"]` (vd "Couldn't generate due to unusual activity in your account").
- Hay có cửa sổ quảng cáo (lv-modal) → đóng.
"Unusual activity" = Dreamina nghi ngờ tài khoản: dừng tài khoản đó, báo người dùng, KHÔNG lách.
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

L = log.get("dreamina")

HOME = "https://dreamina.capcut.com/ai-tool/home?type=video"
FLAG_RE = re.compile(r"(unusual activity|suspicious|hoạt động bất thường)", re.I)
QUOTA_RE = re.compile(r"(not enough credits|insufficient credits|out of credits|credit|limit reached|upgrade|hết credit|không đủ)", re.I)
BLOCK_RE = re.compile(r"(violat|policy|sensitive|not allowed|inappropriate|vi phạm|chính sách|nhạy cảm)", re.I)

# trạng thái khối kết quả của đúng prompt vừa gửi (khối cuối cùng chứa đoạn prompt)
JS_RECORD = r"""(snippet) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const recs = [...document.querySelectorAll('div[class*="video-record"]')].filter(r => norm(r.innerText).includes(snippet));
  const r = recs[recs.length - 1];
  if (!r) return {found: false, count: document.querySelectorAll('div[class*="video-record"]').length};
  const err = r.querySelector('[class*="error-tips"]');
  const vids = [...r.querySelectorAll('video')].map(v => v.currentSrc || v.src || (v.querySelector('source') || {}).src || '').filter(Boolean);
  const pct = (norm(r.innerText).match(/(\d{1,3})\s*%/) || [])[1];
  return {found: true, count: recs.length, error: err ? norm(err.innerText) : '', vids, pct: pct ? +pct : null,
          busy: /generating|queue|đang tạo|xếp hàng/i.test(norm(r.innerText)) || !!r.querySelector('[class*="progress"],[class*="loading"]')};
}"""

JS_CLOSE_MODALS = r"""() => {
  let n = 0;
  for (const m of document.querySelectorAll('.lv-modal-wrapper, .lv-modal, [role=dialog]')) {
    if (!(m.offsetParent || m.getClientRects().length)) continue;
    const c = m.querySelector('.lv-modal-close-icon, [class*="close"], button[aria-label*="lose" i]');
    if (c) { c.click(); n++; }
  }
  return n;
}"""

# bấm mục có đúng chữ `text` trong popup/popover đang mở (lv-select / lv-popover)
JS_PICK_IN_POPUP = r"""(text) => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  const pops = [...document.querySelectorAll('.lv-select-popup, .lv-popover, .lv-trigger-popup')].filter(vis);
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const want = norm(text);
  for (const p of pops.reverse()) {
    const cands = [...p.querySelectorAll('li, [role=option], label, .lv-select-option, div, span')].filter(vis);
    let el = cands.find(e => norm(e.innerText) === want) || cands.find(e => norm(e.innerText).startsWith(want + ' '));
    if (el) { (el.closest('li, [role=option], label, .lv-select-option') || el).click(); return true; }
  }
  return false;
}"""

# mở một nút/ô chọn trên thanh soạn theo mẫu chữ
JS_OPEN = r"""(pattern) => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  const re = new RegExp(pattern, 'i');
  const el = [...document.querySelectorAll('button, .lv-select')].filter(vis).find(e => re.test((e.innerText || '').replace(/\s+/g, ' ').trim()));
  if (!el) return null;
  el.click();
  return (el.innerText || '').replace(/\s+/g, ' ').trim();
}"""

JS_DIAG = r"""() => {
  const vis = e => !!(e.offsetParent || e.getClientRects().length);
  return {url: location.href,
    buttons: [...document.querySelectorAll('button, .lv-select')].filter(vis).slice(0, 50)
      .map(b => (b.getAttribute('aria-label') || '') + '|' + (b.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40)),
    records: [...document.querySelectorAll('div[class*="record"]')].slice(-3).map(r => (r.className || '').toString().slice(0, 60) + ' :: ' + (r.innerText || '').replace(/\s+/g, ' ').slice(0, 160)),
    videos: [...document.querySelectorAll('video')].slice(-5).map(v => (v.currentSrc || v.src || '').slice(0, 80))};
}"""


class DreaminaAdapter(WebAdapter):
    def __init__(self, platform: str = "dreamina", url_override: str | None = None):
        super().__init__("dreamina", url_override)
        self.url = (url_override or "").strip() or HOME

    async def _diag(self, page, why: str):
        try:
            L.warning("Dreamina chẩn đoán (%s): %s", why, json.dumps(await page.evaluate(JS_DIAG), ensure_ascii=False)[:3000])
        except Exception as e:
            L.warning("Dreamina chẩn đoán lỗi: %s", e)

    async def _signed_out(self, page) -> bool:
        try:
            txt = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        return bool(re.search(r"Sign in Free credits|Sign in to start creating|Sign in to claim", txt))

    async def is_logged_in(self, page) -> bool:
        if "dreamina" not in page.url and "/dreamina/" not in page.url:
            return False
        if await self._any_visible(page, "captcha_markers") or await self._signed_out(page):
            return False
        return await self._first(page, "prompt", timeout=1500) is not None

    async def check_login(self, page) -> str:
        await asyncio.sleep(3)
        if await self._any_visible(page, "captcha_markers"):
            return "needs_user"
        if await self._signed_out(page):
            return "expired"
        return "ok" if await self._first(page, "prompt", timeout=8000) else "unknown"

    async def _choose(self, page, opener: str, value: str, what: str):
        if not value:
            return
        cur = await page.evaluate(JS_OPEN, opener)
        if cur is None:
            L.warning("Dreamina: không thấy ô chọn %s", what)
            return
        await asyncio.sleep(0.7)
        if cur.lower().startswith(value.lower()):
            await page.keyboard.press("Escape")
            return
        ok = await page.evaluate(JS_PICK_IN_POPUP, value)
        if not ok:
            L.warning("Dreamina: không chọn được %s = %s (đang: %s)", what, value, cur)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)

    async def run_and_save(self, page, job: dict, refs: list[str], params: dict, want: int,
                           on_progress, on_user, timeout_s: int, dest_dir: Path, base_name: str,
                           kind: str) -> list[Path]:
        await page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(3)
        await page.evaluate(JS_CLOSE_MODALS)
        await self.guard(page, on_user)
        if await self._signed_out(page):
            raise JobError("not_logged_in", "Dreamina chưa đăng nhập")
        box = await self._first(page, "prompt", timeout=20000)
        if box is None:
            await self._diag(page, "không thấy ô nhập")
            raise JobError("ui_changed", "không thấy ô nhập prompt của Dreamina (xem chẩn đoán trong Log)")

        await self._choose(page, r"Seedance|Recreate", params.get("model", ""), "model")
        if refs and job.get("mode") == "i2v":
            await self._choose(page, r"^(Omni reference|First and last frames|Multiframes)", "First and last frames", "chế độ")
        ratio = (params.get("ratio") or "").split(" ")[0]
        res = (params.get("quality") or "").upper()
        if ratio or res:
            cur = await page.evaluate(JS_OPEN, r"^\d{1,2}:\d{1,2}")
            if cur is None:
                L.warning("Dreamina: không thấy nút tỷ lệ / độ phân giải")
            else:
                await asyncio.sleep(0.7)
                for v in (ratio, res):
                    if v and not await page.evaluate(JS_PICK_IN_POPUP, v):
                        L.warning("Dreamina: không chọn được %s", v)
                    await asyncio.sleep(0.3)
                await page.keyboard.press("Escape")
        secs = re.findall(r"\d+", params.get("durations") or "")
        if secs and secs[0] != "5":
            cur = await page.evaluate(JS_OPEN, r"^\d{1,2}s$")
            if cur is not None:
                await asyncio.sleep(0.7)
                if not await page.evaluate(JS_PICK_IN_POPUP, secs[0]):
                    L.warning("Dreamina: không đặt được thời lượng %s giây (đang %s)", secs[0], cur)
                await page.keyboard.press("Escape")

        if refs:
            fi = await self._first(page, "file_input", timeout=4000, visible=False)
            if fi is None:
                await self._diag(page, "không thấy ô tải ảnh")
                raise JobError("ui_changed", "không thấy ô tải ảnh tham chiếu của Dreamina")
            await fi.set_input_files(refs[:2] if job.get("mode") == "i2v" else refs[:12])
            await asyncio.sleep(4)

        text = job["prompt"].strip()
        snippet = re.sub(r"\s+", " ", text)[:50].strip()
        box = await self._first(page, "prompt", timeout=8000)
        await box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(text)
        await asyncio.sleep(0.8)

        async def click_generate():
            loc = page.locator("button[aria-label='Generate']")
            for i in range(await loc.count() - 1, -1, -1):
                b = loc.nth(i)
                if await b.is_visible() and not await b.is_disabled():
                    await b.click()
                    return True
            return False

        if not await click_generate():
            await self._diag(page, "nút Generate không bật")
            raise JobError("ui_changed", "nút Generate của Dreamina không bật")
        on_progress(3)
        # bấm ở trang chủ chỉ mở phiên mới: chờ sang /ai-tool/generate rồi bấm lại nếu chưa có khối kết quả
        for _ in range(20):
            await asyncio.sleep(0.5)
            if "ai-tool/generate" in page.url:
                break
        await asyncio.sleep(2.5)
        await page.evaluate(JS_CLOSE_MODALS)
        st = await page.evaluate(JS_RECORD, snippet)
        if not st["found"]:
            await click_generate()

        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(3)
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_RECORD, snippet)
            if not st["found"]:
                if time.monotonic() - start > 45:
                    await self._diag(page, "không thấy khối kết quả")
                    raise JobError("ui_changed", "Dreamina không tạo khối kết quả cho prompt (xem chẩn đoán trong Log)")
                continue
            if st["error"]:
                msg = st["error"][:250]
                if FLAG_RE.search(msg):
                    raise JobError("flagged", "Dreamina: " + msg)
                if BLOCK_RE.search(msg):
                    raise JobError("blocked", msg)
                if QUOTA_RE.search(msg):
                    raise JobError("quota", msg)
                raise JobError("unknown", "Dreamina: " + msg)
            if st["vids"]:
                break
            on_progress(st["pct"] if st["pct"] is not None else min(92, 5 + int((time.monotonic() - start) * 0.5)))
        else:
            await self._diag(page, "hết thời gian")
            raise JobError("timeout")
        on_progress(96)
        dest_dir.mkdir(parents=True, exist_ok=True)
        return [await self.download(page, st["vids"][0], dest_dir / f"{base_name}_1")]
