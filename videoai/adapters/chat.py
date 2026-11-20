"""AI Agent bằng TÀI KHOẢN ĐÃ ĐĂNG NHẬP (không cần API key): gửi yêu cầu vào khung chat của nền tảng
(ChatGPT, Gemini – dùng chính tài khoản Google của Flow, Grok, Muse) trong trình duyệt ẩn của tài khoản đó,
rồi đọc câu trả lời.

Cách đọc câu trả lời không phụ thuộc giao diện từng trang (giao diện đổi thường xuyên):
- Cuối tin nhắn có một mã yêu cầu ngẫu nhiên (vd "#REQ-7f3a9c") → mọi chữ SAU mã này trên trang là câu trả lời.
- Yêu cầu AI đặt kết quả giữa hai mốc [[OUT]] … [[END]] → lấy đúng phần giữa hai mốc, xong khi thấy [[END]]
  và chữ đã đứng yên. Không có mốc thì lấy phần chữ sau mã yêu cầu khi đã đứng yên một lúc.
Xác minh (captcha / Cloudflare) hay chưa đăng nhập: báo người dùng tự xử lý, không lách.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time

from ..core import log
from ..core.errors import JobError

L = log.get("ai-agent")

OUT, END = "[[OUT]]", "[[END]]"

SITES = {
    # nền tảng tài khoản: (tên hiển thị, địa chỉ chat, ô nhập, nút gửi, nút dừng (đang trả lời))
    "gpt": ("ChatGPT", "https://chatgpt.com/?temporary-chat=true",
            ["#prompt-textarea", "div.ProseMirror[contenteditable='true']", "textarea"],
            ["button[data-testid='send-button']", "button[aria-label*='Send' i]", "button[aria-label*='Gửi']"],
            ["button[data-testid='stop-button']", "button[aria-label*='Stop' i]"]),
    "flow": ("Gemini", "https://gemini.google.com/app",
             ["rich-textarea div[contenteditable='true']", "div.ql-editor[contenteditable='true']",
              "div[contenteditable='true'][role='textbox']"],
             ["button.send-button", "button[aria-label*='Send' i]", "button[aria-label*='Gửi']"],
             ["button[aria-label*='Stop' i]", "button[aria-label*='Dừng']", "button.stop",
              ".markdown[aria-busy='true']"]),
    "grok": ("Grok", "https://grok.com/",
             ["div[contenteditable='true']", "textarea"],
             ["button[aria-label='Send']", "button[type='submit']"],
             ["button[aria-label*='Stop' i]"]),
    "muse": ("Muse", "https://muse.ai/",
             ["textarea[placeholder='Message']", "textarea", "div[contenteditable='true']"],
             ["button[aria-label*='Send' i]", "button[type='submit']"],
             ["button[aria-label*='Stop' i]"]),
}
ORDER = ["gpt", "flow", "grok", "muse"]          # thứ tự ưu tiên khi tự chọn tài khoản
LABEL = {k: v[0] for k, v in SITES.items()}
# bật "trò chuyện tạm thời" trước khi gửi (không lưu vào lịch sử chat của người dùng) – nếu trang có nút này
TEMP_CHAT = {"flow": ["button[aria-label='Bật cuộc trò chuyện tạm thời']", "button[aria-label*='Temporary chat' i]"]}
# Gemini hiện chữ dần (span.pending); trang chạy ẩn có thể chậm vẽ → ép hiện để đọc đủ chữ
CSS_REVEAL = ".pending{visibility:visible!important;opacity:1!important;display:inline!important}"

BLOCK_RE = re.compile(r"(verify you are human|xác minh bạn là người|just a moment|captcha|unusual activity)", re.I)
LOGIN_RE = re.compile(r"\b(log in|sign in|đăng nhập)\b", re.I)


def wrap(system: str, user: str, nonce: str) -> str:
    """Tin nhắn gửi vào chat: hướng dẫn + nội dung + quy ước mốc + mã yêu cầu ở CUỐI."""
    return (f"{system.strip()}\n\n{user.strip()}\n\n"
            f"Quy định trả lời: chỉ ghi kết quả, đặt giữa hai mốc {OUT} và {END} (mỗi mốc một dòng riêng), "
            f"không giải thích thêm, không dùng khối code.\n#REQ-{nonce}")


def extract(text: str, nonce: str) -> tuple[str, bool]:
    """(câu trả lời, đã xong?) từ toàn bộ chữ trên trang."""
    k = text.rfind(f"#REQ-{nonce}")
    if k < 0:                       # tin nhắn bị thu gọn (không thấy mã): lấy mốc [[OUT]] cuối không thuộc phần hướng dẫn
        k = max((m.start() for m in re.finditer(re.escape(OUT), text) if not text[m.end():m.end() + 4].strip().startswith("và")),
                default=-1)
        if k < 0:
            return "", False
        after = text[k:]
    else:
        after = text[k + len(nonce) + 5:]
    a = after.find(OUT)
    if a >= 0:
        body = after[a + len(OUT):]
        b = body.find(END)
        if b >= 0:
            return body[:b].strip(), True
        return body.strip(), False
    return after.strip(), False


JS_TEXT = "() => (document.querySelector('main') || document.body).innerText"


async def _first(page, sels: list[str], timeout_ms: int = 1500):
    for s in sels:
        loc = page.locator(s).first
        try:
            await loc.wait_for(state="visible", timeout=timeout_ms)
            return loc
        except Exception:
            continue
    return None


async def _busy(page, sels: list[str]) -> bool:
    for s in sels:
        try:
            if await page.locator(s).first.is_visible():
                return True
        except Exception:
            pass
    return False


async def ask(page, platform: str, system: str, user: str, timeout_s: int = 240, on_status=None, url: str | None = None) -> str:
    name, url0, inputs, sends, stops = SITES[platform]
    url = url or url0
    say = on_status or (lambda m: None)
    nonce = secrets.token_hex(3)
    if not page.url.startswith(url.split("?")[0]):
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    # ô nhập (chờ trang chat sẵn sàng)
    box = None
    t0 = time.time()
    while time.time() - t0 < 40 and box is None:
        box = await _first(page, inputs, 1500)
        if box is None:
            try:
                body = await page.evaluate("() => document.body.innerText.slice(0, 3000)")
            except Exception:
                body = ""
            if BLOCK_RE.search(body):
                raise JobError("needs_user", f"{name} yêu cầu xác minh – mở trình duyệt của tài khoản để xác minh rồi thử lại.")
    if box is None:
        raise JobError("not_logged_in", f"Không thấy ô chat của {name} – tài khoản có thể chưa đăng nhập {name}.")
    for sel in TEMP_CHAT.get(platform, []):
        try:
            b = page.locator(sel).first
            if await b.is_visible():
                await b.click()
                await asyncio.sleep(1.0)
                box = await _first(page, inputs, 3000) or box
                break
        except Exception:
            pass
    try:
        await page.add_style_tag(content=CSS_REVEAL)
    except Exception:
        pass
    say(f"Đang gửi yêu cầu cho {name}…")
    msg = wrap(system, user, nonce)
    await box.click()
    for i, line in enumerate(msg.split("\n")):
        if i:
            await page.keyboard.press("Shift+Enter")
        if line:
            await page.keyboard.insert_text(line)
    await asyncio.sleep(0.6)
    sent = False
    for s in sends:
        b = page.locator(s).first
        try:
            if await b.is_visible() and await b.is_enabled():
                await b.click()
                sent = True
                break
        except Exception:
            continue
    if not sent:
        await page.keyboard.press("Enter")
    say(f"{name} đang trả lời…")
    last, stable_since, t0 = None, time.time(), time.time()
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(1.2)
        try:
            text = await page.evaluate(JS_TEXT)
        except Exception:
            continue
        ans, done = extract(text, nonce)
        if ans != last:
            last, stable_since = ans, time.time()
        busy = await _busy(page, stops)
        quiet = time.time() - stable_since
        if done and ((not busy and quiet >= 1.5) or quiet >= 5):
            return ans
        if ans and not busy and quiet >= 10:               # AI không đặt mốc: lấy phần chữ đã đứng yên
            return ans
    if last:
        return last
    raise JobError("timeout", f"{name} không trả lời kịp – thử lại hoặc chọn tài khoản khác ở Cài đặt › AI Agent.")
