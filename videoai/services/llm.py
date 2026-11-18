"""Sửa / viết prompt bằng LLM qua API chính thức, dùng key của người dùng (Gemini hoặc OpenAI)."""
from __future__ import annotations

import json
import urllib.request

from ..core.db import Database

SYSTEM_FIX = ("Bạn là trợ lý viết prompt cho AI tạo ảnh/video. Viết lại prompt sau rõ ràng, cụ thể về chủ thể, "
              "bối cảnh, ánh sáng, góc máy, chuyển động; giữ ý gốc; bằng tiếng Anh; một đoạn; không giải thích.")
SYSTEM_WRITE = ("Bạn là biên kịch. Từ ý tưởng sau, viết {n} prompt tạo video nối tiếp nhau thành một câu chuyện, "
                "mỗi prompt một dòng, tiếng Anh, giữ nhân vật nhất quán. Chỉ trả về các dòng prompt.")

try:
    import keyring  # Windows Credential Manager
except Exception:  # pragma: no cover
    keyring = None


def get_key(db: Database, provider: str) -> str:
    if keyring:
        try:
            k = keyring.get_password("VideoAI-MrHuynh", provider)
            if k:
                return k
        except Exception:
            pass
    return db.get_setting(f"llm_key_{provider}", "") or ""


def set_key(db: Database, provider: str, key: str) -> None:
    if keyring:
        try:
            keyring.set_password("VideoAI-MrHuynh", provider, key)
            db.set_setting(f"llm_key_{provider}", "")
            return
        except Exception:
            pass
    db.set_setting(f"llm_key_{provider}", key)


def _post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def complete(db: Database, system: str, user: str) -> str:
    provider = db.get_setting("llm_provider", "gemini")
    model = db.get_setting("llm_model", "") or ("gemini-2.5-flash" if provider == "gemini" else "gpt-4o-mini")
    key = get_key(db, provider)
    if not key:
        raise RuntimeError("Chưa nhập API key cho AI viết prompt (Cài Đặt › AI viết prompt).")
    if provider == "gemini":
        data = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": [{"text": user}]}]},
            {"x-goog-api-key": key},
        )
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    data = _post(
        "https://api.openai.com/v1/chat/completions",
        {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        {"Authorization": f"Bearer {key}"},
    )
    return data["choices"][0]["message"]["content"].strip()


def fix_prompts(db: Database, prompts: list[str]) -> list[str]:
    return [complete(db, SYSTEM_FIX, p) for p in prompts]


def write_story(db: Database, idea: str, n: int) -> list[str]:
    out = complete(db, SYSTEM_WRITE.format(n=n), idea)
    return [l.strip(" -•\t0123456789.") for l in out.splitlines() if l.strip()][:n]
