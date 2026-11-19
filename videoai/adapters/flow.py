"""Adapter Google Flow (flow.google.com) — thao tác qua giao diện web, như người dùng tự làm.

Cấu trúc trang (đọc từ giao diện thật, 11/2026):
- Trang chủ: nút "Dự án mới" (button.mat-mdc-fab, icon 'add') → /project/<id>
- Ô prompt: div.ProseMirror[contenteditable][role=textbox]
- Nút tạo: button.generate-icon-button (type=submit)
- Nút cài đặt: button.settings-trigger-button → bảng trong .cdk-overlay-pane với các nút role=radio,
  chữ đầu là tên icon (không phụ thuộc ngôn ngữ): image / videocam, crop_free (Khung hình) /
  chrome_extension (Thành phần), crop_16_9 / crop_landscape / crop_square / crop_portrait / crop_9_16,
  360p / 720p..., x1..x4; menu model = button.mat-mdc-menu-trigger → [role=menuitem];
  thời lượng = input[type=range] (nhãn "<n> giây").
- Khung đầu/cuối: button.empty-chip (ô trống đầu tiên); thêm thành phần: nút '+' trong ô soạn.
  Hộp chọn: nút 'upload' → input[type=file]; sau khi tải lên chọn button.asset-item theo tên tệp →
  button.detail-add-to-prompt-btn.
- Kết quả: flow-tile-container; đang tạo = flow-pending-tile (có %); xong = flow-image-tile / flow-video-tile.
- Tải về: rê chuột vào ô → nút 'more_vert' → mục 'download' → menu con (ảnh: 1K gốc/2K/4K;
  video: 270p GIF/720p gốc/1080p/4K).
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from ..browser import human
from ..core import log
from ..core.errors import JobError
from .base import WebAdapter

L = log.get("flow")

HOME = "https://flow.google.com/"
RATIO_ICON = {"16:9": "crop_16_9", "4:3": "crop_landscape", "1:1": "crop_square", "3:4": "crop_portrait", "9:16": "crop_9_16"}
BLOCK_WORDS = re.compile(r"(policy|violat|not allowed|unsafe|chính sách|vi phạm|không được phép|không an toàn|bị chặn)", re.I)
QUOTA_WORDS = re.compile(r"(credit|quota|limit|tín dụng|hạn mức|giới hạn|hết lượt|nâng cấp gói|upgrade)", re.I)

JS_SUMMARY = "() => { const t = document.querySelector('button.settings-trigger-button'); return t ? t.innerText : ''; }"

JS_APPLY = r"""
async (o) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const report = [];
  const trig = document.querySelector('button.settings-trigger-button');
  if (!trig) return {report: ['no-settings-button'], cost: null};
  const pane = () => [...document.querySelectorAll('.cdk-overlay-pane')].pop();
  const opened = () => !!document.querySelector('.cdk-overlay-pane button[role=radio]');
  for (let i = 0; i < 4 && !opened(); i++) {        // mở bảng cài đặt chắc chắn (bấm lại nếu chưa mở)
    trig.click();
    for (let k = 0; k < 15 && !opened(); k++) await sleep(100);
  }
  if (!opened()) return {report: ['settings-not-open'], cost: null};
  await sleep(250);
  const radio = (key) => {
    const p = pane(); if (!p) return null;
    return [...p.querySelectorAll('button[role=radio]')].find(b => {
      const t = b.innerText.trim(); return t === key || t.split(/\s+/)[0] === key || t.startsWith(key + ' ');
    });
  };
  const pick = async (key, label) => {
    if (!key) return;
    const b = radio(key);
    if (!b) { report.push('missing:' + label + '=' + key); return; }
    if (b.getAttribute('aria-checked') !== 'true') { b.click(); await sleep(450); }
  };
  await pick(o.kind, 'kind');
  if (o.kind === 'videocam') await pick(o.vmode, 'vmode');
  await pick(o.ratio, 'ratio');
  if (o.model) {
    const p = pane();
    const t = p && p.querySelector('button.mat-mdc-menu-trigger');
    const norm = s => (s || '').replace(/[^\p{L}\p{N}.\- ]/gu, '').replace(/\s+/g, ' ').trim().toLowerCase();
    if (t && !norm(t.innerText).includes(norm(o.model))) {
      t.click(); await sleep(600);
      const m = [...document.querySelectorAll('.cdk-overlay-pane')].pop();
      const it = m && [...m.querySelectorAll('[role=menuitem]')].find(e => norm(e.innerText).startsWith(norm(o.model)));
      if (it) { it.click(); await sleep(600); } else { report.push('missing:model=' + o.model);
        document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(300); }
    } else if (!t) report.push('missing:model-menu');
  }
  await pick(o.res, 'resolution');
  if (o.seconds) {
    const p = pane(); const r = p && p.querySelector('input[type=range]');
    if (r) {
      let ok = false;
      for (let v = +r.min; v <= +r.max; v++) {
        r.value = v; r.dispatchEvent(new Event('input', {bubbles: true})); r.dispatchEvent(new Event('change', {bubbles: true}));
        await sleep(80);
        const m = (pane().innerText || '').match(/(\d+)\s*(giây|seconds?|sec|s\b)/i);
        if (m && +m[1] === o.seconds) { ok = true; break; }
      }
      if (!ok) report.push('missing:duration=' + o.seconds);
    } else report.push('missing:duration-slider');
  }
  await pick(o.count, 'count');
  const esc = () => { const ev = new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true});
    Object.defineProperty(ev, 'keyCode', {get: () => 27}); Object.defineProperty(ev, 'which', {get: () => 27});
    (document.activeElement || document.body).dispatchEvent(ev); };
  const cm = (pane() && pane().innerText || '').match(/(\d[\d.,]*)\s*(tín dụng|credits?)/i);
  const cost = cm ? cm[1] : null;
  esc(); await sleep(300);
  const bd = document.querySelector('.cdk-overlay-backdrop'); if (bd) { bd.click(); await sleep(300); }
  if (document.querySelector('.cdk-overlay-pane button[role=radio]')) { trig.click(); await sleep(300); }
  return {report, cost};
}
"""

JS_MARK = r"""
() => { document.querySelectorAll('flow-tile-container').forEach(t => t.setAttribute('data-va-seen', '1')); return document.querySelectorAll('flow-tile-container').length; }
"""

JS_STATE = r"""
() => {
  const tiles = [...document.querySelectorAll('flow-tile-container:not([data-va-seen])')];
  const out = tiles.map((t, i) => {
    if (!t.getAttribute('data-va-id')) t.setAttribute('data-va-id', 'va' + Math.random().toString(36).slice(2, 10));
    const pending = !!t.querySelector('flow-pending-tile');
    const img = t.querySelector('flow-image-tile img.image, flow-image-tile img');
    const vid = t.querySelector('flow-video-tile');
    const txt = (t.innerText || '').replace(/\s+/g, ' ').trim();
    const m = txt.match(/(\d{1,3})\s*%/);
    let state = pending ? 'pending' : (vid ? 'video' : (img && img.naturalWidth > 0 ? 'image' : (img ? 'loading' : 'other')));
    return {id: t.getAttribute('data-va-id'), state, pct: m ? +m[1] : null, text: txt.slice(0, 300),
            src: img ? (img.currentSrc || img.src) : null};
  });
  const snack = [...document.querySelectorAll('mat-snack-bar-container, .mat-mdc-snack-bar-container, [role=alert], [aria-live=assertive]')]
                  .map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400);
  return {tiles: out, snack, url: location.href};
}
"""


async def safe_click(page, loc, timeout: int = 4000):
    """Bấm nút cho chắc.
    - Nút nằm trong hộp/menu nổi (.cdk-overlay-container): nếu bị che thì bấm bằng script,
      KHÔNG nhấn Escape (Escape sẽ đóng luôn hộp chọn ảnh / menu tải xuống).
    - Nút trên trang: nếu bị lớp phủ che thì Escape đóng lớp phủ rồi bấm lại, cuối cùng bấm bằng script."""
    try:
        await loc.click(timeout=timeout)
        return
    except Exception:
        pass
    try:
        in_overlay = await loc.evaluate("e => !!e.closest('.cdk-overlay-container')", timeout=5000)
    except Exception:
        in_overlay = False
    if not in_overlay:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.4)
            await loc.click(timeout=timeout)
            return
        except Exception:
            pass
    await loc.evaluate("e => { e.scrollIntoView({block:'center'}); e.click(); }", timeout=8000)


JS_CHIPS = """() => {
  const bar = document.querySelector('flow-ingredient-bar') || document;
  const chips = [...bar.querySelectorAll('button.chip-container')];
  return {n: chips.length, busy: chips.filter(c => c.getAttribute('aria-busy') === 'true').length,
          empty: [...bar.querySelectorAll('button.empty-chip')].map(b => (b.innerText || '').trim())};
}"""

JS_CLEAR_CHIPS = """async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 12; i++) {
    const c = document.querySelector('flow-ingredient-bar button.chip-container');
    if (!c) return true;
    c.click();
    await sleep(350);
  }
  return !document.querySelector('flow-ingredient-bar button.chip-container');
}"""


class FlowAdapter(WebAdapter):
    def __init__(self, platform: str = "flow", url_override: str | None = None):
        super().__init__("flow", url_override)
        u = (url_override or "").strip()
        if not u or "labs.google" in u:
            u = HOME
        self.url = u

    # -------------------------------------------------- vào dự án
    async def _signed_out(self, page) -> bool:
        return "accounts.google.com" in page.url or page.url.rstrip("/").endswith("/about")

    async def ensure_project(self, page, on_user):
        if "/project/" in page.url and await self._first(page, ["div.ProseMirror[contenteditable='true']"], timeout=8000):
            return
        if "/project/" in self.url:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=90_000)
        elif "flow.google.com" not in page.url or "/project/" not in page.url:
            await page.goto(HOME, wait_until="domcontentloaded", timeout=90_000)
        await asyncio.sleep(2.5)
        if await self._signed_out(page):
            raise JobError("not_logged_in", "phiên Google đã hết, cần đăng nhập lại")
        if "/project/" not in page.url:
            btn = await self._first(page, ["button[class*='new-project']", "button.mat-mdc-fab:has-text('add')",
                                            "button:has-text('Dự án mới')", "button:has-text('New project')"], timeout=15000)
            if btn is None:
                raise JobError("ui_changed", "không thấy nút Dự án mới")
            await safe_click(page, btn)
            for _ in range(40):
                await asyncio.sleep(0.5)
                if "/project/" in page.url:
                    break
        if not await self._first(page, ["div.ProseMirror[contenteditable='true']"], timeout=20000):
            raise JobError("ui_changed", "không thấy ô nhập prompt trong dự án Flow")

    async def _wait_signed_in(self, page, on_user, minutes: int = 15):
        on_user("needs_user")
        try:
            await page.bring_to_front()
        except Exception:
            pass
        end = time.monotonic() + minutes * 60
        while time.monotonic() < end:
            await asyncio.sleep(3)
            if "flow.google.com" in page.url and not page.url.rstrip("/").endswith("/about"):
                on_user("resumed")
                await asyncio.sleep(2)
                return
        raise JobError("not_logged_in", "chưa đăng nhập Google Flow")

    async def is_logged_in(self, page) -> bool:
        u = page.url
        if "flow.google.com" not in u or "accounts.google.com" in u or u.rstrip("/").endswith("/about"):
            return False
        for sel in ("button.mat-mdc-fab", "div.ProseMirror[contenteditable='true']", "a[href*='/project/']",
                    "flow-tile-container"):
            try:
                if await page.locator(sel).count():
                    return True
            except Exception:
                pass
        return False

    async def check_login(self, page) -> str:
        await page.goto(HOME, wait_until="domcontentloaded", timeout=90_000)
        await asyncio.sleep(3)
        if await self._signed_out(page):
            return "expired"
        if await self._first(page, ["button.mat-mdc-fab", "flow-tile-container", "a[href*='/project/']"], timeout=8000):
            return "ok"
        return "unknown"

    async def read_credits(self, page) -> int | None:
        return None   # Flow chỉ hiện chi phí từng lần tạo trong bảng cài đặt

    # -------------------------------------------------- tùy chọn
    def _options(self, job: dict, params: dict, want: int, kind: str) -> dict:
        ratio = (params.get("ratio") or "").split(" ")[0]
        o = {"kind": "videocam" if kind == "video" else "image", "ratio": RATIO_ICON.get(ratio),
             "model": (params.get("model") or "").strip() or None,
             "count": f"x{max(1, min(4, want))}"}
        if kind == "video":
            o["vmode"] = "chrome_extension" if job["mode"] == "compose" else "crop_free"
            res = params.get("resolutions") or ""
            o["res"] = res.split(" ")[0] if res and res != "Mặc định" else None
            dur = params.get("durations") or ""
            m = re.match(r"(\d+)", dur)
            o["seconds"] = int(m.group(1)) if m else None
        return o

    @staticmethod
    def _summary_mismatch(summary: str, o: dict) -> list[str]:
        """So nút tóm tắt cài đặt của Flow (vd 'Video · 720p · 8 giây crop_16_9 x3') với lựa chọn trong tools."""
        if not summary.strip():
            return []          # không đọc được → không chặn
        words = summary.split()
        bad = []
        if o.get("ratio") and o["ratio"] not in words:
            bad.append("tỷ lệ khung hình")
        if o.get("count") and o["count"] not in words:
            bad.append("số kết quả")
        low = summary.lower()
        if o.get("kind") == "videocam" and "video" not in low:
            bad.append("loại Video")
        if o.get("kind") == "image" and "video" in low:
            bad.append("loại Hình ảnh")
        return bad

    # -------------------------------------------------- ảnh tham chiếu
    async def _chips(self, page) -> dict:
        try:
            return await page.evaluate(JS_CHIPS)
        except Exception:
            return {"n": 0, "busy": 0, "empty": []}

    async def _close_overlays(self, page):
        for _ in range(3):
            if not await page.locator(".cdk-overlay-pane").count():
                return
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.35)

    async def _upload_via_picker(self, page, open_btn, path: str):
        """Mở hộp chọn của Flow → Tải lên → chọn ảnh vừa tải → Thêm vào câu lệnh.
        Chạy được cả giao diện rộng (có nút 'Thêm vào câu lệnh') lẫn giao diện hẹp (bấm ảnh là thêm luôn)."""
        tmpdir = Path(tempfile.mkdtemp())
        name = f"va_{uuid.uuid4().hex[:8]}{Path(path).suffix.lower() or '.png'}"
        f = tmpdir / name
        shutil.copy(path, f)
        before = (await self._chips(page))["n"]
        await safe_click(page, open_btn)
        await human.pause(0.6, 1.0)
        up = await self._first(page, [".cdk-overlay-pane button.sidebar-upload-btn",
                                      ".cdk-overlay-pane button.upload-button",
                                      ".cdk-overlay-pane button[aria-label*='Tải nội dung' i]",
                                      ".cdk-overlay-pane button[aria-label*='upload' i]",
                                      ".cdk-overlay-pane button:has-text('upload')"], timeout=8000)
        if up is None:
            raise JobError("ui_changed", "không thấy nút tải ảnh lên trong hộp chọn")
        try:
            async with page.expect_file_chooser(timeout=10000) as fc:
                await safe_click(page, up)
            chooser = await fc.value
            await chooser.set_files(str(f))
        except Exception:
            inp = page.locator("input[type=file]")
            if not await inp.count():
                raise JobError("ui_changed", "không mở được hộp chọn tệp của Flow")
            await inp.last.set_input_files(str(f))
        item = None
        for _ in range(120):   # chờ tải lên xong (tối đa ~60 giây)
            await asyncio.sleep(0.5)
            if (await self._chips(page))["n"] > before:   # Flow tự thêm luôn
                break
            loc = page.locator(f".cdk-overlay-pane button.asset-item:has-text('{name}')")
            if await loc.count():
                item = loc.first
                break
        if item is not None:
            await safe_click(page, item)
            await human.pause(0.5, 0.9)
            for _ in range(24):   # tối đa ~12 giây
                if (await self._chips(page))["n"] > before:
                    break
                add = page.locator(".cdk-overlay-pane button.detail-add-to-prompt-btn, "
                                   ".cdk-overlay-pane button[class*='add-to-prompt']")
                if await add.count() and await add.first.is_visible():
                    await safe_click(page, add.first)
                await asyncio.sleep(0.5)
        if (await self._chips(page))["n"] <= before:
            await self._close_overlays(page)
            raise JobError("ui_changed", "không thêm được ảnh vào câu lệnh của Flow")
        for _ in range(60):    # chờ ảnh trong ô xử lý xong
            if not (await self._chips(page))["busy"]:
                break
            await asyncio.sleep(0.5)
        await self._close_overlays(page)
        await human.pause(0.4, 0.8)

    async def _composer(self, page):
        return page.locator("div.ProseMirror[contenteditable='true']").first

    async def _plus_button(self, page):
        await page.keyboard.press("Escape")       # đóng menu cài đặt còn mở (nếu có) để không che nút
        await asyncio.sleep(0.3)
        loc = page.locator("form button[aria-label*='thành phần' i], form button[aria-label*='ingredient' i], "
                           "button[aria-label*='Thêm thành phần' i], button[aria-label*='Add ingredient' i]")
        n = await loc.count()
        for i in range(n):
            b = loc.nth(i)
            if await b.is_visible():
                return b
        # dự phòng: nút có icon add trong ô soạn
        loc = page.locator("form button:has-text('add')")
        return loc.first if await loc.count() else None

    async def clear_refs(self, page):
        """Bỏ ảnh tham chiếu/khung hình còn sót từ lần tạo trước (Flow giữ lại trong ô nhập)."""
        try:
            await page.evaluate(JS_CLEAR_CHIPS)
        except Exception as e:
            L.debug("clear chips: %s", e)

    async def attach(self, page, job: dict, refs: list[str]):
        await self.clear_refs(page)
        if not refs:
            return
        if job["mode"] == "i2v":
            for i, path in enumerate(refs[:2]):   # khung đầu, khung cuối
                want = ("Bắt đầu", "Start") if i == 0 else ("Kết thúc", "End")
                slot = None
                for _ in range(16):
                    loc = page.locator("flow-ingredient-bar button.empty-chip, button.empty-chip")
                    n = await loc.count()
                    for k in range(n):
                        tx = ((await loc.nth(k).inner_text()) or "").strip()
                        if any(tx.lower().startswith(w.lower()) for w in want):
                            slot = loc.nth(k)
                            break
                    if slot is None and n:
                        slot = loc.first
                    if slot is not None:
                        break
                    await asyncio.sleep(0.5)
                if slot is None:
                    raise JobError("ui_changed", "không thấy ô khung hình đầu/cuối (kiểm tra chế độ Ảnh - Video)")
                await self._upload_via_picker(page, slot, path)
        else:
            for path in refs:
                plus = await self._plus_button(page)
                if plus is None:
                    raise JobError("ui_changed", "không thấy nút thêm ảnh tham chiếu")
                await self._upload_via_picker(page, plus, path)

    # -------------------------------------------------- chạy
    async def run_and_save(self, page, job: dict, refs: list[str], params: dict, want: int,
                           on_progress, on_user, timeout_s: int, dest_dir: Path, base_name: str,
                           kind: str) -> list[Path]:
        await self.ensure_project(page, on_user)
        opts = self._options(job, params, want, kind)
        for attempt in range(3):
            res = await page.evaluate(JS_APPLY, opts)
            for _ in range(3):   # chắc chắn đã đóng bảng cài đặt (lớp phủ của nó chặn các nút khác)
                if not await page.locator(".cdk-overlay-pane button[role=radio], .cdk-overlay-backdrop").count():
                    break
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.4)
            summary = (await page.evaluate(JS_SUMMARY)) or ""
            bad = self._summary_mismatch(summary, opts)
            if not bad:
                break
            L.info("Flow: cài đặt chưa đúng (%s; Flow đang ghi: %s) → đặt lại", ", ".join(bad), " ".join(summary.split()))
            await asyncio.sleep(0.6)
        else:
            raise JobError("ui_changed", "không đặt được " + ", ".join(bad) + " trên Flow (không tạo để tránh tốn tín dụng)")
        report = res.get("report", []) if isinstance(res, dict) else (res or [])
        for r in report:
            if r.startswith(("missing:resolution", "missing:duration")):
                L.info("Flow: model này không có tùy chọn %s, dùng mặc định của model", r.split(":", 1)[1].split("=")[0])
            else:
                L.warning("Flow: không chọn được %s (giữ lựa chọn đang có trên trang)", r)
        if isinstance(res, dict) and res.get("cost"):
            L.info("Flow: lần tạo này tốn khoảng %s tín dụng (theo Flow)", res["cost"])
        await self.attach(page, job, refs)

        box = await self._composer(page)
        await safe_click(page, box)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(job["prompt"])
        await human.pause(0.5, 1.0)
        await page.evaluate(JS_MARK)
        btn = await self._first(page, ["button.generate-icon-button", "button[type='submit']"], timeout=8000)
        if btn is None:
            raise JobError("ui_changed", "không thấy nút tạo")
        if await btn.is_disabled():
            await asyncio.sleep(2)
        await safe_click(page, btn)
        on_progress(3)

        start = time.monotonic()
        done_tiles: list[dict] = []
        seen_any = False
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(2.5)
            if await self._signed_out(page):
                raise JobError("not_logged_in", "phiên Google đã hết, cần đăng nhập lại")
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_STATE)
            tiles = st["tiles"]
            if tiles:
                seen_any = True
            pend = [t for t in tiles if t["state"] in ("pending", "loading")]
            ok = [t for t in tiles if t["state"] in ("image", "video")]
            bad = [t for t in tiles if t["state"] == "other"]
            pcts = [t["pct"] for t in pend if t["pct"] is not None]
            if pcts:
                on_progress(max(5, min(95, int(sum(pcts) / len(pcts)))))
            if tiles and not pend:
                done_tiles = ok
                if not ok and bad:
                    msg = " / ".join(t["text"] for t in bad)
                    raise JobError("blocked" if BLOCK_WORDS.search(msg) else ("quota" if QUOTA_WORDS.search(msg) else "unknown"), msg[:300])
                break
            if not seen_any and time.monotonic() - start > 30:
                msg = st.get("snack") or ""
                if msg:
                    raise JobError("blocked" if BLOCK_WORDS.search(msg) else ("quota" if QUOTA_WORDS.search(msg) else "unknown"), msg[:300])
                if time.monotonic() - start > 60:
                    raise JobError("unknown", "Flow không bắt đầu tạo (không có ô kết quả mới)")
        else:
            raise JobError("timeout")
        if not done_tiles:
            raise JobError("timeout")

        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        for n, t in enumerate(done_tiles[:max(1, want)], 1):
            out = dest_dir / f"{base_name}_{n}"
            try:
                try:
                    saved.append(await self._download_tile(page, t, out, kind, params.get("quality")))
                except Exception as e1:
                    L.info("Flow: tải lần 1 lỗi (%s), thử lại", str(e1).splitlines()[0][:160])
                    await self._close_overlays(page)
                    saved.append(await self._download_tile(page, t, out, kind, params.get("quality")))
            except Exception as e:
                L.warning("Flow: không tải được bản %s qua menu (%s) → tải bản xem trước",
                          params.get("quality") or "gốc", str(e).splitlines()[0][:160])
                if t.get("src"):
                    saved.append(await self.download(page, t["src"], out))
                else:
                    raise JobError("download", str(e))
        return saved

    async def _download_tile(self, page, t: dict, out_noext: Path, kind: str, quality: str | None = None) -> Path:
        tile = page.locator(f"flow-tile-container[data-va-id='{t['id']}']")
        await tile.scroll_into_view_if_needed()
        await tile.hover()
        await human.pause(0.4, 0.7)
        more = tile.locator("button:has-text('more_vert')").first
        await safe_click(page, more)
        await human.pause(0.4, 0.7)
        dl = page.locator(".cdk-overlay-pane [role=menuitem]:has-text('download')").last
        await safe_click(page, dl)
        await human.pause(0.5, 0.9)
        items = page.locator(".cdk-overlay-pane").last.locator("[role=menuitem]")
        n = await items.count()
        texts = [((await items.nth(i).inner_text()) or "") for i in range(n)]
        idx = None
        q = (quality or "").strip().lower()
        if q:   # chất lượng người dùng chọn: 1K / 2K / 4K (ảnh) · 720p / 1080p / 4K (video)
            idx = next((i for i, tx in enumerate(texts) if tx.strip().lower().startswith(q)), None)
            if idx is None:
                L.warning("Flow: không có lựa chọn tải %s, dùng bản gốc", quality)
        if idx is None:
            idx = 0
            for i, tx in enumerate(texts):   # bản gốc, bỏ GIF
                low = tx.lower()
                if "gif" in low:
                    continue
                if "gốc" in low or "original" in low:
                    idx = i
                    break
            else:
                idx = next((i for i, tx in enumerate(texts) if "gif" not in tx.lower()), 0)
        upscaled = q in ("2k", "4k", "1080p")
        async with page.expect_download(timeout=1_200_000 if upscaled else 300_000) as dinfo:   # tăng độ phân giải cần thêm thời gian
            await safe_click(page, items.nth(idx))
        d = await dinfo.value
        if upscaled:
            L.info("Flow: đang nhận bản %s (Flow nâng cấp xong mới tải, tín dụng tính theo Flow)", quality)
        suffix = Path(d.suggested_filename or "").suffix or (".mp4" if kind == "video" else ".png")
        out = out_noext.with_suffix(suffix.lower())
        k = 1
        while out.exists():
            out = out_noext.with_name(f"{out_noext.name}_{k}").with_suffix(suffix.lower())
            k += 1
        await d.save_as(str(out))
        await page.keyboard.press("Escape")
        return out
