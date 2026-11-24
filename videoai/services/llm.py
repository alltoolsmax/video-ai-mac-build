"""AI Agent: sửa / viết prompt bằng API key Gemini / Chat GPT (services/api_llm.py, v2.1.6 – thử trước nếu có)
hoặc TÀI KHOẢN CHAT GPT ĐÃ ĐĂNG NHẬP trong tools – không cần API key (adapters/chat.py).
v2.1.0: chỉ dùng Chat GPT (bỏ Gemini: chậm, hay lỗi, dùng chung tài khoản Google với Flow nên dễ bị Google chặn).

Tự chọn tài khoản, người dùng không cần chọn:
- luân phiên lần lượt giữa các tài khoản Chat GPT (yêu cầu 1 → gpt1, 2 → gpt2, …, quay vòng);
- một tài khoản lỗi (không gửi được, hết lượt, không trả kết quả) → tự gửi lại bằng tài khoản kế tiếp,
  tài khoản lỗi tạm bỏ qua 10 phút."""
from __future__ import annotations

import re
import threading
import time

from ..core import log
from ..core.db import Database

L = log.get("llm")

SYSTEM_FIX = ("Bạn là trợ lý viết prompt cho AI tạo ảnh/video. Viết lại prompt sau rõ ràng, cụ thể về chủ thể, "
              "bối cảnh, ánh sáng, góc máy, chuyển động; giữ ý gốc; bằng tiếng Anh; một đoạn; không giải thích.")
SYSTEM_WRITE = ("Bạn là biên kịch. Từ ý tưởng sau, viết {n} prompt tạo video nối tiếp nhau thành một câu chuyện, "
                "mỗi prompt một dòng, tiếng Anh, giữ nhân vật nhất quán. Chỉ trả về các dòng prompt.")

CHAT_PLATFORMS = ("gpt",)                 # chỉ Chat GPT
NO_ACCOUNT = ("Chưa có API key hay tài khoản Chat GPT nào cho AI Agent. Nhập API key Gemini / Chat GPT ở "
              "Cài đặt › AI Agent, hoặc thêm và đăng nhập tài khoản Chat GPT ở Cài đặt › Tài khoản.")
BAD_SECS = 600
MAX_TRIES = 4

_lock = threading.Lock()
_busy: dict[str, int] = {}                # tài khoản đang trả lời bao nhiêu yêu cầu
_bad: dict[str, float] = {}               # tài khoản lỗi → bỏ qua tới thời điểm này
_next: dict[str, int] = {}                # vị trí luân phiên tiếp theo theo nền tảng


def agent_accounts(db: Database) -> list[dict]:
    """Tài khoản dùng được cho AI Agent (đang bật, đã đăng nhập / chưa kiểm tra)."""
    accs = [a for a in db.accounts() if a["platform"] in CHAT_PLATFORMS and a["enabled"]
            and a["status"] in ("ok", "unknown")]
    order = {p: i for i, p in enumerate(CHAT_PLATFORMS)}
    return sorted(accs, key=lambda a: (order[a["platform"]], a["created_at"] or "", a["id"]))


def busy(account_id: str) -> bool:
    with _lock:
        return _busy.get(account_id, 0) > 0


def candidates(db: Database) -> list[dict]:
    """Thứ tự thử: Chat GPT rảnh (luân phiên) › Chat GPT bận › tài khoản vừa lỗi."""
    accs = agent_accounts(db)
    now = time.monotonic()
    with _lock:
        free, taken, bad = [], [], []
        for plat in CHAT_PLATFORMS:
            lst = [a for a in accs if a["platform"] == plat]
            if not lst:
                continue
            k = _next.get(plat, 0) % len(lst)
            for a in lst[k:] + lst[:k]:
                if _bad.get(a["id"], 0) > now:
                    bad.append(a)
                elif _busy.get(a["id"], 0):
                    taken.append(a)
                else:
                    free.append(a)
        return free + taken + bad


def pick_account(db: Database) -> dict | None:
    c = candidates(db)
    return c[0] if c else None


def _take(db: Database, a: dict):
    with _lock:
        _busy[a["id"]] = _busy.get(a["id"], 0) + 1
        lst = [x["id"] for x in agent_accounts(db) if x["platform"] == a["platform"]]
        if a["id"] in lst:
            _next[a["platform"]] = lst.index(a["id"]) + 1


def _release(a: dict):
    with _lock:
        _busy[a["id"]] = max(0, _busy.get(a["id"], 0) - 1)


