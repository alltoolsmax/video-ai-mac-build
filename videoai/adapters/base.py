"""Adapter chung điều khiển trang web AI qua giao diện người dùng.

Mỗi nền tảng có một file selectors/<platform>.json mô tả: URL, ô nhập prompt, nút tạo,
ô tải ảnh, dấu hiệu chưa đăng nhập / cần xác minh / bị chặn / hết lượt, và vùng chứa kết quả.
Khi web đổi giao diện, chỉ cần sửa file JSON đó (Cài Đặt › Nền tảng › Mở thư mục selector).

Không gọi API nội bộ: mọi việc làm qua những gì người dùng nhìn thấy trên trang.
Kết quả được tải qua địa chỉ ảnh/video đang hiển thị trên trang, bằng phiên của chính người dùng.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable

from ..core import log
from ..core.errors import JobError
from ..core.paths import data_dir, package_dir
from ..browser import human

L = log.get("adapter")

ProgressCb = Callable[[int], None]
UserCb = Callable[[str], None]


def selectors_dir() -> Path:
    """Bản người dùng sửa (ưu tiên) nằm trong data_dir/selectors; bản mặc định trong gói."""
    d = data_dir() / "selectors"
    d.mkdir(parents=True, exist_ok=True)
    src = package_dir() / "adapters" / "selectors"
    for f in src.glob("*.json"):
        if not (d / f.name).exists():
            shutil.copy(f, d / f.name)
    return d


def load_selectors(platform: str) -> dict:
    f = selectors_dir() / f"{platform}.json"
    if not f.exists():
        f = package_dir() / "adapters" / "selectors" / "_generic.json"
    return json.loads(f.read_text(encoding="utf-8"))


class WebAdapter:
    def __init__(self, platform: str, url_override: str | None = None):
        self.platform = platform
        self.sel = load_selectors(platform)
        self.url = url_override or self.sel.get("url", "")

    # ---------- tìm phần tử ----------
    async def _first(self, page, keys, timeout=8000, visible=True):
        cands = self.sel.get(keys, []) if isinstance(keys, str) else keys
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            for s in cands:
                try:
                    loc = page.locator(s)
                    n = await loc.count()
                    for i in range(n - 1, -1, -1):  # phần tử mới nhất thường nằm cuối
                        el = loc.nth(i)
                        if not visible or await el.is_visible():
                            return el
                except Exception:
                    continue
            await asyncio.sleep(0.4)
        return None

    async def _any_visible(self, page, key) -> bool:
        for s in self.sel.get(key, []):
            try:
                loc = page.locator(s)
                if await loc.count() and await loc.first.is_visible():
                    return True
            except Exception:
                pass
        return False

    # ---------- trạng thái ----------
    async def check_login(self, page) -> str:
        await asyncio.sleep(2)
        if await self._any_visible(page, "captcha_markers"):
            return "needs_user"
        if await self._any_visible(page, "logged_out_markers"):
            return "expired"
        if await self._first(page, "prompt", timeout=6000):
            return "ok"
        return "unknown"

    async def read_credits(self, page) -> int | None:
        for s in self.sel.get("credits", []):
            try:
                loc = page.locator(s)
                if await loc.count():
                    txt = await loc.first.inner_text()
                    m = re.search(r"(\d[\d.,]*)", txt)
                    if m:
                        return int(re.sub(r"[.,]", "", m.group(1)))
            except Exception:
                pass
        return None

    async def wait_for_user(self, page, on_user: UserCb, max_minutes: int = 15):
        """Trang cần xác minh: đưa cửa sổ lên, báo người dùng, chờ đến khi trang trở lại bình thường."""
        on_user("needs_user")
        try:
            await page.bring_to_front()
        except Exception:
            pass
        deadline = time.monotonic() + max_minutes * 60
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            if not await self._any_visible(page, "captcha_markers") and \
               not await self._any_visible(page, "logged_out_markers"):
                if await self._first(page, "prompt", timeout=2000):
                    on_user("resumed")
                    return
        raise JobError("needs_user", "hết thời gian chờ người dùng xác minh")

    async def guard(self, page, on_user: UserCb):
        if await self._any_visible(page, "captcha_markers") or await self._any_visible(page, "logged_out_markers"):
            await self.wait_for_user(page, on_user)

    # ---------- tùy chọn ----------
    async def apply_options(self, page, mode: str, params: dict):
        """Áp dụng tùy chọn bằng chuỗi click khai báo trong JSON:
        "options": {"mode": {"t2v": ["button:has-text('Text to Video')"]}, "ratio": {"16:9 Ngang": [...]}}
        Thiếu khai báo thì giữ nguyên lựa chọn đang có trên trang (trang thường nhớ lần dùng trước)."""
        opts = self.sel.get("options", {})
        wanted = {"mode": mode, **{k: v for k, v in params.items() if isinstance(v, str)}}
        for name, value in wanted.items():
            steps = opts.get(name, {}).get(value)
            if not steps:
                continue
            for s in steps:
                el = await self._first(page, [s], timeout=5000)
                if el is None:
                    L.warning("[%s] không áp dụng được %s=%s (thiếu %s)", self.platform, name, value, s)
                    break
                await el.click()
                await human.pause(0.3, 0.7)

    # ---------- media trên trang ----------
    async def _media_srcs(self, page) -> list[str]:
        sel = ",".join(self.sel.get("result_media", ["img", "video"]))
        min_px = int(self.sel.get("result_min_px", 256))
        try:
            return await page.eval_on_selector_all(
                sel,
                """(els, minPx) => els.map(e => {
                    const r = e.getBoundingClientRect();
                    const w = e.naturalWidth || e.videoWidth || r.width;
                    const h = e.naturalHeight || e.videoHeight || r.height;
                    let src = e.currentSrc || e.src || '';
                    if (!src && e.tagName === 'VIDEO') { const s = e.querySelector('source'); if (s) src = s.src; }
                    return (w >= minPx || h >= minPx) ? src : '';
                }).filter(Boolean)""",
                min_px,
            )
        except Exception:
            return []

    async def _blocked(self, page) -> bool:
        return await self._any_visible(page, "blocked_markers")

    async def _quota(self, page) -> bool:
        return await self._any_visible(page, "quota_markers")

    # ---------- một lần tạo ----------
    async def run(self, page, job: dict, refs: list[str], params: dict, want: int,
                  on_progress: ProgressCb, on_user: UserCb, timeout_s: int) -> list[str]:
        await self.guard(page, on_user)
        await self.apply_options(page, job["mode"], params)

        # tải ảnh tham chiếu / khung hình
        if refs:
            fi = await self._first(page, "file_input", timeout=6000, visible=False)
            if fi is None:
                btn = await self._first(page, "attach_button", timeout=4000)
                if btn:
                    await btn.click()
                    await human.pause()
                    fi = await self._first(page, "file_input", timeout=6000, visible=False)
            if fi is None:
                raise JobError("ui_changed", "không thấy ô tải ảnh")
            await fi.set_input_files(refs)
            await human.pause(1.5, 3.0)

        before = set(await self._media_srcs(page))
        box = await self._first(page, "prompt", timeout=15000)
        if box is None:
            await self.guard(page, on_user)
            box = await self._first(page, "prompt", timeout=10000)
            if box is None:
                raise JobError("ui_changed", "không thấy ô nhập prompt")
        await human.type_into(page, box, job["prompt"])

        btn = await self._first(page, "submit", timeout=8000)
        if btn is not None:
            await btn.click()
        else:
            await page.keyboard.press("Enter")
        on_progress(5)

        # chờ kết quả mới xuất hiện
        start = time.monotonic()
        found: list[str] = []
        stable_since = None
        while time.monotonic() - start < timeout_s:
            await asyncio.sleep(3)
            if await self._blocked(page):
                raise JobError("blocked")
            if await self._quota(page):
                raise JobError("quota")
            if await self._any_visible(page, "captcha_markers"):
                await self.wait_for_user(page, on_user)
            now_srcs = [s for s in await self._media_srcs(page) if s not in before]
            new = [s for s in now_srcs if s not in found]
            found.extend(new)
            elapsed = time.monotonic() - start
            on_progress(min(95, 5 + int(90 * elapsed / max(timeout_s * 0.5, 1))))
            if len(found) >= want:
                # chờ thêm chút cho chắc các file đã hoàn chỉnh (video có thể đổi src khi xong)
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since > 4:
                    break
            elif found and new == [] and stable_since is None and elapsed > timeout_s * 0.6:
                break
        if not found:
            raise JobError("timeout")
        return found[:want] if want else found

    # ---------- tải về ----------
    async def download(self, page, src: str, dest_noext: Path) -> Path:
        dest_noext.parent.mkdir(parents=True, exist_ok=True)
        data: bytes | None = None
        ctype = ""
        if src.startswith("data:"):
            head, b64 = src.split(",", 1)
            ctype = head[5:].split(";")[0]
            data = base64.b64decode(b64)
        elif src.startswith("blob:"):
            b64, ctype = await page.evaluate(
                """async (u) => { const r = await fetch(u); const b = await r.blob();
                   const buf = new Uint8Array(await b.arrayBuffer()); let s='';
                   for (let i=0;i<buf.length;i+=32768) s += String.fromCharCode.apply(null, buf.subarray(i,i+32768));
                   return [btoa(s), b.type]; }""", src)
            data = base64.b64decode(b64)
        else:
            resp = await page.context.request.get(src, timeout=180_000)
            if not resp.ok:
                raise JobError("download", f"HTTP {resp.status}")
            data = await resp.body()
            ctype = resp.headers.get("content-type", "")
        ext = _ext_from(ctype, src, data)
        out = dest_noext.with_suffix(ext)
        k = 1
        while out.exists():
            out = dest_noext.with_name(f"{dest_noext.name}_{k}").with_suffix(ext)
            k += 1
        out.write_bytes(data)
        return out


def _ext_from(ctype: str, src: str, data: bytes) -> str:
    c = (ctype or "").lower()
    if "mp4" in c or data[4:8] == b"ftyp":
        return ".mp4"
    if "webm" in c or data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    if "png" in c or data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if "webp" in c or data[8:12] == b"WEBP":
        return ".webp"
    if "jpeg" in c or "jpg" in c or data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    m = re.search(r"\.(mp4|webm|png|jpe?g|webp)(\?|$)", src, re.I)
    return "." + m.group(1).lower() if m else ".bin"
