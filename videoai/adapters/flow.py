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
FLAG_WORDS = re.compile(r"(hoạt động bất thường|unusual activity|tiện ích trình duyệt|browser extension)", re.I)
QUOTA_WORDS = re.compile(r"(credit|quota|limit|tín dụng|hạn mức|giới hạn|hết lượt|nâng cấp gói|upgrade)", re.I)

JS_SUMMARY = "() => { const t = document.querySelector('button.settings-trigger-button'); return t ? t.innerText : ''; }"

JS_APPLY = r"""
async (o) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const report = [];
  const trig = document.querySelector('button.settings-trigger-button');
  if (!trig) return {report: ['no-settings-button'], cost: null};
  const pane = () => { const r = document.querySelector('.cdk-overlay-pane button[role=radio]');
    return r ? r.closest('.cdk-overlay-pane') : [...document.querySelectorAll('.cdk-overlay-pane')].pop(); };
  const opened = () => !!document.querySelector('.cdk-overlay-pane button[role=radio]');
  for (let i = 0; i < 4 && !opened(); i++) {        // mở bảng cài đặt chắc chắn (bấm lại nếu chưa mở)
    trig.click();
    for (let k = 0; k < 15 && !opened(); k++) await sleep(100);
  }
  if (!opened()) return {report: ['settings-not-open'], cost: null};
  await sleep(250);
  const radio = (key) => {           // tìm trong mọi khung nổi (khung cuối có thể là tooltip, không phải bảng cài đặt)
    return [...document.querySelectorAll('.cdk-overlay-pane button[role=radio]')].find(b => {
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

# Nhận diện ô kết quả bằng "khóa" lấy từ địa chỉ ảnh/video của chính ô đó (không đổi khi Flow vẽ lại lưới).
# Thuộc tính tự gắn vào thẻ (data-*) sẽ mất khi Flow vẽ lại → không dùng để phân biệt ô cũ/mới.
JS_TILE_LIB = r"""
const vaKey = (t) => {
  const v = t.querySelector('video'); const im = t.querySelector('img');
  let s = (v && (v.currentSrc || v.src || v.poster)) || (im && (im.currentSrc || im.src)) || '';
  if (s && !s.startsWith('data:')) return s.split('=')[0].split('?')[0];
  if (t.querySelector('flow-pending-tile')) return null;            // đang tạo: chưa có khóa
  const tx = (t.innerText || '').replace(/\s+/g, ' ').trim();       // ô lỗi (không có ảnh/video): khóa theo nội dung
  return tx ? 'txt:' + tx.slice(0, 200) : null;
};
const vaUpload = (t) => /(^|\s)(va_[0-9a-f]{8}|[\w\-. ]+\.(png|jpe?g|webp|bmp|gif))(\s|$)/i.test((t.innerText || '').replace(/\s+/g, ' '));
const vaHash = (s) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return 'va' + (h >>> 0).toString(36); };
"""

JS_KEYS = "() => {" + JS_TILE_LIB + "return [...document.querySelectorAll('flow-tile-container')].map(vaKey).filter(Boolean); }"

JS_STATE = "(seen) => {" + JS_TILE_LIB + r"""
  const old = new Map();                               // khóa → số ô đã có trước khi bấm Tạo (tính cả ô trùng nội dung)
  for (const k of (seen || [])) old.set(k, (old.get(k) || 0) + 1);
  const out = [];
  for (const t of document.querySelectorAll('flow-tile-container')) {
    const key = vaKey(t);
    if (key && old.get(key) > 0) { old.set(key, old.get(key) - 1); continue; }   // ô đã có trước khi bấm Tạo
    const pending = !!t.querySelector('flow-pending-tile');
    // v2.1.12: chỉ là "video" khi ô có thẻ <video> thật. Ô video LỖI (vd. "Không thể tạo video vì hoạt động bất
    // thường") vẫn là flow-video-tile nhưng không có video → trước đây bị coi là xong, tải lỗi rồi tạo lại liên tục
    // trên các tài khoản khác (càng dễ bị Google gắn cờ).
    const vid = t.querySelector('video');
    const vtile = t.querySelector('flow-video-tile');
    const img = t.querySelector('flow-image-tile img.image, flow-image-tile img, img');
    const txt = (t.innerText || '').replace(/\s+/g, ' ').trim();
    if (!pending && vaUpload(t)) continue;             // ảnh tham chiếu vừa tải lên, không phải kết quả
    const m = txt.match(/(\d{1,3})\s*%/);
    const failTxt = /(bất thường|unusual|không thể|couldn.?t|could not|can.?t generate|failed|thất bại|vi phạm|violat|policy|chính sách|thử lại|try again)/i.test(txt);
    const hasImg = img && img.naturalWidth > 0;
    // v2.2.3: ô VIDEO đã xong thường chỉ hiện ẢNH poster (chưa có thẻ <video> cho tới khi rê chuột). Trước đây bị
    // nhận nhầm là "image" → báo "trả về image thay vì video" → tool gửi tạo lại → 1 tác vụ ra nhiều kết quả trong Flow.
    // Giờ: ô flow-video-tile có <video> HOẶC ảnh poster HOẶC đã có khóa (src) = video đã xong.
    let state;
    if (pending) state = 'pending';
    else if (vtile && !failTxt && (vid || hasImg || key)) state = 'video';
    else if (vid) state = 'video';
    else if (hasImg && !vtile) state = 'image';
    else if (img || (vtile && !failTxt)) state = 'loading';
    else state = 'other';
    const v = t.querySelector('video');
    out.push({key, id: key ? vaHash(key) : null, state, pct: m ? +m[1] : null, text: txt.slice(0, 300),
              src: img ? (img.currentSrc || img.src) : null, vsrc: v ? (v.currentSrc || v.src || null) : null});
  }
  const snack = [...document.querySelectorAll('mat-snack-bar-container, .mat-mdc-snack-bar-container, [role=alert], [aria-live=assertive]')]
                  .map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400);
  return {tiles: out, snack, url: location.href};
}"""

# Gắn lại thẻ cho đúng ô có khóa này (ngay trước khi thao tác) và trả về id
JS_TAG = "(key) => {" + JS_TILE_LIB + r"""
  for (const t of document.querySelectorAll('flow-tile-container')) {
    if (vaKey(t) === key) { const id = vaHash(key); t.setAttribute('data-va-id', id); t.scrollIntoView({block: 'center'}); return id; }
  }
  return null;
}"""


def split_extend(prompt: str) -> list[str]:
    """Prompt chế độ Kéo dài: 'cảnh đầu || đoạn kéo dài 1 || đoạn kéo dài 2'."""
    return [x.strip() for x in re.split(r"\s*\|\|\s*", prompt or "") if x.strip()]


# Đặt thanh trượt "Kéo dài thời lượng" (3–10 giây) rồi đóng bảng; trả về giá trị đang đặt
JS_EXTEND_SECS = r"""async (secs) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let inp = null;
  for (let i = 0; i < 10 && !inp; i++) {
    inp = [...document.querySelectorAll('.cdk-overlay-pane input[type=range]')].pop() || null;
    if (!inp) await sleep(300);
  }
  if (!inp) return null;
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  set.call(inp, String(secs));
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  inp.dispatchEvent(new Event('change', {bubbles: true}));
  await sleep(300);
  const v = inp.value;
  const bd = document.querySelector('.cdk-overlay-backdrop');   // KHÔNG nhấn Escape: Escape thoát trình chỉnh sửa
  if (bd) bd.click();
  await sleep(300);
  return v;
}"""

JS_EXTEND_STATE = r"""() => {
  const clips = [...document.querySelectorAll('.clip')];
  const generating = clips.some(c => /extend-generating|is-generating/.test(c.className)) ||
                     /Đang kéo dài|Extending/i.test(document.body.innerText);
  const composing = clips.some(c => /extend-compos/.test(c.className));
  const panel = [...document.querySelectorAll("button[aria-label='Thoát khỏi chế độ mở rộng']")].some(b => b.offsetParent);
  const bad = clips.filter(c => /fail|error/i.test(c.className));
  const snack = [...document.querySelectorAll('mat-snack-bar-container, .mat-mdc-snack-bar-container, [role=alert], [aria-live=assertive]')]
                  .map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400);
  return {generating, composing, panel, failed: bad.map(c => (c.innerText || 'lỗi').replace(/\s+/g, ' ').trim()).join(' / ').slice(0, 300), snack};
}"""


# Lần đầu tài khoản Google vào Flow: hộp Điều khoản / Chính sách, màn chào, hướng dẫn nhanh, banner cookie.
# Trả về {act, tag} — act: 'consent' (cần người dùng đồng ý trong tools) | 'check' | 'agree' | 'next' | 'dismiss' | 'reject' | ''
JS_ONBOARD = r"""(consent) => {
  const vis = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const label = b => {                                    // bỏ tên icon material (arrow_forward, close…) ở đầu / cuối
    let t = norm(b.innerText || b.value || '');
    t = t.replace(/^([a-z]+(_[a-z]+)+|close|check|add)\s+/, '').replace(/\s+([a-z]+(_[a-z]+)+|close|check)$/, '');
    return (t || norm(b.getAttribute('aria-label') || '')).toLowerCase();
  };
  const TERMS = /(điều khoản|chính sách|quyền riêng tư|terms|privacy|policy|policies)/i;
  const MARKETING = /(email|e-mail|tin tức|cập nhật|ưu đãi|khuyến mãi|news|updates|offers|marketing|khảo sát|survey|nghiên cứu|research|feedback|góp ý)/i;
  const RIGHTS = /(Quyền sử dụng|quyền cần thiết|necessary rights|rights to use)/i;
  const COOKIE = /(cookie)/i;
  const AGREE = /^(tôi đồng ý|đồng ý|chấp nhận|tôi chấp nhận|i agree|agree|accept|i accept|agree and continue|đồng ý và tiếp tục)$/;
  const NEXT = /^(tiếp tục|tiếp theo|continue|next|bắt đầu|bắt đầu ngay|get started|let's go|let’s go|start|start creating|bắt đầu tạo|try now|try it now|dùng thử|dùng thử ngay|thử ngay|create with flow|tạo bằng flow|tạo với flow|try flow|thử flow|dùng flow|go to flow|chuyển đến flow|mở flow)$/;
  const DISMISS = /^(đã hiểu|tôi đã hiểu|got it|bỏ qua|skip|skip tour|bỏ qua phần giới thiệu|đóng|close|ok|okay|no thanks|no, thanks|không, cảm ơn|không cảm ơn|để sau|later|maybe later|not now|dismiss|xong|done)$/;
  const REJECT = /^(từ chối|từ chối tất cả|reject|reject all|chỉ cookie cần thiết|only necessary|necessary only)$/;
  const main = document.querySelector("div.ProseMirror[contenteditable='true']");
  const fab = document.querySelector("button.mat-mdc-fab, button[class*='new-project']");
  let boxes = [...document.querySelectorAll("[role=dialog], [role=alertdialog], mat-dialog-container, .cdk-overlay-pane, [aria-modal=true]")]
    .filter(vis).filter(c => !c.closest('[role=menu], [role=listbox]') && !c.querySelector('[role=menu], [role=listbox]'))
    .filter(c => !RIGHTS.test(c.innerText || ''));
  // màn chào / điều khoản chiếm cả trang (chưa vào được trang chủ Flow): xét cả trang
  if (!boxes.length && !main && !fab) boxes = [document.body];
  document.querySelectorAll('[data-va-onb]').forEach(e => e.removeAttribute('data-va-onb'));
  const tag = e => { e.setAttribute('data-va-onb', '1'); return true; };
  for (const c of boxes.reverse()) {
    const text = c.innerText || '';
    const btns = [...c.querySelectorAll("button, [role=button], a[role=link], a.button, input[type=submit]")]
      .filter(vis).filter(b => !b.disabled && b.getAttribute('aria-disabled') !== 'true');
    const find = re => btns.find(b => re.test(label(b)));
    if (COOKIE.test(text) && !TERMS.test(text.replace(/cookie[^.]*\./ig, ''))) {   // banner cookie → từ chối cookie không cần thiết
      const r = find(REJECT); if (r && tag(r)) return {act: 'reject', what: label(r)};
    }
    const terms = TERMS.test(text) && (find(AGREE) || c.querySelector("input[type=checkbox], [role=checkbox]"));
    if (terms && !consent) return {act: 'consent', what: norm(text).slice(0, 160)};
    const cbs = [...c.querySelectorAll("input[type=checkbox], [role=checkbox]")];
    for (const cb of cbs) {
      const on = cb.type === 'checkbox' ? cb.checked : cb.getAttribute('aria-checked') === 'true';
      if (on) continue;
      const lab = norm((cb.closest('label, mat-checkbox, .mdc-form-field, li, div') || cb).innerText || cb.getAttribute('aria-label') || '');
      if (MARKETING.test(lab) && !TERMS.test(lab)) continue;            // email quảng cáo / khảo sát: để trống
      if (!TERMS.test(lab) && !cb.required && cb.getAttribute('aria-required') !== 'true') continue;
      const t = cb.type === 'checkbox' && !vis(cb) ? (cb.closest('label, mat-checkbox') || cb) : cb;
      if (tag(t)) return {act: 'check', what: lab.slice(0, 120)};
    }
    let b = find(AGREE); if (b && tag(b)) return {act: 'agree', what: label(b)};
    const order = c === document.body ? [[NEXT, 'next'], [DISMISS, 'dismiss']] : [[DISMISS, 'dismiss'], [NEXT, 'next']];
    for (const [re, act] of order) { b = find(re); if (b && tag(b)) return {act, what: label(b)}; }  // hộp chào / mẹo: ưu tiên Bỏ qua
  }
  return {act: ''};
}"""


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
        self.rights_ok = False
        self.terms_ok = False
        u = (url_override or "").strip()
        if not u or "labs.google" in u:
            u = HOME
        self.url = u

    # -------------------------------------------------- vào dự án
    async def _signed_out(self, page) -> bool:
        return "accounts.google.com" in page.url or page.url.rstrip("/").endswith("/about")

    async def onboarding(self, page, max_steps: int = 12) -> int:
        """Tài khoản Google lần đầu vào Flow: tick ô Điều khoản / Chính sách (bắt buộc) rồi bấm Đồng ý / Tiếp tục,
        bỏ qua màn chào + hướng dẫn nhanh, từ chối cookie không cần thiết. Ô nhận email quảng cáo / khảo sát để trống.
        Chỉ tự đồng ý điều khoản khi người dùng đã xác nhận trong tools (Cài đặt lưu 'flow_terms_ok').
        Trả về số bước đã làm."""
        done = idle = 0
        for _ in range(max_steps):
            try:
                st = await page.evaluate(JS_ONBOARD, self.terms_ok)
            except Exception:
                st = {"act": ""}
            act = st.get("act") or ""
            if act == "consent":
                raise JobError("bad_input", "Flow yêu cầu chấp nhận Điều khoản & Chính sách của Google (lần đầu dùng Flow) – "
                                            "bấm Bắt đầu lại trong tools và chọn \"Tôi đồng ý\" ở hộp xác nhận")
            if not act:
                idle += 1
                if idle >= 2:
                    break
                await asyncio.sleep(1.2)
                continue
            idle = 0
            loc = page.locator("[data-va-onb]").first
            try:
                await safe_click(page, loc)
            except Exception as e:
                L.warning("Flow: không bấm được bước làm quen (%s): %s", act, e)
                break
            done += 1
            L.info("Flow lần đầu: %s – %s", {"check": "tick ô", "agree": "đồng ý điều khoản", "next": "tiếp tục",
                                              "dismiss": "bỏ qua giới thiệu", "reject": "từ chối cookie không cần thiết"}.get(act, act),
                   (st.get("what") or "")[:100])
            await asyncio.sleep(1.5)
        return done

    PROJECT_MAX_TILES = 12      # dự án đã nhiều kết quả → tạo dự án mới (trang nhẹ, chạy nhanh, ít lỗi – giống G-Labs)

    async def _refresh_session(self, page) -> bool:
        """Trang bị đẩy về accounts.google.com / trang giới thiệu dù vẫn còn cookie đăng nhập: thường chỉ cần tải lại
        trang là Google khôi phục phiên (y như người dùng bấm làm mới). Trả về True nếu đã vào lại được Flow.
        KHÔNG đăng nhập hộ, không điền mật khẩu, không lách – chỉ làm mới phiên hợp lệ đang có."""
        if not await self.has_login_cookie(page):
            return False                      # không còn cookie đăng nhập → đúng là đã đăng xuất, không cố làm mới
        for attempt in range(2):
            try:
                await page.goto(HOME, wait_until="domcontentloaded", timeout=90_000)
            except Exception:
                pass
            await asyncio.sleep(2.5)
            if "accounts.google.com" not in page.url and not page.url.rstrip("/").endswith("/about"):
                L.info("Flow: phiên Google được làm mới sau khi tải lại trang (lần %d)", attempt + 1)
                return True
            await self.onboarding(page, 6)       # qua trang giới thiệu nếu có
            await asyncio.sleep(1.5)
            if "accounts.google.com" not in page.url and not page.url.rstrip("/").endswith("/about"):
                return True
        return False

    async def ensure_project(self, page, on_user):
        if "/project/" in page.url and await self._first(page, ["div.ProseMirror[contenteditable='true']"], timeout=8000):
            try:
                n = await page.locator("flow-tile-container").count()
            except Exception:
                n = 0
            if n < self.PROJECT_MAX_TILES or "/project/" in self.url:
                await self.onboarding(page, 4)
                return
            L.info("Flow: dự án đã có %d kết quả → mở dự án mới cho nhẹ trang", n)
            await page.goto(HOME, wait_until="domcontentloaded", timeout=90_000)
            await asyncio.sleep(2)
        if "/project/" in self.url:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=90_000)
        elif "/project/" not in page.url:
            await page.goto(self.url, wait_until="domcontentloaded", timeout=90_000)
        await asyncio.sleep(2.5)
        if "accounts.google.com" in page.url and not await self._refresh_session(page):
            raise JobError("not_logged_in", "phiên Google đã hết, cần đăng nhập lại")
        await self.onboarding(page)                      # trang giới thiệu (/about), điều khoản, màn chào
        await asyncio.sleep(1)
        if await self._signed_out(page) and not await self._refresh_session(page):
            raise JobError("not_logged_in", "phiên Google đã hết, cần đăng nhập lại")
        if "/project/" not in page.url:
            btn = await self._first(page, ["button[class*='new-project']", "button.mat-mdc-fab:has-text('add')",
                                            "button:has-text('Dự án mới')", "button:has-text('New project')",
                                            "button:has-text('Tạo dự án')", "button:has-text('Create project')",
                                            "button:has-text('Bắt đầu dự án')", "button:has-text('Start a project')",
                                            "button:has-text('Start a new project')"], timeout=15000)
            if btn is None:
                await self.onboarding(page)
                btn = await self._first(page, ["button[class*='new-project']", "button.mat-mdc-fab:has-text('add')",
                                                "button:has-text('Dự án mới')", "button:has-text('New project')"], timeout=10000)
            if btn is None:
                raise JobError("ui_changed", "không thấy nút Dự án mới")
            await safe_click(page, btn)
            for _ in range(40):
                await asyncio.sleep(0.5)
                if "/project/" in page.url:
                    break
            L.info("Flow: đã tạo dự án mới")
        await asyncio.sleep(1)
        await self.onboarding(page, 6)                   # hướng dẫn nhanh khi mở dự án đầu tiên
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

    LOGIN_COOKIES = (("google.com", "__Secure-1PSID"), ("google.com", "SID"))

    async def check_login(self, page) -> str:
        await page.goto(HOME, wait_until="domcontentloaded", timeout=90_000)
        await asyncio.sleep(3)
        if "accounts.google.com" not in page.url and page.url.rstrip("/").endswith("/about"):
            # tài khoản mới vào Flow lần đầu: Flow hiện trang giới thiệu (/about) dù Google đã đăng nhập
            # → trước đây báo nhầm "chưa đăng nhập". Bấm "Tạo bằng Flow" / qua màn chào rồi mới kiểm tra.
            await self.onboarding(page, 8)
            for _ in range(10):
                await asyncio.sleep(1)
                if not page.url.rstrip("/").endswith("/about"):
                    break
            await self.onboarding(page, 6)
        if "accounts.google.com" in page.url:
            return "expired"
        if await self._signed_out(page):
            return "ok" if await self.has_login_cookie(page) else "expired"
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
    def _classify(msg: str) -> str:
        if FLAG_WORDS.search(msg):
            return "flagged"          # Google phát hiện bất thường: không lách, chỉ dừng tài khoản và báo người dùng
        if BLOCK_WORDS.search(msg):
            return "blocked"
        return "quota" if QUOTA_WORDS.search(msg) else "unknown"

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

    JS_AGENT = r"""(turnOff) => {
      // chế độ "bảng điều khiển bên" của Tác nhân Flow: ô nhập nằm trong bảng bên, công tắc bị ẩn → đóng bảng trước
      const close = [...document.querySelectorAll('button')].find(x => x.offsetParent && /right_panel_close/.test(x.innerText || ''));
      if (close && document.querySelector('.agent-panel-prompt-box')) { if (turnOff) close.click(); return 'panel'; }
      const b = [...document.querySelectorAll('button')].find(x => /Tác nhân Flow|Flow agent|Flow Agent/i.test(x.getAttribute('aria-label') || ''));
      if (!b) return 'none';
      const on = b.getAttribute('aria-pressed') === 'true' || /^spark$/.test((b.innerText || '').trim());
      if (on && turnOff) b.click();
      return on ? 'on' : 'off';
    }"""
    APPROVE_RE = re.compile(r"(Phê duyệt|Luôn phê duyệt|Approve|Always approve)", re.I)

    async def _agent_off(self, page):
        """Tắt "Tác nhân Flow" (Flow Agent). Khi bật, câu lệnh đi vào khung chat của tác nhân và Flow hỏi
        "Bạn có muốn tôi bắt đầu tạo … tín dụng không? Phê duyệt / Từ chối" → tools đứng. Tools tạo trực tiếp nên luôn tắt."""
        for _ in range(6):
            try:
                st = await page.evaluate(self.JS_AGENT, True)
            except Exception:
                return
            if st not in ("on", "panel"):
                return
            L.info("Flow: %s → tắt để tạo trực tiếp", "đang mở bảng Tác nhân Flow" if st == "panel" else "đang bật Tác nhân Flow")
            await asyncio.sleep(0.8)
        L.warning("Flow: không tắt được Tác nhân Flow – nếu Flow hỏi phê duyệt, tools bấm \"Phê duyệt\" cho tác vụ này")

    async def _agent_approve(self, page) -> bool:
        """Tác nhân Flow hỏi "Bạn có muốn tôi bắt đầu tạo … tín dụng không?" cho chính tác vụ người dùng đã bấm chạy
        trong tools → bấm "Phê duyệt" (chỉ lần này; KHÔNG bấm "Luôn phê duyệt trong dự án")."""
        try:
            loc = page.locator("button", has_text=re.compile(r"^\s*(check\s*)?(Phê duyệt|Approve)\s*$", re.I))
            for i in range(await loc.count()):
                b = loc.nth(i)
                if await b.is_visible():
                    await safe_click(page, b)
                    await asyncio.sleep(1.0)
                    return True
        except Exception:
            pass
        return False

    async def _agent_asking(self, page) -> bool:
        try:
            loc = page.locator("button", has_text=self.APPROVE_RE)
            n = await loc.count()
            for i in range(n):
                if await loc.nth(i).is_visible():
                    return True
        except Exception:
            pass
        return False

    RIGHTS_RE = re.compile(r"(Quyền sử dụng|quyền cần thiết|necessary rights|rights to use|Use rights|permission to use)", re.I)

    async def _rights_dialog(self, page, allowed: bool) -> bool:
        """Hộp "Quyền sử dụng video/hình ảnh này" của Google khi tải tệp lên Flow.
        Người dùng đã xác nhận trong tools (Cài đặt lưu 'flow_rights_ok') → bấm "Tôi đồng ý, không hiện lại".
        Chưa xác nhận → không tự bấm, báo lỗi rõ để người dùng xác nhận trong tools. Trả về True nếu đã xử lý hộp."""
        dlg = page.locator("mat-dialog-container, [role=dialog], [role=alertdialog]").filter(has_text=self.RIGHTS_RE)
        try:
            if not await dlg.count() or not await dlg.first.is_visible():
                return False
        except Exception:
            return False
        if not allowed:
            raise JobError("bad_input", "Flow yêu cầu xác nhận quyền sử dụng tệp tải lên – bấm Bắt đầu lại trong tools "
                                        "và chọn \"Tôi đồng ý\" ở hộp xác nhận quyền sử dụng")
        for txt in ("Tôi đồng ý, không hiện lại", "I agree, don't show again", "I agree, don’t show again",
                    "Tôi đồng ý", "I agree", "Agree"):
            b = dlg.first.locator("button", has_text=txt)
            if await b.count() and await b.first.is_visible():
                await safe_click(page, b.first)
                L.info("Flow: đã xác nhận quyền sử dụng tệp tải lên (%s)", txt)
                await asyncio.sleep(0.8)
                return True
        raise JobError("ui_changed", "không thấy nút đồng ý trong hộp quyền sử dụng của Flow")

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
        for _ in range(480 if Path(path).suffix.lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v") else 120):
            # chờ tải lên xong (ảnh tối đa ~60 giây, video ~4 phút)
            await asyncio.sleep(0.5)
            await self._rights_dialog(page, self.rights_ok)
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
                await self._rights_dialog(page, self.rights_ok)
                if (await self._chips(page))["n"] > before:
                    break
                add = page.locator(".cdk-overlay-pane button.detail-add-to-prompt-btn, "
                                   ".cdk-overlay-pane button[class*='add-to-prompt']")
                if await add.count() and await add.first.is_visible():
                    await safe_click(page, add.first)
                await asyncio.sleep(0.5)
        if (await self._chips(page))["n"] <= before:
            try:   # ghi lại tình trạng hộp chọn để chẩn đoán lần sau
                diag = await page.evaluate("""() => ({panes: [...document.querySelectorAll('.cdk-overlay-pane')].map(p =>
                    (p.innerText || '').replace(/\\s+/g, ' ').slice(0, 200)),
                    items: [...document.querySelectorAll('button.asset-item')].map(b => (b.innerText || '').replace(/\\s+/g, ' ').slice(0, 60)).slice(0, 8),
                    chips: document.querySelectorAll('flow-ingredient-bar button').length})""")
                L.warning("Flow: không gắn được ảnh %s (tìm thấy trong hộp chọn: %s) · chẩn đoán: %s",
                          name, "có" if item is not None else "không", diag)
            except Exception:
                pass
            await self._close_overlays(page)
            raise JobError("ui_changed", "không thêm được ảnh vào câu lệnh của Flow")
        is_vid = Path(path).suffix.lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v")
        for _ in range(360 if is_vid else 60):    # chờ ảnh (video: lâu hơn, tối đa ~3 phút) trong ô xử lý xong
            await self._rights_dialog(page, self.rights_ok)
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
                    raise JobError("ui_changed", "không thấy ô khung hình đầu/cuối (kiểm tra chế độ Ảnh → Video)")
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
        self.rights_ok = bool(params.get("flow_rights_ok"))
        self.terms_ok = bool(params.get("flow_terms_ok"))
        if job.get("mode") == "lipsync":
            return await self._lipsync(page, job, refs, params, want, on_progress, on_user, timeout_s, dest_dir, base_name)
        if kind == "video" and params.get("keyframe") and refs and job.get("mode") in ("t2v", "compose"):
            return await self._keyframe(page, job, refs, params, want, on_progress, on_user, timeout_s, dest_dir, base_name)
        await self.ensure_project(page, on_user)
        exts: list[str] = []
        if job.get("mode") == "extend":      # "cảnh đầu || kéo dài 1 || kéo dài 2": tạo video rồi Kéo dài ngay trong Flow
            parts = split_extend(job["prompt"])
            if len(parts) < 2:
                raise JobError("bad_input", "Kéo dài: ghi dạng  cảnh đầu || đoạn kéo dài  (ít nhất 1 đoạn sau dấu ||)")
            exts = parts[1:]
            job = dict(job, mode="compose" if refs else "t2v", prompt=parts[0])
            want = 1
            outer_progress = on_progress
            on_progress = lambda p: outer_progress(max(1, int(p * 0.4)))
        await self._agent_off(page)
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
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Delete")
        await page.keyboard.insert_text(job["prompt"])
        await human.pause(0.5, 1.0)
        if kind == "video" and params.get("voices"):
            await self._add_voices(page, list(params["voices"]))
        await self._agent_off(page)              # chắc chắn tạo trực tiếp, không qua khung chat Tác nhân Flow
        seen_keys = await page.evaluate(JS_KEYS)
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
        want_state = "video" if kind == "video" else "image"
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(1.2)           # kiểm tra dày hơn: có kết quả là tải ngay
            if await self._signed_out(page):
                raise JobError("not_logged_in", "phiên Google đã hết, cần đăng nhập lại")
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            if not seen_any and await self._agent_approve(page):
                L.info("Flow: Tác nhân Flow hỏi phê duyệt chi phí cho tác vụ người dùng đã bấm chạy → đã bấm \"Phê duyệt\" (1 lần)")
            st = await page.evaluate(JS_STATE, seen_keys)
            tiles = st["tiles"]
            pend = [t for t in tiles if t["state"] in ("pending", "loading")]
            ok = [t for t in tiles if t["state"] == want_state]
            wrong = [t for t in tiles if t["state"] in ("image", "video") and t["state"] != want_state]
            bad = [t for t in tiles if t["state"] == "other"]
            if pend or ok or bad:
                seen_any = True
            pcts = [t["pct"] for t in pend if t["pct"] is not None]
            if pcts:
                on_progress(max(5, min(95, int(sum(pcts) / len(pcts)))))
            if seen_any and not pend:
                if ok:
                    done_tiles = ok
                    break
                if bad:
                    msg = " / ".join(t["text"] for t in bad)
                    raise JobError(self._classify(msg), msg[:300])
                if wrong:
                    raise JobError("unknown", f"Flow trả về {wrong[0]['state']} thay vì {want_state} "
                                              "(kiểm tra chế độ / model trên Flow)")
            if not seen_any and time.monotonic() - start > 30:
                msg = st.get("snack") or ""
                if msg:
                    raise JobError(self._classify(msg), msg[:300])
                if time.monotonic() - start > 60:
                    raise JobError("unknown", "Flow không bắt đầu tạo (không có ô kết quả mới)")
        else:
            raise JobError("timeout")
        if not done_tiles:
            raise JobError("timeout")

        dest_dir.mkdir(parents=True, exist_ok=True)
        if exts:
            secs = int(params.get("extend_secs") or 4)
            return [await self._extend(page, done_tiles[0], exts, secs, outer_progress, on_user, timeout_s,
                                       dest_dir / f"{base_name}_1")]
        saved: list[Path] = []
        for n, t in enumerate(done_tiles[:max(1, want)], 1):
            out = dest_dir / f"{base_name}_{n}"
            fast = await self._fast_original(page, t, out, kind, params.get("quality"))
            if fast:
                saved.append(fast)
                continue
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
                src = t.get("vsrc") if kind == "video" else t.get("src")   # video: không bao giờ lưu ảnh xem trước
                if src:
                    saved.append(await self.download(page, src, out))
                else:
                    raise JobError("download", str(e))
        return saved

    # -------------------------------------------------- Tạo kịch bản: ảnh khung đầu → video, giọng nói
    async def _keyframe(self, page, job: dict, refs: list[str], params: dict, want: int, on_progress, on_user,
                        timeout_s: int, dest_dir: Path, base_name: str) -> list[Path]:
        """Nhất quán cao: (1) tạo ẢNH khung hình đầu của cảnh bằng mô hình ảnh với đủ ảnh nhân vật / sản phẩm / bối cảnh,
        (2) dùng ảnh đó làm khung đầu để tạo video (Ảnh → Video). Ảnh khung đầu được lưu cạnh video."""
        p_img = dict(params, model=params.get("frame_model") or "Nano Banana Pro", quality="", resolutions="",
                     durations="", keyframe=False, voices=None)
        job_img = dict(job, mode="t2i", prompt=params.get("frame_prompt") or job["prompt"])
        imgs = await self.run_and_save(page, job_img, refs, p_img, 1, lambda p: on_progress(max(1, int(p * 0.3))),
                                       on_user, min(timeout_s, 360), dest_dir, f"{base_name}_khung", "image")
        if not imgs:
            raise JobError("unknown", "không tạo được ảnh khung đầu")
        from ..media.images import to_jpg
        frame = imgs[0] if imgs[0].suffix.lower() == ".jpg" else to_jpg(imgs[0])
        L.info("Flow: đã tạo ảnh khung đầu %s → tạo video từ ảnh này", frame.name)
        p_vid = dict(params, keyframe=False)
        return await self.run_and_save(page, dict(job, mode="i2v"), [str(frame)], p_vid, want,
                                       lambda p: on_progress(30 + int(p * 0.7)), on_user, timeout_s, dest_dir,
                                       base_name, "video")

    async def _open_asset_picker_at_caret(self, page):
        """Gõ '@' trong ô câu lệnh → Flow mở hộp chọn thành phần (giọng nói, nhân vật, ảnh…)."""
        await page.keyboard.type("@")
        for _ in range(20):
            await asyncio.sleep(0.25)
            if await page.locator(".cdk-overlay-pane input.search-input").count():
                return True
        return False

    async def _pick_voice_in_picker(self, page, voice: str) -> bool:
        inp = page.locator(".cdk-overlay-pane input.search-input").first
        try:
            await inp.fill(voice)
        except Exception:
            return False
        for _ in range(16):
            await asyncio.sleep(0.3)
            items = page.locator(".cdk-overlay-pane button.asset-item")
            for i in range(await items.count()):
                tx = ((await items.nth(i).inner_text()) or "").split("\n")
                if any(t.strip().lower() == voice.lower() for t in tx):
                    await items.nth(i).click()
                    await asyncio.sleep(0.6)
                    return True
        return False

    async def _add_voices(self, page, voices: list[str]):
        """Gắn giọng nói Flow (thành phần âm thanh, vd @Leda) vào cuối câu lệnh cho từng nhân vật của cảnh.
        Không gắn được thì tiếp tục tạo (giọng do Flow tự chọn) và ghi Log."""
        for v in [x for x in voices if x][:3]:
            try:
                await page.keyboard.press("End")
                await page.keyboard.insert_text(" ")
                if not await self._open_asset_picker_at_caret(page):
                    raise RuntimeError("không mở được hộp chọn khi gõ @")
                if not await self._pick_voice_in_picker(page, v):
                    raise RuntimeError("không thấy giọng trong danh sách")
                add = page.locator(".cdk-overlay-pane button.detail-add-to-prompt-btn")
                if await add.count():
                    await add.first.click()
                for _ in range(12):
                    await asyncio.sleep(0.25)
                    if await page.locator(f".mention-chip[data-mention-id='voices/{v.lower()}']").count():
                        break
                else:
                    raise RuntimeError("Flow không gắn giọng vào câu lệnh")
                L.info("Flow: đã gắn giọng %s vào câu lệnh", v)
            except Exception as e:
                L.warning("Flow: không gắn được giọng %s (%s) – Flow sẽ tự chọn giọng", v, e)
                await self._close_overlays(page)
                try:
                    await page.keyboard.press("Backspace") if await page.evaluate(
                        "() => (document.querySelector(\"div.ProseMirror[contenteditable='true']\")||{}).innerText?.trim().endsWith('@')") else None
                except Exception:
                    pass
        await self._close_overlays(page)

    async def voice_preview(self, page, voice: str, text: str, on_status=None) -> bytes:
        """Nghe thử giọng Flow với câu thoại riêng: hộp chọn › Giọng nói › điền "Hội thoại mẫu" › Phát bản nghe trước,
        lấy đoạn âm thanh Flow tạo ra. Không tạo video, không gửi câu lệnh."""
        import base64
        say = on_status or (lambda m: None)
        await self.ensure_project(page, lambda *_: None)
        await self._agent_off(page)
        box = await self._composer(page)
        await safe_click(page, box)
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Delete")
        say("Đang mở danh sách giọng của Flow…")
        if not await self._open_asset_picker_at_caret(page):
            raise JobError("ui_changed", "không mở được danh sách giọng nói của Flow")
        try:
            tab = page.locator(".cdk-overlay-pane mat-list-item:has-text('Giọng nói'), .cdk-overlay-pane mat-list-item:has-text('Voices')")
            if await tab.count():
                await tab.first.click()
                await asyncio.sleep(0.6)
            if not await self._pick_voice_in_picker(page, voice):
                raise JobError("ui_changed", f"không thấy giọng {voice} trên Flow")
            old = await page.evaluate("() => [...document.querySelectorAll('audio')].map(a => a.src)")
            ta = page.locator(".cdk-overlay-pane textarea.sample-dialogue-input").first
            await ta.fill(text[:120])
            await asyncio.sleep(0.4)
            say(f"Flow đang đọc thử giọng {voice}…")
            await page.locator(".cdk-overlay-pane button.voice-audio-card").first.click()
            src = None
            for _ in range(120):
                await asyncio.sleep(0.5)
                srcs = await page.evaluate("() => [...document.querySelectorAll('audio')].map(a => a.currentSrc || a.src)")
                new = [x for x in srcs if x and x.startswith("blob:") and x not in old]
                if new:
                    src = new[-1]
                    break
            if not src:
                raise JobError("timeout", "Flow không trả về đoạn nghe thử")
            await page.evaluate("() => document.querySelectorAll('audio').forEach(a => a.pause())")
            b64 = await page.evaluate("""async (u) => { const b = await (await fetch(u)).blob();
                return await new Promise(r => { const f = new FileReader(); f.onload = () => r(f.result.split(',')[1]);
                f.readAsDataURL(b); }); }""", src)
            return base64.b64decode(b64)
        finally:
            await self._close_overlays(page)
            try:
                await safe_click(page, await self._composer(page))
                await page.keyboard.press("ControlOrMeta+A")
                await page.keyboard.press("Delete")
            except Exception:
                pass

    # -------------------------------------------------- Copy Động Tác (trang "lipsync")
    async def _lipsync(self, page, job: dict, refs: list[str], params: dict, want: int, on_progress, on_user,
                       timeout_s: int, dest_dir: Path, base_name: str) -> list[Path]:
        """Video gốc + ảnh nhân vật → Flow · Video › Thành phần (Omni 1.2 Flash) với prompt Copy động tác cố định (chỉ chép động tác, không khẩu hình / lời nói).
        - Cắt video gốc đúng thời lượng đã chọn trên máy (Flow lấy độ dài video theo thành phần).
        - Tỷ lệ "Theo video gốc": video ngang → 16:9, dọc → 9:16.
        - Giữ nhạc / tiếng gốc: ghép lại âm thanh của đoạn video gốc vào kết quả (Veo không nhận âm thanh đầu vào)."""
        from ..media import lipsync as LS
        from .lipsync_prompt import LIPSYNC_PROMPT
        if len(refs) < 2:
            raise JobError("ref_missing", "Copy động tác cần 1 video gốc và 1 ảnh nhân vật")
        video, image = refs[0], refs[1]
        loop = asyncio.get_running_loop()
        secs = int(params.get("lipsync_secs") or 10)
        clip = await loop.run_in_executor(None, LS.prepare_clip, video, secs)
        ratio = LS.pick_ratio(params.get("ratio") or "", clip)
        p2 = dict(params, ratio=ratio, resolutions="720p", durations="", model="Omni 1.2 Flash")
        job2 = dict(job, mode="compose", prompt=LIPSYNC_PROMPT)
        try:
            saved = await self.run_and_save(page, job2, [clip, image], p2, want, on_progress, on_user, timeout_s,
                                            dest_dir, base_name, "video")
            if params.get("keep_audio", True):
                saved = [await loop.run_in_executor(None, LS.put_audio, out, clip) for out in saved]
            return saved
        finally:
            LS.cleanup(clip)

    # -------------------------------------------------- Kéo dài video
    async def _btn(self, page, label: str, timeout: float = 15):
        """Nút theo aria-label (nút cuối cùng đang hiện)."""
        loc = page.locator(f"button[aria-label='{label}']")
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            n = await loc.count()
            for i in range(n - 1, -1, -1):
                if await loc.nth(i).is_visible():
                    return loc.nth(i)
            await asyncio.sleep(0.5)
        raise JobError("ui_changed", f"không thấy nút \"{label}\" trên Flow")

    async def _extend(self, page, t: dict, exts: list[str], secs: int, on_progress, on_user, timeout_s: int,
                      out_noext: Path) -> Path:
        """Mở video vừa tạo → (+) → Kéo dài → chọn số giây → nhập prompt → Bắt đầu tạo; lặp cho từng đoạn;
        cuối cùng tải video đã kéo dài (Flow ghép thành 1 video, bản gốc 720p) rồi quay lại lưới."""
        tid = await page.evaluate(JS_TAG, t["key"]) if t.get("key") else None
        if not tid:
            raise JobError("download", "không tìm thấy video vừa tạo để kéo dài")
        tile = page.locator(f"flow-tile-container[data-va-id='{tid}']").first
        await safe_click(page, tile.locator("video, img").first)
        for _ in range(40):
            if "/edit/" in page.url:
                break
            await asyncio.sleep(0.5)
        else:
            raise JobError("ui_changed", "không mở được trình chỉnh sửa video của Flow")
        secs = max(3, min(10, int(secs)))
        try:
            for i, text in enumerate(exts, 1):
                L.info("Flow: kéo dài đoạn %d/%d (+%d giây): %s", i, len(exts), secs, text[:80])
                await safe_click(page, await self._btn(page, "Thêm đoạn video", 30))
                await human.pause(0.4, 0.7)
                item = page.locator(".cdk-overlay-pane [role=menuitem]:has-text('Kéo dài'), "
                                    ".cdk-overlay-pane button:has-text('Kéo dài')").first
                await item.wait_for(state="visible", timeout=6000)
                await safe_click(page, item)
                await self._btn(page, "Thoát khỏi chế độ mở rộng", 10)
                # thời lượng kéo dài: thanh trượt 3–10 giây trong bảng cài đặt
                await safe_click(page, await self._btn(page, "Điều kiện kích hoạt cài đặt", 10))
                await asyncio.sleep(0.6)
                got = await page.evaluate(JS_EXTEND_SECS, secs)
                if got and int(got) != secs:
                    L.warning("Flow: không đặt được thời lượng kéo dài %s giây (đang %s)", secs, got)
                box = page.locator(".ProseMirror").last
                await safe_click(page, box)
                await page.keyboard.press("ControlOrMeta+A")
                await page.keyboard.press("Delete")
                await page.keyboard.insert_text(text)
                await human.pause(0.5, 1.0)
                await safe_click(page, await self._btn(page, "Bắt đầu tạo", 10))
                await self._wait_extend(page, on_user, timeout_s,
                                        lambda p, i=i: on_progress(40 + int(55 * ((i - 1) + p / 100) / len(exts))))
            on_progress(96)
            return await self._download_open_video(page, out_noext)
        finally:
            try:
                back = page.locator("button[aria-label*='Nút quay lại' i], button[aria-label*='Back' i]").first
                if await back.count() and "/edit/" in page.url:
                    await safe_click(page, back)
                    await asyncio.sleep(1.5)
            except Exception:
                pass

    async def _wait_extend(self, page, on_user, timeout_s: int, progress):
        start = time.monotonic()
        started = False
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(1.5)
            if await self._signed_out(page):
                raise JobError("not_logged_in", "phiên Google đã hết, cần đăng nhập lại")
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            st = await page.evaluate(JS_EXTEND_STATE)
            if st["generating"]:
                started = True
                progress(min(95, int((time.monotonic() - start) / 1.2)))   # Flow không hiện %, ước theo thời gian (~2 phút)
                continue
            if st["failed"] or (st["snack"] and (BLOCK_WORDS.search(st["snack"]) or FLAG_WORDS.search(st["snack"]))):
                msg = st["failed"] or st["snack"]
                raise JobError(self._classify(msg), "Kéo dài lỗi: " + msg[:250])
            if started or not (st["composing"] or st["panel"]):   # đã qua bước soạn (kể cả xong quá nhanh) → xong
                return
            if time.monotonic() - start > 40:
                raise JobError(self._classify(st["snack"] or ""), st["snack"] or "Flow không bắt đầu kéo dài video")
        raise JobError("timeout")

    async def _download_open_video(self, page, out_noext: Path) -> Path:
        await safe_click(page, await self._btn(page, "Tải nội dung nghe nhìn xuống", 15))
        await human.pause(0.5, 0.8)
        items = page.locator(".cdk-overlay-pane").last.locator("[role=menuitem], button")
        n = await items.count()
        texts = [((await items.nth(i).inner_text()) or "").lower() for i in range(n)]
        idx = next((i for i, tx in enumerate(texts) if "gốc" in tx or "original" in tx), None)
        if idx is None:
            idx = next((i for i, tx in enumerate(texts) if "gif" not in tx and "270p" not in tx), 0)
        async with page.expect_download(timeout=300_000) as dinfo:
            await safe_click(page, items.nth(idx))
        d = await dinfo.value
        suffix = (Path(d.suggested_filename or "").suffix or ".mp4").lower()
        out = out_noext.with_suffix(suffix)
        k = 1
        while out.exists():
            out = out_noext.with_name(f"{out_noext.name}_{k}").with_suffix(suffix)
            k += 1
        await d.save_as(str(out))
        return out

    async def _fast_original(self, page, t: dict, out_noext: Path, kind: str, quality: str | None) -> Path | None:
        """Video bản gốc (720p / không chọn chất lượng): tải thẳng file video đang phát trong ô kết quả
        (chính là bản gốc), bỏ qua mở menu ⋮ › Tải xuống – nhanh hơn vài giây mỗi video. Lỗi → về cách cũ."""
        q = (quality or "").strip().lower()
        src = t.get("vsrc") or ""
        if kind != "video" or q not in ("", "720p", "gốc", "original") or not src.startswith(("https://", "http://", "blob:")):
            return None
        try:
            out = await self.download(page, src, out_noext)
            head = out.read_bytes()[:12]
            if out.stat().st_size < 50_000 or head[4:8] != b"ftyp":      # không phải mp4 hoàn chỉnh
                out.unlink(missing_ok=True)
                return None
            L.info("Flow: đã tải thẳng video bản gốc (%.1f MB)", out.stat().st_size / 1048576)
            return out
        except Exception as e:
            L.info("Flow: tải thẳng không được (%s) → tải qua menu", str(e).splitlines()[0][:120])
            return None

    async def _download_tile(self, page, t: dict, out_noext: Path, kind: str, quality: str | None = None) -> Path:
        async def tile_now():
            tid = await page.evaluate(JS_TAG, t["key"]) if t.get("key") else None
            if not tid:
                raise JobError("download", "không tìm thấy ô kết quả trên Flow")
            return page.locator(f"flow-tile-container[data-va-id='{tid}']").first

        tile = await tile_now()
        try:
            await tile.hover(timeout=8000)
        except Exception:
            pass
        await human.pause(0.4, 0.7)
        tile = await tile_now()          # Flow có thể vừa vẽ lại khi rê chuột
        more = tile.locator("button[aria-label*='Tuỳ chọn khác' i], button[aria-label*='Tùy chọn khác' i], "
                            "button[aria-label*='More' i], button:has-text('more_vert')")
        if await more.count():
            await safe_click(page, more.first)
        else:                            # không có nút ⋮: mở menu chuột phải của ô
            media = tile.locator("video, img").first
            await media.click(button="right", timeout=8000)
        await human.pause(0.4, 0.7)
        dl = page.locator(".cdk-overlay-pane [role=menuitem]:has-text('download')").last
        await dl.wait_for(state="attached", timeout=6000)
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
        upscaled = q in ("2k", "4k", "1080p") and idx is not None and texts[idx].strip().lower().startswith(q)
        # chờ Flow nâng độ phân giải có giới hạn: ảnh 2K / 4K 3 phút, video 1080p 6 phút, video 4K 15 phút.
        # Quá hạn (Flow không trả bản nâng cấp) → tải bản gốc ngay, không để tác vụ đứng im tới 20 phút
        wait_ms = (180_000 if kind != "video" else (360_000 if q == "1080p" else 900_000)) if upscaled else 300_000
        try:
            async with page.expect_download(timeout=wait_ms) as dinfo:
                await safe_click(page, items.nth(idx))
            d = await dinfo.value
        except Exception as e:
            if not upscaled or "imeout" not in type(e).__name__ + str(e):
                raise
            L.warning("Flow: chờ bản %s quá %d giây – tải bản gốc thay thế", quality, wait_ms // 1000)
            try:
                await page.keyboard.press("Escape")
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return await self._download_tile(page, t, out_noext, kind, None)
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