def ask(db: Database, engine, system: str, user: str, files: list[str] | None = None, timeout_s: int = 240,
        on_status=None, check=None, want_json: bool = False) -> str:
    """Gửi yêu cầu cho AI Agent, tự chọn tài khoản và tự chuyển tài khoản khi lỗi.
    check(ans): kiểm tra định dạng (ValueError = sai) – sai 2 lần trên 1 tài khoản → chuyển tài khoản khác."""
    from . import api_llm
    last = None
    for prov in api_llm.active(db):                      # v2.1.6: có API key → gọi API trước (nhanh, không mở trình duyệt)
        try:
            out = api_llm.ask(db, prov, system, user, files=files, timeout_s=min(timeout_s, 300), check=check,
                              want_json=want_json, on_status=on_status)
            api_llm.mark_ok(prov)
            return out
        except api_llm.ApiError as e:
            last = str(e)
            api_llm.mark_bad(prov, e.kind)
            L.warning("AI Agent: %s lỗi – chuyển tiếp: %s", api_llm.LABEL[prov], last)
            if on_status:
                on_status("AI Agent đang thử lại…")
    if engine is None:
        raise RuntimeError(last or "AI Agent cần bộ chạy trình duyệt.")
    cands = candidates(db)
    if not cands:
        raise RuntimeError(((last + "\n") if last else "") + NO_ACCOUNT)
    for n, acc in enumerate(cands[:MAX_TRIES]):
        if n and on_status:
            on_status("AI Agent đang thử lại…")
        _take(db, acc)
        try:
            if check is None and not want_json:
                fut = engine.ask_ai(acc, system, user, timeout_s=timeout_s, on_status=on_status, files=files or None)
            else:
                fut = engine.ask_ai(acc, system, user, timeout_s=timeout_s, on_status=on_status, files=files or None,
                                    check=check, want_json=want_json)
            out = fut.result(timeout=2 * timeout_s + 180)
            if not (out or "").strip():
                raise RuntimeError("AI Agent không trả lời")
            with _lock:
                _bad.pop(acc["id"], None)
            return out
        except Exception as e:
            from ..core.errors import JobError
            last = (e.detail or e.friendly) if isinstance(e, JobError) else (str(e) or type(e).__name__)
            fmt = isinstance(e, JobError) and e.code in ("ai_format", "login_open")  # tạm nghỉ ngắn
            with _lock:
                _bad[acc["id"]] = time.monotonic() + (120 if fmt else BAD_SECS)
            L.warning("AI Agent: tài khoản %s (%s) lỗi – chuyển tài khoản khác: %s", acc["label"], acc["platform"], last)
        finally:
            _release(acc)
    raise RuntimeError(last or NO_ACCOUNT)


def complete(db: Database, system: str, user: str, engine=None, on_status=None) -> str:
    """Gửi yêu cầu vào khung chat của tài khoản đã đăng nhập (không cần API key)."""
    return ask(db, engine, system, user, on_status=on_status)


def _lines(out: str) -> list[str]:
    res = []
    for l in out.splitlines():
        l = re.sub(r"^\s*(?:[-•*]|\d{1,3}[.)\]:]|(?:prompt|cảnh|scene)\s*\d+\s*[:.)-])\s*", "", l.strip(), flags=re.I)
        l = l.strip().strip('"').strip()
        if l and l not in (OUT_MARK, END_MARK):
            res.append(l)
    return res


OUT_MARK, END_MARK = "[[OUT]]", "[[END]]"

SYSTEM_FIX_MANY = ("Bạn là trợ lý viết prompt cho AI tạo ảnh/video. Viết lại TỪNG prompt bên dưới cho rõ ràng, cụ thể về "
                   "chủ thể, bối cảnh, ánh sáng, góc máy, chuyển động; giữ ý gốc; bằng tiếng Anh. Trả về đúng {n} dòng, "
                   "dòng thứ i là prompt thứ i đã viết lại, không đánh số, không giải thích.")


def fix_prompts(db: Database, prompts: list[str], engine=None, on_status=None) -> list[str]:
    out: list[str] = []
    for i in range(0, len(prompts), 25):                # gửi theo từng nhóm 25 prompt (một tin nhắn / nhóm)
        part = prompts[i:i + 25]
        body = "\n".join(f"{k + 1}. {p}" for k, p in enumerate(part))
        lines = _lines(complete(db, SYSTEM_FIX_MANY.format(n=len(part)), body, engine, on_status))
        if len(lines) != len(part):                     # AI trả sai số dòng → sửa từng prompt
            lines = [(_lines(complete(db, SYSTEM_FIX, p, engine, on_status)) or [p])[0] for p in part]
        out += lines
    return out


def write_story(db: Database, idea: str, n: int, engine=None, on_status=None) -> list[str]:
    return _lines(complete(db, SYSTEM_WRITE.format(n=n), idea, engine, on_status))[:n]
