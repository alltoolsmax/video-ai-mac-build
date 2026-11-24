"""AI Agent qua API chính thức (v2.1.6): Gemini API (Google AI Studio) và OpenAI API (Chat GPT) bằng API key của
người dùng. Có API key → AI Agent gọi API trước (nhanh, không mở trình duyệt); API lỗi / hết lượt → tự chuyển sang
API kia, rồi sang các tài khoản Chat GPT đã đăng nhập như cũ.

- Gemini: key tạo miễn phí ở https://aistudio.google.com/apikey – dự án chưa bật thanh toán vẫn dùng được các model
  Flash / Flash-Lite trong giới hạn miễn phí (số lượt / phút, / ngày thấp).
- OpenAI: cần nạp tiền trước (trả trước) – tài khoản chưa nạp thường báo lỗi 429 "insufficient_quota".
Key lưu trong cơ sở dữ liệu của tools trên máy người dùng, chỉ gửi tới máy chủ Google / OpenAI."""
from __future__ import annotations

import base64
import json
import mimetypes
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..core import log

L = log.get("api_llm")

GEMINI_DEFAULT = "gemini-flash-latest"
OPENAI_DEFAULT = "gpt-5-mini"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
OPENAI_URL = "https://api.openai.com/v1"
PROVIDERS = ("gemini", "openai")
LABEL = {"gemini": "Gemini API", "openai": "Chat GPT API"}
KEY_PAGE = {"gemini": "https://aistudio.google.com/apikey", "openai": "https://platform.openai.com/api-keys"}
KEY = "ai_api"                    # settings: {"gemini": {"key", "model", "on"}, "openai": {...}}
BAD_SECS = {"quota": 900, "auth": 3600, "net": 60}

_lock = threading.Lock()
_bad: dict[str, float] = {}


class ApiError(RuntimeError):
    def __init__(self, provider: str, kind: str, msg: str):
        super().__init__(f"{LABEL[provider]}: {msg}")
        self.provider, self.kind = provider, kind


def config(db) -> dict:
    c = db.get_setting(KEY, {}) or {}
    out = {}
    for p in PROVIDERS:
        v = c.get(p) or {}
        out[p] = {"key": (v.get("key") or "").strip(),
                  "model": (v.get("model") or "").strip() or (GEMINI_DEFAULT if p == "gemini" else OPENAI_DEFAULT),
                  "on": v.get("on", True)}
    return out


def save(db, provider: str, key: str, model: str, on: bool = True) -> None:
    c = db.get_setting(KEY, {}) or {}
    c[provider] = {"key": key.strip(), "model": model.strip(), "on": bool(on)}
    db.set_setting(KEY, c)


def active(db) -> list[str]:
    """API có key và đang bật, theo thứ tự thử (API vừa lỗi xếp sau)."""
    c = config(db)
    ps = [p for p in PROVIDERS if c[p]["key"] and c[p]["on"]]
    now = time.monotonic()
    with _lock:
        return sorted(ps, key=lambda p: _bad.get(p, 0) > now)


def mark_bad(provider: str, kind: str):
    with _lock:
        _bad[provider] = time.monotonic() + BAD_SECS.get(kind, 60)


def mark_ok(provider: str):
    with _lock:
        _bad.pop(provider, None)


def is_bad(provider: str) -> bool:
    with _lock:
        return _bad.get(provider, 0) > time.monotonic()


# ------------------------------------------------------------------ HTTP
def _post(url: str, headers: dict, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url: str, headers: dict, timeout: int = 30) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _classify(provider: str, e: Exception) -> ApiError:
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        try:
            msg = (json.loads(body).get("error") or {}).get("message") or body
        except Exception:
            msg = body or str(e)
        msg = " ".join(str(msg).split())[:220]
        if e.code in (401, 403) or "API key not valid" in msg or "invalid_api_key" in body:
            return ApiError(provider, "auth", f"API key không đúng hoặc chưa được phép ({e.code}). {msg}")
        if e.code == 429:
            if "insufficient_quota" in body:
                return ApiError(provider, "quota", "tài khoản OpenAI chưa nạp tiền / hết tiền (insufficient_quota).")
            return ApiError(provider, "quota", f"hết lượt miễn phí hoặc gửi quá nhanh (429). {msg}")
        if e.code == 404:
            return ApiError(provider, "auth", f"không có model này ({e.code}). {msg}")
        return ApiError(provider, "net", f"lỗi {e.code}. {msg}")
    return ApiError(provider, "net", f"không kết nối được ({type(e).__name__}: {str(e)[:160]})")


def _images(files: list[str] | None) -> list[tuple[str, str]]:
    out = []
    for f in files or []:
        p = Path(f)
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        if not mime.startswith("image/"):
            continue
        out.append((mime, base64.b64encode(p.read_bytes()).decode()))
    return out


