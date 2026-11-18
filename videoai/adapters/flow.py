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

JS_APPLY = r"""
async (o) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const report = [];
  const trig = document.querySelector('button.settings-trigger-button');
  if (!trig) return ['no-settings-button'];
  trig.click(); await sleep(700);
  const pane = () => [...document.querySelectorAll('.cdk-overlay-pane')].pop();
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
  const cm = (pane() && pane().innerText || '').match(/(\d[\d.,]*)\s*(tín dụng|credits?)/i);
  const cost = cm ? cm[1] : null;
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await sleep(300);
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
            await self._wait_signed_in(page, on_user)
        if "/project/" not in page.url:
            btn = await self._first(page, ["button[class*='new-project']", "button.mat-mdc-fab:has-text('add')",
                                            "button:has-text('Dự án mới')", "button:has-text('New project')"], timeout=15000)
            if btn is None:
                raise JobError("ui_changed", "không thấy nút Dự án mới")
            await btn.click()
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

    # -------------------------------------------------- ảnh tham chiếu
    async def _upload_via_picker(self, page, open_btn, path: str):
        tmpdir = Path(tempfile.mkdtemp())
        name = f"va_{uuid.uuid4().hex[:8]}{Path(path).suffix.lower() or '.png'}"
        f = tmpdir / name
        shutil.copy(path, f)
        await open_btn.click()
        await human.pause(0.6, 1.0)
        up = await self._first(page, [".cdk-overlay-pane button:has-text('upload')"], timeout=8000)
        if up is None:
            raise JobError("ui_changed", "không thấy nút tải ảnh lên trong hộp chọn")
        async with page.expect_file_chooser(timeout=15000) as fc:
            await up.click()
        chooser = await fc.value
        await chooser.set_files(str(f))
        item = None
        for _ in range(90):   # chờ tải lên xong (tối đa ~45 giây)
            await asyncio.sleep(0.5)
            loc = page.locator(f".cdk-overlay-pane button.asset-item:has-text('{name}')")
            if await loc.count():
                item = loc.first
                break
        if item is None:
            raise JobError("ui_changed", "ảnh tải lên không xuất hiện trong danh sách")
        await item.click()
        await human.pause(0.4, 0.8)
        add = await self._first(page, [".cdk-overlay-pane button.detail-add-to-prompt-btn",
                                       ".cdk-overlay-pane button[class*='add-to-prompt']"], timeout=8000)
        if add is None:
            raise JobError("ui_changed", "không thấy nút thêm ảnh vào câu lệnh")
        await add.click()
        await human.pause(0.8, 1.4)

    async def _composer(self, page):
        return page.locator("div.ProseMirror[contenteditable='true']").first

    async def _plus_button(self, page):
        loc = page.locator("button[aria-label*='thành phần' i], button[aria-label*='ingredient' i], "
                           "button[aria-label*='Add' i][type='button']")
        n = await loc.count()
        for i in range(n):
            b = loc.nth(i)
            if await b.is_visible():
                return b
        # dự phòng: nút có icon add trong ô soạn
        loc = page.locator("form button:has-text('add')")
        return loc.first if await loc.count() else None

    async def attach(self, page, job: dict, refs: list[str]):
        if not refs:
            return
        if job["mode"] == "i2v":
            for path in refs[:2]:   # khung đầu, khung cuối
                slot = await self._first(page, ["button.empty-chip"], timeout=8000)
                if slot is None:
                    raise JobError("ui_changed", "không thấy ô khung hình đầu/cuối")
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
        res = await page.evaluate(JS_APPLY, self._options(job, params, want, kind))
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
        await box.click()
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
        await btn.click()
        on_progress(3)

        start = time.monotonic()
        done_tiles: list[dict] = []
        seen_any = False
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(2.5)
            if await self._signed_out(page):
                await self._wait_signed_in(page, on_user)
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
                saved.append(await self._download_tile(page, t, out, kind))
            except Exception as e:
                L.warning("Flow: tải qua menu lỗi (%s), thử tải trực tiếp", e)
                if t.get("src"):
                    saved.append(await self.download(page, t["src"], out))
                else:
                    raise JobError("download", str(e))
        return saved

    async def _download_tile(self, page, t: dict, out_noext: Path, kind: str) -> Path:
        tile = page.locator(f"flow-tile-container[data-va-id='{t['id']}']")
        await tile.scroll_into_view_if_needed()
        await tile.hover()
        await human.pause(0.4, 0.7)
        more = tile.locator("button:has-text('more_vert')").first
        await more.click()
        await human.pause(0.4, 0.7)
        dl = page.locator(".cdk-overlay-pane [role=menuitem]:has-text('download')").last
        await dl.click()
        await human.pause(0.5, 0.9)
        items = page.locator(".cdk-overlay-pane").last.locator("[role=menuitem]")
        n = await items.count()
        texts = [((await items.nth(i).inner_text()) or "") for i in range(n)]
        idx = 0
        for i, tx in enumerate(texts):   # chọn bản gốc, bỏ GIF
            low = tx.lower()
            if "gif" in low:
                continue
            if "gốc" in low or "original" in low:
                idx = i
                break
        else:
            idx = next((i for i, tx in enumerate(texts) if "gif" not in tx.lower()), 0)
        async with page.expect_download(timeout=300_000) as dinfo:
            await items.nth(idx).click()
        d = await dinfo.value
        suffix = Path(d.suggested_filename or "").suffix or (".mp4" if kind == "video" else ".png")
        out = out_noext.with_suffix(suffix.lower())
        k = 1
        while out.exists():
            out = out_noext.with_name(f"{out_noext.name}_{k}").with_suffix(suffix.lower())
            k += 1
        await d.save_as(str(out))
        await page.keyboard.press("Escape")
        return out
