"""Đọc cookie người dùng dán vào (thay cho việc mở Chrome để đăng nhập).

Nhận 2 dạng:
  * JSON xuất từ tiện ích Cookie-Editor / EditThisCookie (mảng object có name, value, domain…) – khuyên dùng.
  * Chuỗi header "Cookie": "SID=...; HSID=...; __Secure-1PSID=..." (lấy ở DevTools › Network) – không có tên miền,
    nên gán vào tên miền mặc định của nền tảng.
Kết quả là danh sách cookie theo định dạng Playwright `BrowserContext.add_cookies`.
"""
from __future__ import annotations

import json

# tên miền gắn cho cookie dạng chuỗi header (không mang tên miền) + tên miền dùng để xóa phiên cũ trước khi nạp
PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "flow": (".google.com",),
    "gvids": (".google.com",),
    "gpics": (".google.com",),
    "gemini": (".google.com",),           # tài khoản Gemini riêng cho AI Agent (cookie lấy ở gemini.google.com)
    "gpt": (".chatgpt.com",),
    "grok": (".grok.com",),
    "muse": (".muse.ai",),
}
# trang chủ dùng cho cookie __Host- (bắt buộc gắn với một host cụ thể)
PLATFORM_HOSTS: dict[str, str] = {
    "flow": "https://flow.google.com/",
    "gvids": "https://vids.google.com/",
    "gpics": "https://photos.google.com/",
    "gemini": "https://gemini.google.com/",
    "gpt": "https://chatgpt.com/",
    "grok": "https://grok.com/",
    "muse": "https://muse.ai/",
}
# cookie phiên bắt buộc phải có (đuôi tên miền, tên cookie) – trùng với LOGIN_COOKIES của adapter
REQUIRED: dict[str, tuple[tuple[str, str], ...]] = {
    "flow": (("google.com", "__Secure-1PSID"), ("google.com", "SID")),
    "gvids": (("google.com", "__Secure-1PSID"), ("google.com", "SID")),
    "gpics": (("google.com", "__Secure-1PSID"), ("google.com", "SID")),
    "gemini": (("google.com", "__Secure-1PSID"), ("google.com", "SID")),
    "gpt":(("chatgpt.com", "__Secure-next-auth.session-token"),),
    "grok": (("grok.com", "sso"),),
}

_SAMESITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict"}
MAX_COOKIES = 3000


class CookieError(ValueError):
    pass


def default_domain(platform: str) -> str:
    return PLATFORM_DOMAINS.get(platform, (".google.com",))[0]


def parse(text: str, platform: str) -> tuple[list[dict], list[str]]:
    """Trả về (cookie cho Playwright, cảnh báo). Lỗi định dạng → CookieError (thông điệp tiếng Việt)."""
    text = (text or "").strip()
    if not text:
        raise CookieError("Chưa dán cookie.")
    if text[0] in "[{":
        cookies, warns = _parse_json(text, platform)
    else:
        cookies, warns = _parse_header(text, platform)
    if not has_session(cookies, platform):
        need = " hoặc ".join(n for _, n in REQUIRED.get(platform, ()))
        if need:
            warns.append(f"Không thấy cookie phiên đăng nhập ({need}) – có thể đã xuất nhầm trang hoặc chưa đăng nhập.")
    return cookies, warns


def has_session(cookies: list[dict], platform: str) -> bool:
    req = REQUIRED.get(platform)
    if not req:
        return True
    for c in cookies:
        dom = (c.get("domain") or c.get("url") or "").lower()
        for suffix, name in req:
            if suffix in dom and (c["name"] == name or c["name"].startswith(name + ".")):
                return True
    return False


def session_expiry(cookies: list[dict], platform: str) -> float | None:
    """Hạn (giây epoch) của cookie phiên đăng nhập: lấy hạn SỚM NHẤT trong các cookie phiên bắt buộc có hạn.
    None khi không xác định được (cookie phiên là cookie phiên làm việc, hoặc nền tảng chưa khai báo cookie phiên).
    Đây là hạn ghi trên cookie – nền tảng vẫn có thể thu hồi phiên sớm hơn."""
    req = REQUIRED.get(platform)
    if not req:
        return None
    found: list[float] = []
    for c in cookies:
        dom = (c.get("domain") or c.get("url") or "").lower()
        exp = c.get("expires")
        if not isinstance(exp, (int, float)) or exp <= 0:
            continue
        for suffix, name in req:
            if suffix in dom and (c.get("name") == name or str(c.get("name", "")).startswith(name + ".")):
                found.append(float(exp))
    return min(found) if found else None