RULE_API = "Chỉ trả về đúng kết quả được yêu cầu, không giải thích, không hỏi lại."
RULE_API_JSON = "Chỉ trả về MỘT đối tượng JSON hợp lệ, không giải thích, không khối code. Lời thoại dùng ngoặc kép cong “…”."


def _gemini(cfg: dict, system: str, turns: list[tuple[str, str]], imgs, want_json: bool, timeout: int) -> str:
    contents = []
    for i, (role, text) in enumerate(turns):
        parts = [{"text": text}]
        if i == 0:
            parts += [{"inline_data": {"mime_type": m, "data": d}} for m, d in imgs]
        contents.append({"role": "user" if role == "user" else "model", "parts": parts})
    body = {"system_instruction": {"parts": [{"text": system + "\n\n" + (RULE_API_JSON if want_json else RULE_API)}]},
            "contents": contents}
    if want_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    r = _post(f"{GEMINI_URL}/models/{cfg['model']}:generateContent", {"x-goog-api-key": cfg["key"]}, body, timeout)
    cands = r.get("candidates") or []
    if not cands:
        why = (r.get("promptFeedback") or {}).get("blockReason") or "không có câu trả lời"
        raise ApiError("gemini", "net", f"Gemini không trả lời ({why}).")
    text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []) if not p.get("thought"))
    return text.strip()


def _openai(cfg: dict, system: str, turns: list[tuple[str, str]], imgs, want_json: bool, timeout: int) -> str:
    msgs = [{"role": "system", "content": system + "\n\n" + (RULE_API_JSON if want_json else RULE_API)}]
    for i, (role, text) in enumerate(turns):
        if i == 0 and imgs:
            content = [{"type": "text", "text": text}] + [
                {"type": "image_url", "image_url": {"url": f"data:{m};base64,{d}"}} for m, d in imgs]
        else:
            content = text
        msgs.append({"role": role, "content": content})
    body = {"model": cfg["model"], "messages": msgs}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    r = _post(f"{OPENAI_URL}/chat/completions", {"Authorization": f"Bearer {cfg['key']}"}, body, timeout)
    ch = r.get("choices") or []
    if not ch:
        raise ApiError("openai", "net", "OpenAI không trả lời.")
    return ((ch[0].get("message") or {}).get("content") or "").strip()


CALL = {"gemini": _gemini, "openai": _openai}


def ask(db, provider: str, system: str, user: str, files: list[str] | None = None, timeout_s: int = 240,
        check=None, want_json: bool = False, on_status=None) -> str:
    """Gửi 1 yêu cầu qua API. Sai định dạng (check báo ValueError) → nhắc AI sửa tối đa 2 lần trong cùng hội thoại.
    Lỗi → ApiError (kind: auth / quota / net / format)."""
    cfg = config(db)[provider]
    if not cfg["key"]:
        raise ApiError(provider, "auth", "chưa nhập API key.")
    if on_status:
        on_status(f"AI Agent ({LABEL[provider]}) đang phân tích…")
    imgs = _images(files)
    turns = [("user", user)]
    for k in range(3):
        try:
            ans = CALL[provider](cfg, system, turns, imgs, want_json, timeout_s)
        except ApiError:
            raise
        except Exception as e:
            raise _classify(provider, e) from e
        if not ans:
            raise ApiError(provider, "net", "câu trả lời trống.")
        if check is None:
            return ans
        try:
            check(ans)
            return ans
        except ValueError as e:
            if k == 2:
                raise ApiError(provider, "format", f"trả kết quả chưa đúng: {e}") from e
            turns += [("assistant", ans),
                      ("user", f"Câu trả lời vừa rồi chưa đúng yêu cầu: {e}. Hãy gửi lại ĐẦY ĐỦ kết quả theo đúng "
                               f"định dạng đã quy định (không bớt phần nào).")]
    raise ApiError(provider, "format", "trả kết quả chưa đúng.")


def models(provider: str, key: str) -> list[str]:
    """Danh sách model tạo chữ của key (để kiểm tra key và chọn model)."""
    try:
        if provider == "gemini":
            r = _get(f"{GEMINI_URL}/models?pageSize=200", {"x-goog-api-key": key.strip()})
            return sorted(m["name"].split("/", 1)[-1] for m in r.get("models", [])
                          if "generateContent" in (m.get("supportedGenerationMethods") or [])
                          and "gemini" in m.get("name", ""))
        r = _get(f"{OPENAI_URL}/models", {"Authorization": f"Bearer {key.strip()}"})
        return sorted(m["id"] for m in r.get("data", []) if m.get("id", "").startswith(("gpt-", "o")))
    except ApiError:
        raise
    except Exception as e:
        raise _classify(provider, e) from e
