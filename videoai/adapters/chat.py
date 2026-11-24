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
ORDER = ["gpt", "flow", "grok", "muse"]          # thứ tự ưu tiên khi tự chọn tài khoản
LABEL = {k: v[0] for k, v in SITES.items()}
# bật "trò chuyện tạm thời" trước khi gửi (không lưu vào lịch sử chat của người dùng) – nếu trang có nút này
TEMP_CHAT = {"flow": ["button[aria-label='Bật cuộc trò chuyện tạm thời']", "button[aria-label*='Temporary chat' i]"]}
# Gemini hiện chữ dần (span.pending); trang chạy ẩn có thể chậm vẽ → ép hiện để đọc đủ chữ
CSS_REVEAL = ".pending{visibility:visible!important;opacity:1!important;display:inline!important}"

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
              files: list[str] | None = None, check=None, want_json: bool = False) -> str:
    """check(ans): báo ValueError nếu câu trả lời sai định dạng → nhắc AI sửa 1 lần trong cùng cuộc chat;
    vẫn sai → JobError("ai_format") để AI Agent chuyển sang tài khoản khác."""
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
                raise JobError("needs_user", "Tài khoản AI Agent cần xác minh – mở trình duyệt của tài khoản để xác minh rồi thử lại.")
    if box is None:
        raise JobError("not_logged_in", "AI Agent chưa sẵn sàng – tài khoản AI Agent có thể đã hết phiên đăng nhập (kiểm tra ở Cài đặt › Tài khoản).")
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
PASTE_SITES = ("flow",)          # Chat GPT: dán đoạn dài bị đổi thành tệp đính kèm → giữ cách gõ đang chạy tốt


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
    while time.time() - t0 < timeout_s:
        await asyncio.sleep(0.7)
        try:
            text = await page.evaluate(JS_TEXT)
        except Exception:
            continue
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
