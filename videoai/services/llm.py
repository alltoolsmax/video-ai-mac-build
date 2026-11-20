"""AI Agent: sửa / viết prompt bằng TÀI KHOẢN ĐÃ ĐĂNG NHẬP trong tools (ChatGPT / Gemini qua tài khoản Google của
Flow / Grok / Muse) – không cần API key (adapters/chat.py)."""
from __future__ import annotations

import re

from ..core.db import Database

SYSTEM_FIX = ("Bạn là trợ lý viết prompt cho AI tạo ảnh/video. Viết lại prompt sau rõ ràng, cụ thể về chủ thể, "
              "bối cảnh, ánh sáng, góc máy, chuyển động; giữ ý gốc; bằng tiếng Anh; một đoạn; không giải thích.")
SYSTEM_WRITE = ("Bạn là biên kịch. Từ ý tưởng sau, viết {n} prompt tạo video nối tiếp nhau thành một câu chuyện, "
                "mỗi prompt một dòng, tiếng Anh, giữ nhân vật nhất quán. Chỉ trả về các dòng prompt.")

CHAT_PLATFORMS = ("gpt", "flow", "grok", "muse")


def agent_accounts(db: Database) -> list[dict]:
    """Tài khoản dùng được cho AI Agent (đã đăng nhập, đang bật), theo thứ tự ưu tiên ChatGPT › Gemini › Grok › Muse."""
    accs = [a for a in db.accounts() if a["platform"] in CHAT_PLATFORMS and a["enabled"]
            and a["status"] in ("ok", "unknown")]
    order = {p: i for i, p in enumerate(CHAT_PLATFORMS)}
    return sorted(accs, key=lambda a: (a["status"] != "ok", order[a["platform"]]))


def pick_account(db: Database) -> dict | None:
    want = db.get_setting("ai_account", "") or ""
    accs = agent_accounts(db)
    for a in accs:
        if a["id"] == want:
            return a
    return accs[0] if accs else None


def complete(db: Database, system: str, user: str, engine=None, on_status=None) -> str:
    """Gửi yêu cầu vào khung chat của tài khoản đã đăng nhập (không cần API key)."""
    if engine is None:
        raise RuntimeError("AI Agent cần bộ chạy trình duyệt.")
    acc = pick_account(db)
    if acc is None:
        raise RuntimeError("Chưa có tài khoản nào đăng nhập ChatGPT, Google (Flow), Grok hoặc Muse để AI Agent dùng. "
                           "Thêm và đăng nhập ở Cài đặt › Tài khoản.")
    try:
        return engine.ask_ai(acc, system, user, on_status=on_status).result(timeout=300)
    except Exception as e:
        from ..core.errors import JobError
        if isinstance(e, JobError):
            raise RuntimeError(e.detail or e.friendly) from e
        raise


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
