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
    "gpt": ("ChatGPT", "https://chatgpt.com/",
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
# "gemini": loại tài khoản RIÊNG cho AI Agent – cookie lấy ở gemini.google.com, không dùng chung với tài khoản Flow.
# Giao diện chat là một nên dùng lại các khai báo của khóa "flow" (khóa "flow" giữ lại cho mã / kiểm thử cũ).
GEMINI = "gemini"
SITES[GEMINI] = SITES["flow"]
ORDER = ["gpt", GEMINI, "flow", "grok", "muse"]  # thứ tự ưu tiên khi tự chọn tài khoản
LABEL = {k: v[0] for k, v in SITES.items()}
# bật "trò chuyện tạm thời" trước khi gửi (không lưu vào lịch sử chat của người dùng) – nếu trang có nút này
TEMP_CHAT = {"flow": ["button[aria-label='Bật cuộc trò chuyện tạm thời']", "button[aria-label*='Temporary chat' i]"]}
TEMP_CHAT[GEMINI] = TEMP_CHAT["flow"]
# Gemini hiện chữ dần (span.pending); trang chạy ẩn có thể chậm vẽ → ép hiện để đọc đủ chữ
CSS_REVEAL = ".pending{visibility:visible!important;opacity:1!important;display:inline!important}"

# v2.2.6 – chẩn đoán "chưa đăng nhập" đúng: chỉ báo hết phiên khi trang THẬT SỰ hiện nút Đăng nhập và không còn cookie
# phiên. Còn lại (bảng thông báo che, chưa vào màn hình chat, chọn workspace…) → tự khắc phục / nhờ người dùng xem cửa sổ.
SESSION_COOKIE = {"gpt": ("chatgpt.com", "__Secure-next-auth.session-token"),
                  "flow": ("google.com", "__Secure-1PSID"),
                  "grok": ("grok.com", "sso")}
SESSION_COOKIE[GEMINI] = SESSION_COOKIE["flow"]
LOGIN_BTN =["[data-testid='login-button']", "a[href*='/auth/login']", "button:has-text('Log in')",
             "button:has-text('Đăng nhập')", "a:has-text('Sign in')", "a:has-text('Đăng nhập')"]
# nút đóng các bảng thông báo / giới thiệu tính năng mới (chỉ bấm bên trong hộp thoại, không bấm đồng ý điều khoản)
DISMISS = [f"[role='dialog'] {t}:has-text('{x}')" for t in ("button", "a")
           for x in ("Maybe later", "Not now", "No thanks", "Dismiss", "Got it", "Okay, let", "Close", "Skip",
                     "Để sau", "Không phải bây giờ", "Bỏ qua", "Đã hiểu", "Đóng")] + \
          ["[role='dialog'] button[aria-label='Close' i]", "[role='dialog'] button[data-testid='close-button']",
           "[role='dialog'] button[aria-label='Đóng']"]
NEW_CHAT = {"gpt": ["a[data-testid='create-new-chat-button']", "button[data-testid='create-new-chat-button']",
                    "a[aria-label*='New chat' i]", "a[aria-label*='Đoạn chat mới' i]"],
            "flow": ["button[aria-label*='New chat' i]", "button[aria-label*='Cuộc trò chuyện mới' i]"],
            "grok": ["a[href='/']"]}
NEW_CHAT[GEMINI] = NEW_CHAT["flow"]


def _same_page(cur: str, target: str) -> bool:
    from urllib.parse import urlparse
    a, b = urlparse(cur or ""), urlparse(target or "")
    return a.netloc == b.netloc and (a.path.rstrip("/") or "/") == (b.path.rstrip("/") or "/")


async def _visible_any(page, sels: list[str]) -> bool:
    for s in sels:
        try:
            loc = page.locator(s)
            for i in range(min(await loc.count(), 4)):
                if await loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False


async def _has_session(page, platform: str) -> bool:
    dom_name = SESSION_COOKIE.get(platform)
    if not dom_name:
        return False
    dom, name = dom_name
    try:
        now_ = time.time()
        for c in await page.context.cookies():
            if c.get("expires", -1) not in (-1, None) and c["expires"] < now_:
                continue
            if c.get("domain", "").lstrip(".").endswith(dom) and \
                    (c.get("name") == name or c.get("name", "").startswith(name + ".")):
                return True
    except Exception:
        pass
    return False


async def _dismiss(page) -> bool:
    hit = False
    for s in DISMISS:
        try:
            b = page.locator(s).first
            if await b.count() and await b.is_visible():
                await b.click(timeout=2000)
                hit = True
                await asyncio.sleep(0.6)
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    return hit


async def _snapshot(page, name: str) -> str:
    """Lưu ảnh màn hình trang lúc lỗi vào thư mục log để dễ tìm nguyên nhân."""
    try:
        from ..core.paths import logs_dir
        f = logs_dir() / f"ai-agent-{time.strftime('%Y%m%d-%H%M%S')}.png"
        await page.screenshot(path=str(f), timeout=8000)
        return str(f)
    except Exception:
        return ""


BLOCK_RE = re.compile(r"(verify you are human|xác minh bạn là người|just a moment|captcha|unusual activity)", re.I)
LOGIN_RE = re.compile(r"\b(log in|sign in|đăng nhập)\b", re.I)


RULE = (f"Quy định trả lời: chỉ ghi kết quả, đặt giữa hai mốc {OUT} và {END} (mỗi mốc một dòng riêng), "
        f"không giải thích thêm, không dùng khối code, không hỏi lại, không mở canvas / tài liệu – "
        f"trả lời trực tiếp trong khung chat.")


# Kết quả JSON: bắt buộc đặt trong khối code – trang chat hiển thị chữ thường dạng markdown và làm rơi dấu "\"
# trong JSON (Gemini hay bị), còn khối code giữ nguyên từng ký tự
RULE_JSON = (f"Quy định trả lời: dòng đầu ghi {OUT}, sau đó là MỘT khối code ```json chứa JSON, dòng cuối ghi {END}. "
             f"Không giải thích thêm, không hỏi lại, không mở canvas / tài liệu – trả lời trực tiếp trong khung chat. "
             f"Lời thoại trong JSON dùng ngoặc kép cong “…”.")


def wrap(system: str, user: str, nonce: str, want_json: bool = False) -> str:
    """Tin nhắn gửi vào chat: hướng dẫn + nội dung + quy ước mốc + mã yêu cầu ở CUỐI."""
    return f"{system.strip()}\n\n{user.strip()}\n\n{RULE_JSON if want_json else RULE}\n#REQ-{nonce}"


def followup(err: str, nonce: str) -> str:
    """Câu nhắc gửi tiếp trong CÙNG cuộc chat khi kết quả sai định dạng (AI vẫn nhớ yêu cầu + ảnh)."""
    return (f"Câu trả lời vừa rồi chưa đúng yêu cầu: {err}. Hãy gửi lại ĐẦY ĐỦ kết quả vừa viết theo đúng định dạng JSON "
            f"đã quy định ở trên (không bớt phần nào).\n{RULE_JSON}\n#REQ-{nonce}")


# chữ "đang suy nghĩ / đang phân tích" của trang chat – chưa phải câu trả lời
THINK_RE = re.compile(r"^\s*(chatgpt said:|gemini said:)?\s*(thinking|thought for|reasoning|analy[sz]ing|searching|"
                      r"đang suy nghĩ|đã suy nghĩ|đang phân tích|đang tìm|hiện suy nghĩ|show thinking|"
                      r"just a sec|một chút)", re.I)


# câu từ chối có sẵn của trang chat (Gemini…): nhắc lại trong cùng cuộc chat vô ích → đổi tài khoản khác ngay
REFUSE_RE = re.compile(r"(tôi là một mô hình ngôn ngữ|tôi chỉ là một mô hình ngôn ngữ|nằm ngoài (mục đích|khả năng|phạm vi)|"
                       r"tôi không được lập trình|tôi không thể (giúp|hỗ trợ|thực hiện)|không thể giúp (bạn )?(với|về) (điều|việc) đó|"
                       r"i'?m (just )?a language model|i'?m not able to help|i can'?t help with that|"
                       r"outside (of )?my capabilities|i'?m unable to help)", re.I)


def is_refusal(ans: str) -> bool:
    return bool(ans) and not looks_json(ans) and bool(REFUSE_RE.search(ans)) and len(ans) < 600


def looks_json(ans: str) -> bool:
    a, z = ans.find("{"), ans.rfind("}")
    return a >= 0 and z > a


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


def _has_out(text: str, nonce: str) -> bool:
    """Sau tin nhắn mang mã #REQ-<nonce> đã có mốc [[OUT]] của câu trả lời chưa."""
    k = text.rfind(f"#REQ-{nonce}")
    return k >= 0 and OUT in text[k:]


JS_TEXT = "() => document.body.innerText"          # cả trang (gồm khung canvas nếu AI lỡ mở)
# Cách đọc dự phòng (không phụ thuộc cách trang hiển thị – trình duyệt ẩn có thể không "vẽ" khối code):
# chữ gốc của cả trang + nội dung các khối code cuối cùng
JS_ALT = r"""() => {
  // chữ của cả cây trang, đi vào cả shadow DOM (Gemini có model hiển thị câu trả lời trong vùng tách riêng)
  const deep = n => {
    if (n.nodeType === 3) return n.data;
    if (n.nodeType !== 1 && n.nodeType !== 11) return '';
    if (n.nodeType === 1 && /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE)$/.test(n.tagName)) return '';
    let s = n.shadowRoot ? deep(n.shadowRoot) : '';
    for (const c of n.childNodes) s += deep(c);
    if (n.nodeType === 1 && /^(DIV|P|PRE|LI|BR|SECTION|ARTICLE|MODEL-RESPONSE|MESSAGE-CONTENT)$/.test(n.tagName)) s += '\n';
    return s;
  };
  const found = [];
  const walk = root => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches('pre, code-block, code, model-response, message-content')) found.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const blocks = found.map(e => deep(e)).filter(t => t.includes('{') || t.includes('['));
  return {all: deep(document.body), blocks: blocks.slice(-6).reverse()};
}"""


# khung câu trả lời cuối cùng / khối code cuối cùng – đọc bằng locator của Playwright (xuyên được shadow DOM,
# Gemini có model mới hiển thị câu trả lời ở chỗ document.body.innerText không đọc tới)
ALT_LOCATORS = ("model-response", "message-content", "[data-message-author-role='assistant']",
                "code-block", "pre", "code")


async def _alt_answers(page, nonce: str) -> list[str]:
    out = []
    try:
        d = await page.evaluate(JS_ALT)
        ans, _ = extract(d.get("all") or "", nonce)
        if ans:
            out.append(ans)
        out += [b for b in (d.get("blocks") or []) if b.strip()]
    except Exception:
        pass
    for sel in ALT_LOCATORS:
        try:
            loc = page.locator(sel)
            n = await loc.count()
            if not n:
                continue
            t = await loc.nth(n - 1).inner_text(timeout=1500)
            if t and ("{" in t or "[" in t):
                out.append(extract(t, nonce)[0] or t)
        except Exception:
            continue
    return out


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


# nút mở chỗ đính kèm tệp (input[type=file] thường chỉ xuất hiện sau khi bấm)
ATTACH_OPEN = {
    "gpt": ["button[data-testid='composer-plus-btn']", "button[aria-label*='Add photos' i]", "button[aria-label*='Attach' i]",
            "button[aria-label*='Thêm ảnh' i]", "button[aria-label*='Đính kèm' i]"],
    "flow": ["button[aria-label='Nội dung tải lên và công cụ']", "button[aria-label*='upload' i]",
             "button[aria-label*='tải lên' i]", "button[aria-label*='tải tệp' i]"],
    "grok": ["button[aria-label*='Attach' i]", "button[aria-label*='Đính kèm' i]", "button[aria-label*='Upload' i]"],
    "muse": ["button[aria-label*='Attach' i]", "button[aria-label*='Upload' i]", "button[aria-label*='photo' i]"],
}
ATTACH_OPEN[GEMINI] = ATTACH_OPEN["flow"]
CHOOSER = ["[data-test-id='hidden-local-image-upload-button']", "[data-test-id='local-image-file-uploader-button']",
           "[role=menuitem]:has-text('Tải tệp lên')", "[role=menuitem]:has-text('Upload files')",
           "button:has-text('Tải tệp lên')", "button:has-text('Upload files')", "button:has-text('Tệp')"]


async def _file_input(page):
    loc = page.locator("input[type=file]")
    best = None
    for i in range(await loc.count()):
        acc = (await loc.nth(i).get_attribute("accept")) or ""
        if "image" in acc:
            return loc.nth(i)
        if not acc and best is None:
            best = loc.nth(i)
    return best


async def attach_files(page, platform: str, files: list[str], on_status=None):
    """Đính kèm ảnh tham chiếu vào ô chat (đúng thứ tự). Không được → báo lỗi rõ (không gửi yêu cầu thiếu ảnh)."""
    if not files:
        return
    name = SITES[platform][0]
    (on_status or (lambda m: None))(f"AI Agent đang nhận {len(files)} ảnh tham chiếu…")
    inp = await _file_input(page)
    if inp is None:
        for s in ATTACH_OPEN.get(platform, []):
            try:
                b = page.locator(s).first
                if await b.is_visible():
                    await b.click()
                    await asyncio.sleep(0.9)
                    inp = await _file_input(page)
                    if inp is not None:
                        break
            except Exception:
                continue
    done = False
    if inp is not None:
        try:
            if (await inp.get_attribute("multiple")) is not None or len(files) == 1:
                await inp.set_input_files(files)
            else:
                for f in files:
                    await inp.set_input_files(f)
                    await asyncio.sleep(1.2)
            done = True
        except Exception as e:
            L.info("%s: đính kèm qua ô tệp lỗi (%s) – thử hộp chọn tệp", name, str(e)[:120])
    if not done:
        for s in CHOOSER:
            try:
                b = page.locator(s).first
                if not await b.count():
                    continue
                async with page.expect_file_chooser(timeout=6000) as fc:
                    await b.click(force=True)
                await (await fc.value).set_files(files)
                done = True
                break
            except Exception:
                continue
    if not done:
        raise JobError("ui_changed", "AI Agent không nhận được ảnh tham chiếu – thử chọn tài khoản AI Agent khác "
                                     "(ChatGPT / Gemini) ở Cài đặt › AI Agent.")
    try:
        await page.keyboard.press("Escape")       # đóng menu tải lên (nếu còn mở)
    except Exception:
        pass
    await asyncio.sleep(2.0 + 1.5 * len(files))  # chờ ảnh tải lên xong (nút gửi còn bị khóa trong lúc tải)


async def ask(page, platform: str, system: str, user: str, timeout_s: int = 240, on_status=None, url: str | None = None,
              files: list[str] | None = None, check=None, want_json: bool = False, on_verify=None) -> str:
    """check(ans): báo ValueError nếu câu trả lời sai định dạng → nhắc AI sửa 1 lần trong cùng cuộc chat;
    vẫn sai → JobError("ai_format") để AI Agent chuyển sang tài khoản khác."""
    name, url0, inputs, sends, stops = SITES[platform]
    url = url or url0
    say = on_status or (lambda m: None)
    nonce = secrets.token_hex(3)
    if not _same_page(page.url, url):            # đang ở trang khác của cùng website (ảnh, GPTs, cài đặt…) → về khung chat
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    # ô nhập (chờ trang chat sẵn sàng; chưa thấy thì tự khắc phục từng bước trước khi kết luận)
    box = None
    t0 = time.time()
    blocked_at = None
    fixed = set()
    while time.time() - t0 < 45 and box is None:
        box = await _first(page, inputs, 1500)
        if box is not None:
            break
        el = time.time() - t0
        try:
            body = await page.evaluate("() => document.body.innerText.slice(0, 3000)")
        except Exception:
            body = ""
        if BLOCK_RE.search(body) or await _challenge_page(page):
            blocked_at = blocked_at or time.time()
            if time.time() - blocked_at < 10:        # trang kiểm tra thường tự qua sau vài giây → chờ trước
                continue
            # Vẫn hỏi "Verify you are human": tools KHÔNG tự bấm / lách kiểm tra. Hiện cửa sổ Chrome cho người dùng
            # tự tick, chờ tối đa 5 phút, xác minh xong thì tự ẩn cửa sổ và chạy tiếp.
            if on_verify is None:
                raise JobError("needs_user", "Tài khoản AI Agent cần xác minh – mở trình duyệt của tài khoản để xác minh rồi thử lại.")
            await on_verify(True)
            say(f"{name} cần xác minh: hãy tick ô xác minh trong cửa sổ Chrome vừa hiện – xong tools tự chạy tiếp")
            end = time.time() + 300
            while time.time() < end and box is None:
                await asyncio.sleep(2)
                if page.is_closed():                  # người dùng đóng cửa sổ xác minh → dừng ngay
                    raise JobError("needs_user", "Cửa sổ xác minh Chat GPT đã bị đóng (has been closed).")
                box = await _first(page, inputs, 1000)
            await on_verify(False)
            if box is None:
                raise JobError("needs_user", "Chưa xác minh trong 5 phút – AI Agent chuyển tài khoản khác / thử lại sau.")
            say("Đã xác minh – AI Agent chạy tiếp")
            break
        blocked_at = None
        # tự khắc phục khi trang chưa hiện khung chat (mỗi bước 1 lần)
        if el > 6 and "dismiss" not in fixed:
            fixed.add("dismiss")
            if await _dismiss(page):
                L.info("%s: đã đóng bảng thông báo che khung chat", name)
        elif el > 14 and "newchat" not in fixed:
            fixed.add("newchat")
            L.info("%s: chưa thấy khung chat (trang đang ở %s) → mở cuộc trò chuyện mới", name, page.url[:120])
            if not _same_page(page.url, url) or not await _click_first(page, NEW_CHAT.get(platform, [])):
                await _goto(page, url)
        elif el > 26 and "reload" not in fixed:
            fixed.add("reload")
            L.info("%s: vẫn chưa thấy khung chat → tải lại trang chat", name)
            await _goto(page, url)
            await asyncio.sleep(2)
            await _dismiss(page)
    if box is None:
        box = await _not_ready(page, platform, name, url, inputs, say, on_verify)
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
    if files:
        await attach_files(page, platform, files, say)
        box = await _first(page, inputs, 3000) or box
    say("AI Agent đang phân tích…")
    paste = platform in PASTE_SITES
    ans = await _send_read(page, box, wrap(system, user, nonce, want_json), nonce, sends, stops, timeout_s, say, bool(files),
                           want_json, paste, check)
    if check is None:
        return ans
    for k in range(2):                                     # sai định dạng → nhắc lại ngay trong cùng cuộc chat
        try:
            check(ans)
            return ans
        except ValueError as e:
            for i_, alt in enumerate(await _alt_answers(page, nonce)):   # đọc lại theo cách khác trước khi bắt AI sửa
                try:
                    check(alt)
                    L.info("%s: lấy được kết quả bằng cách đọc dự phòng", name)
                    return alt
                except ValueError as e2:
                    L.warning("%s – cách đọc dự phòng %d chưa dùng được (%s): %s", name, i_ + 1, e2,
                              " ".join(alt.split())[:300])
            L.warning("%s trả sai định dạng (%s). Câu trả lời: %s", name, e, " ".join(ans.split())[:1000] or "(trống)")
            if is_refusal(ans):
                raise JobError("ai_format", f"AI Agent ({name}) từ chối yêu cầu – chuyển sang tài khoản khác") from e
            if k:
                raise JobError("ai_format", f"AI Agent ({name}) trả kết quả chưa đúng: {e}") from e
            say(f"Kết quả chưa đúng ({e}) – yêu cầu AI sửa lại…")
            nonce = secrets.token_hex(3)
            box = await _first(page, inputs, 5000)
            if box is None:
                raise JobError("ai_format", f"AI Agent ({name}) trả kết quả chưa đúng: {e}") from e
            ans = await _send_read(page, box, followup(str(e), nonce), nonce, sends, stops, timeout_s, say, False,
                                   want_json, paste, check)
    return ans


CHALLENGE_FRAMES = ("iframe[src*='challenges.cloudflare.com']", "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']",
                    "#challenge-form", "#cf-challenge-running")


async def _challenge_page(page) -> bool:
    """Trang kiểm tra robot (Cloudflare "Just a moment… / Verify you are human"): chữ xác minh nằm trong iframe nên
    innerText của trang chính không có – nhận diện qua tiêu đề trang và khung kiểm tra."""
    try:
        if BLOCK_RE.search(await page.title()):
            return True
    except Exception:
        pass
    for sel in CHALLENGE_FRAMES:
        try:
            if await page.locator(sel).count():
                return True
        except Exception:
            pass
    return False


async def _click_first(page, sels: list[str]) -> bool:
    for s_ in sels:
        try:
            b = page.locator(s_).first
            if await b.count() and await b.is_visible():
                await b.click(timeout=3000)
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue
    return False


async def _goto(page, url: str):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    except Exception as e:
        L.info("mở lại trang chat lỗi: %s", str(e).splitlines()[0][:120])


GEMINI_NEEDS_COOKIE = ("Tài khoản Gemini chưa đăng nhập (trang chuyển sang đăng nhập Google). Cookie của tài khoản Gemini phải "
                       "lấy ở chính trang gemini.google.com: Cài Đặt › Tài khoản › chọn tài khoản Gemini › API Key › Lấy API Key › "
                       "Lấy Cookie, xuất cookie ở trang đó rồi dán và Lưu.")


async def _not_ready(page, platform: str, name: str, url: str, inputs, say, on_verify):
    """Hết thời gian mà chưa thấy khung chat: phân biệt CHƯA ĐĂNG NHẬP thật với trang chưa vào đúng giao diện."""
    shot = await _snapshot(page, name)
    try:
        title = await page.title()
    except Exception:
        title = ""
    login_btn = await _visible_any(page, LOGIN_BTN)
    on_auth = any(k in page.url for k in ("/auth", "auth.openai.com", "accounts.google.com", "/login", "/sign-in"))
    session = await _has_session(page, platform)
    L.warning("%s: không thấy khung chat – trang: %s (%s) · nút Đăng nhập: %s · cookie phiên: %s%s", name,
              page.url[:160], title[:80], "có" if login_btn else "không", "còn" if session else "không",
              f" · ảnh màn hình: {shot}" if shot else "")
    if platform in (GEMINI, "flow") and "accounts.google.com" in page.url:
        # Đo ngày 27/11/2026: cookie xuất ở flow.google.com vẫn "đã đăng nhập" cho Flow nhưng gemini.google.com chuyển
        # sang trang đăng nhập Google – Gemini cần cookie lấy ở chính gemini.google.com. Báo rõ cho AI Agent (chuyển
        # tài khoản khác); không mở cửa sổ xác minh.
        raise JobError("not_logged_in", GEMINI_NEEDS_COOKIE)
    if (login_btn or on_auth) and not session:
        raise JobError("not_logged_in", f"Tài khoản AI Agent ({name}) đã hết phiên đăng nhập – đăng nhập lại ở "
                                        "Cài đặt › Tài khoản.")
    # Đã đăng nhập nhưng trang chưa vào đúng giao diện chat (bảng thông báo, chọn workspace, trang khác…):
    # hiện cửa sổ để người dùng xem / bấm, tools tự chạy tiếp khi khung chat hiện ra.
    if on_verify is not None:
        msg = (f"{name} đã đăng nhập nhưng chưa vào đúng khung chat – xem cửa sổ Chrome vừa hiện (đóng thông báo / "
               "chọn workspace / bấm Đoạn chat mới), tools tự chạy tiếp")
        try:
            await on_verify(True, msg)
        except TypeError:
            await on_verify(True)
        say(msg)
        box = None
        end = time.time() + 180
        while time.time() < end and box is None:
            await asyncio.sleep(2)
            if page.is_closed():
                raise JobError("needs_user", "Cửa sổ Chat GPT đã bị đóng (has been closed).")
            box = await _first(page, inputs, 1000)
        await on_verify(False)
        if box is not None:
            say(f"{name} đã vào khung chat – AI Agent chạy tiếp")
            return box
    raise JobError("ui_changed", f"{name} chưa hiện khung chat (trang: {page.url[:100]}) – tài khoản vẫn đăng nhập, "
                                 "không phải lỗi đăng nhập. Mở trình duyệt của tài khoản để kiểm tra rồi thử lại.")


async def _focus_box(page, box):
    """Đặt con trỏ vào ô chat. Trang có lớp phủ (gợi ý, thông báo) che ô nhập → bấm thường bị chặn:
    đóng lớp phủ bằng Esc, bấm cưỡng bức, cuối cùng đặt tiêu điểm bằng JS."""
    try:
        await box.click(timeout=5000)
        return
    except Exception:
        pass
    try:
        await page.keyboard.press("Escape")
        await box.click(timeout=4000, force=True)
        return
    except Exception:
        pass
    await box.evaluate("e => { e.focus(); const s = window.getSelection(); if (s && e.isContentEditable) {"
                       " const r = document.createRange(); r.selectNodeContents(e); r.collapse(false);"
                       " s.removeAllRanges(); s.addRange(r); } }")


# Dán cả tin nhắn một lần như người dùng bấm Dán (Ctrl/Cmd+V). Gemini: ô chat tự định dạng markdown khi GÕ – gõ tới
# dòng "```json" thì phần chữ sau bị biến thành khối code ngay trong tin nhắn → Gemini nhận tin méo, trả câu từ chối;
# gõ từng dòng còn rất chậm. Dán thì Gemini nhận nguyên văn (như người dùng tự dán: trả đúng, nhanh).
JS_PASTE = r"""(el, text) => {
  el.focus();
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  return (el.innerText || el.value || '').length;
}"""
PASTE_SITES = ("flow", GEMINI)   # Chat GPT: dán đoạn dài bị đổi thành tệp đính kèm → giữ cách gõ đang chạy tốt


# Đưa cả tin nhắn vào ô chat MỘT lần (không gõ từng dòng). Thử lần lượt, kiểm tra ô chat đã nhận đủ chữ và không bị
# đổi thành khối code (Gemini tự định dạng markdown khi GÕ "```"):
#   1) sự kiện Dán (paste)  2) lệnh chèn chữ của trình duyệt (execCommand insertText)  3) gán thẳng chữ vào ô (innerText)
# Gemini chặn gán innerHTML (TrustedHTML) → xóa ô bằng textContent.
JS_FILL = r"""(el, [text, how]) => {
  el.focus();
  if (how === 'paste') {
    const dt = new DataTransfer(); dt.setData('text/plain', text);
    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  } else if (how === 'exec') {
    const sel = window.getSelection(); const r = document.createRange();
    r.selectNodeContents(el); r.collapse(false); sel.removeAllRanges(); sel.addRange(r);
    document.execCommand('insertText', false, text);
  } else {
    if ('value' in el && el.tagName !== 'DIV') el.value = text; else el.innerText = text;
    el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
  }
  return true;
}"""
# kiểm tra SAU một nhịp (trang có thể đổi định dạng ngay sau khi chèn chữ)
JS_FILLED = r"""el => ({n: (el.innerText || el.value || '').replace(/\s+/g, '').length,
                        code: !!(el.querySelector && el.querySelector('pre, code'))})"""
JS_CLEAR = "e => { if ('value' in e && e.tagName !== 'DIV') e.value = ''; else e.textContent = ''; " \
           "e.dispatchEvent(new InputEvent('input', {bubbles: true})); }"


async def _type_text(page, box, msg: str, paste: bool):
    await _focus_box(page, box)
    if paste:
        need = len("".join(msg.split())) * 0.9
        for how in ("paste", "exec", "set"):
            try:
                await box.evaluate(JS_FILL, [msg, how])
                await asyncio.sleep(0.35)
                r = await box.evaluate(JS_FILLED)
                if r["n"] >= need and not r["code"]:
                    if how != "paste":
                        L.info("Đưa tin nhắn vào ô chat bằng cách %s", how)
                    return
                L.info("Cách %s chưa được (%s/%d ký tự%s)", how, r["n"], int(need / 0.9), ", bị đổi thành khối code" if r["code"] else "")
                await box.evaluate(JS_CLEAR)
            except Exception as e:
                L.info("Cách %s lỗi: %s", how, str(e).splitlines()[0][:160])
                try:
                    await box.evaluate(JS_CLEAR)
                except Exception:
                    pass
        await _focus_box(page, box)
        L.warning("Không đưa được cả tin nhắn vào ô chat một lần – gõ từng dòng (chậm)")
    for i, line in enumerate(msg.split("\n")):
        if i:
            await page.keyboard.press("Shift+Enter")
        if line:
            await page.keyboard.insert_text(line)



def _ok(check, ans: str) -> bool:
    try:
        check(ans)
        return True
    except ValueError:
        return False


async def _send_read(page, box, msg: str, nonce: str, sends, stops, timeout_s: int, say, has_files: bool,
                     want_json: bool, paste: bool = False, check=None) -> str:
    """Đưa tin nhắn vào ô chat, bấm gửi, chờ AI viết xong rồi trả về phần trả lời.
    check (kết quả JSON): kết quả vừa đủ và đúng định dạng là lấy NGAY – không chờ mốc [[END]] / chờ trang đứng yên."""
    await _type_text(page, box, msg, paste)
    await asyncio.sleep(0.3)
    sent = False
    t_send = time.time()
    while not sent:
        for s in sends:
            b = page.locator(s).first
            try:
                if await b.is_visible() and await b.is_enabled():
                    await b.click()
                    sent = True
                    break
            except Exception:
                continue
        if sent or not has_files or time.time() - t_send > 90:   # có ảnh: chờ ảnh tải lên xong (nút gửi mở khóa)
            break
        await asyncio.sleep(0.8)
    if not sent:
        await page.keyboard.press("Enter")
    say("AI Agent đang viết…")
    last, stable_since, t0, t_alt = None, time.time(), time.time(), 0.0
    deep_mode, t_deep = False, 0.0
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(0.7)
        try:
            text = await page.evaluate(JS_TEXT)
        except Exception:
            continue
        # Gemini có thể vẽ câu trả lời trong shadow DOM: document.body.innerText không thấy mốc [[OUT]], và phần chữ sau
        # tin nhắn chỉ còn chữ của giao diện (chân trang, nút Gửi) → trước đây câu hỏi thường (không kèm kiểm tra định
        # dạng) nhận nhầm chữ giao diện làm câu trả lời. Không thấy mốc thì đọc chữ của cả cây trang, kể cả shadow DOM;
        # đã thấy câu trả lời ở đó thì đọc ở đó tới hết lượt (để chữ không nhảy qua lại giữa hai cách đọc).
        if not _has_out(text, nonce) and (deep_mode or time.time() - t_deep >= 1.5):
            t_deep = time.time()
            try:
                deep = (await page.evaluate(JS_ALT)).get("all") or ""
            except Exception:
                deep = ""
            if _has_out(deep, nonce):
                deep_mode, text = True, deep
            elif deep_mode:
                continue                                     # trang đang vẽ lại: giữ kết quả lượt trước
        ans, done = extract(text, nonce)
        if ans != last:
            last, stable_since = ans, time.time()
        if check is not None and ans and (done or looks_json(ans)) and _ok(check, ans):
            return ans                                       # đã đủ, đúng định dạng: lấy ngay
        busy = await _busy(page, stops)
        quiet = time.time() - stable_since
        if check is not None and quiet >= 2 and time.time() - t_alt >= 2:
            t_alt = time.time()                              # chữ trang không có JSON (Gemini ẩn khối code): đọc thẳng
            for alt in await _alt_answers(page, nonce):
                if _ok(check, alt):
                    return alt
        if done and ((not busy and quiet >= 1.5) or quiet >= 5):
            return ans
        # AI không đặt mốc [[END]]: chỉ nhận khi chữ đã đứng yên lâu, không phải dòng "đang suy nghĩ…",
        # và (khi cần JSON) đã có khối JSON – tránh đọc quá sớm lúc AI còn đang xem ảnh / suy nghĩ
        if ans and not busy and not THINK_RE.match(ans):
            if want_json and is_refusal(ans) and quiet >= 5:     # câu từ chối có sẵn: không chờ thêm
                return ans
            if (not want_json or looks_json(ans)) and quiet >= 15:
                return ans
            if quiet >= 90:
                return ans
    if last:
        return last
    raise JobError("timeout", "AI Agent không trả lời kịp – thử lại hoặc chọn tài khoản khác ở Cài đặt › AI Agent.")