def describe_expiry(expires: float | None, now: float | None = None) -> tuple[str, str]:
    """→ (chữ hiển thị, trạng thái 'ok' | 'soon' | 'expired' | 'unknown'). 'soon' = còn dưới 7 ngày."""
    import time as _t
    if not expires:
        return "Không rõ", "unknown"
    now = _t.time() if now is None else now
    left = expires - now
    date = _t.strftime("%d/%m/%Y %H:%M", _t.localtime(expires))
    if left <= 0:
        return f"Đã hết hạn ({date})", "expired"
    days = int(left // 86400)
    if days >= 1:
        return f"Còn {days} ngày (đến {date})", "soon" if days < 7 else "ok"
    hours = max(1, int(left // 3600))
    return f"Còn {hours} giờ (đến {date})", "soon"


def _parse_json(text: str, platform: str) -> tuple[list[dict], list[str]]:
    # Nhận NHIỀU lần xuất dán nối tiếp nhau ("[...]\n[...]"): vd. cookie xuất ở flow.google.com rồi ở gemini.google.com
    # của cùng tài khoản Google. Cookie trùng (tên + tên miền + đường dẫn) lấy bản dán sau.
    try:
        docs = _json_docs(text)
    except json.JSONDecodeError as e:
        raise CookieError(f"JSON không hợp lệ (dòng {e.lineno}, cột {e.colno}).") from e
    data: list = []
    for d in docs:
        if isinstance(d, dict):
            d = d.get("cookies", [d])
        if not isinstance(d, list):
            raise CookieError("JSON phải là một mảng cookie.")
        data.extend(d)
    if not data:
        raise CookieError("JSON phải là một mảng cookie.")
    merged = len(docs) > 1
    if len(data) > MAX_COOKIES:
        raise CookieError(f"Quá nhiều cookie (>{MAX_COOKIES}).")
    out: list[dict] = []
    for i, raw in enumerate(data):
        if not isinstance(raw, dict):
            raise CookieError(f"Phần tử #{i + 1} không phải object.")
        name, value = raw.get("name"), raw.get("value")
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise CookieError(f"Phần tử #{i + 1} thiếu name/value.")
        domain = raw.get("domain") or default_domain(platform)
        if not isinstance(domain, str):
            raise CookieError(f"Cookie {name}: domain không hợp lệ.")
        ck: dict = {"name": name, "value": value,
                    "secure": bool(raw.get("secure", True)), "httpOnly": bool(raw.get("httpOnly", False))}
        if raw.get("hostOnly") is True or name.startswith("__Host-"):
            ck["url"] = f"https://{domain.lstrip('.')}/"          # Playwright: cookie chỉ của 1 host → dùng url
        else:
            ck["domain"] = domain
            path = raw.get("path")
            ck["path"] = path if isinstance(path, str) and path.startswith("/") else "/"
        exp = raw.get("expirationDate", raw.get("expires"))
        if not raw.get("session") and isinstance(exp, (int, float)) and not isinstance(exp, bool) and exp > 0:
            ck["expires"] = float(exp)
        ss = raw.get("sameSite")
        if isinstance(ss, str) and ss.lower() in _SAMESITE:
            ck["sameSite"] = _SAMESITE[ss.lower()]
        if ck.get("sameSite") == "None":
            ck["secure"] = True
        out.append(ck)
    if merged:
        last: dict[tuple, dict] = {}
        for ck in out:
            last[(ck["name"], ck.get("domain") or ck.get("url"), ck.get("path"))] = ck
        out = list(last.values())
    return out, []


def _json_docs(text: str) -> list:
    """Các khối JSON đứng nối tiếp nhau trong chuỗi (cách nhau bằng khoảng trắng / dấu phẩy)."""
    dec, i, docs = json.JSONDecoder(), 0, []
    while True:
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text):
            return docs
        obj, i = dec.raw_decode(text, i)
        docs.append(obj)


def _parse_header(text: str, platform: str) -> tuple[list[dict], list[str]]:
    if text.lower().startswith("cookie:"):
        text = text[7:]
    dom = default_domain(platform)
    host = PLATFORM_HOSTS.get(platform, "https://flow.google.com/")
    out: list[dict] = []
    warns: list[str] = []
    seen: set[str] = set()
    for part in text.replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            warns.append(f"Bỏ qua mục không có '=': {part[:30]}")
            continue
        name, value = (s.strip() for s in part.split("=", 1))
        if not name or any(ch in name for ch in " \t,"):
            warns.append(f"Bỏ qua tên cookie không hợp lệ: {name[:30]}")
            continue
        if name in seen:
            continue
        seen.add(name)
        ck: dict = {"name": name, "value": value, "secure": True, "httpOnly": False}
        if name.startswith("__Host-"):
            ck["url"] = host
        else:
            ck["domain"], ck["path"] = dom, "/"
        out.append(ck)
    if not out:
        raise CookieError("Không đọc được cookie nào.")
    warns.append(f"Chuỗi cookie không có tên miền nên đã gán vào {dom}. Nếu vẫn báo chưa đăng nhập, "
                 "hãy dán JSON xuất bằng tiện ích Cookie-Editor.")
    return out, warns
