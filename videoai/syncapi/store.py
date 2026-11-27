"""Kho SYNC API: API key ↔ cookie (mã hóa) và API key ↔ tài khoản Video AI. Lưu trong bảng settings của app.db."""
from __future__ import annotations

import hmac
import re
import secrets
import threading
import time

from ..core.cookies import CookieError, parse, session_expiry
from ..core.secret import decrypt, encrypt

KEYS = "sync_api_keys"            # {api_key: {"platform", "cookie_enc", "expires", "created", "updated"}}
LINKS = "sync_api_links"          # {account_id: api_key}
PREFIX = "sync-"
KEY_RE = re.compile(r"^sync-[0-9a-f]{48}$")
PLATFORMS = ("flow", "gpt", "grok", "muse", "gemini")   # nền tảng có trang tạo + Gemini (tài khoản riêng cho AI Agent)

_lock = threading.RLock()


class SyncKeyError(ValueError):
    """API key không hợp lệ / không có trong kho / không đúng nền tảng (thông điệp tiếng Việt)."""


def new_key() -> str:
    return PREFIX + secrets.token_hex(24)


def looks_like_key(text: str) -> bool:
    return bool(KEY_RE.match((text or "").strip()))


class SyncStore:
    def __init__(self, db):
        self.db = db

    # ---------- API key ↔ cookie ----------
    def _keys(self) -> dict:
        v = self.db.get_setting(KEYS, {}) or {}
        return v if isinstance(v, dict) else {}

    def entries(self, platform: str | None = None) -> list[dict]:
        """Các key đã lưu (mới nhất trước), không kèm cookie."""
        out = [{"key": k, "platform": e.get("platform"), "expires": e.get("expires"),
                "created": e.get("created"), "updated": e.get("updated")}
               for k, e in self._keys().items() if isinstance(e, dict) and (not platform or e.get("platform") == platform)]
        return sorted(out, key=lambda e: e.get("updated") or 0, reverse=True)

    def get(self, key: str) -> dict | None:
        key = (key or "").strip()
        e = self._keys().get(key)
        if not isinstance(e, dict):
            return None
        return {"key": key, "platform": e.get("platform"), "expires": e.get("expires"),
                "created": e.get("created"), "updated": e.get("updated")}

    def find(self, token: str) -> dict | None:
        """Tra key gửi qua HTTP (so sánh không lộ thời gian)."""
        token = (token or "").strip().encode()
        hit = None
        for k in self._keys():
            if hmac.compare_digest(k.encode(), token):
                hit = k
        return self.get(hit) if hit else None

    def save_cookie(self, platform: str, text: str, key: str | None = None) -> tuple[str, float | None, list[str]]:
        """Lưu cookie cho key (key=None → tạo key mới). Trả về (key, hạn cookie phiên, cảnh báo).
        Cookie sai định dạng → CookieError; key lạ / khác nền tảng → SyncKeyError."""
        if platform not in PLATFORMS:
            raise SyncKeyError("Nền tảng không hợp lệ.")
        text = (text or "").strip()
        cookies, warns = parse(text, platform)
        expires = session_expiry(cookies, platform)
        now = time.time()
        with _lock:
            keys = self._keys()
            if key:
                key = key.strip()
                cur = keys.get(key)
                if not isinstance(cur, dict):
                    raise SyncKeyError("API key này không có trong SYNC API.")
                if cur.get("platform") != platform:
                    raise SyncKeyError("API key này thuộc nền tảng khác.")
                created = cur.get("created") or now
            else:
                key, created = new_key(), now
                while key in keys:
                    key = new_key()
            keys[key] = {"platform": platform, "cookie_enc": encrypt(text), "expires": expires,
                         "created": created, "updated": now}
            self.db.set_setting(KEYS, keys)
        return key, expires, warns

    def cookie_text(self, key: str) -> str:
        """Cookie đã lưu của key ('' nếu không có / không giải mã được)."""
        e = self._keys().get((key or "").strip())
        return decrypt(e["cookie_enc"]) if isinstance(e, dict) and e.get("cookie_enc") else ""

    def cookies(self, key: str) -> tuple[list[dict], list[str], str]:
        """→ (cookie định dạng Playwright, cảnh báo, nguyên văn). Key lạ / cookie hỏng → SyncKeyError."""
        e = self.get(key)
        if not e:
            raise SyncKeyError("API key này không có trong SYNC API. Bấm «Lấy API Key» để tạo.")
        text = self.cookie_text(key)
        if not text:
            raise SyncKeyError("Không đọc lại được cookie của API key này – mở SYNC API và lưu lại cookie.")
        try:
            cks, warns = parse(text, e["platform"])
        except CookieError as err:
            raise SyncKeyError(str(err)) from err
        return cks, warns, text

    def delete(self, key: str) -> None:
        key = (key or "").strip()
        with _lock:
            keys = self._keys()
            if keys.pop((key or "").strip(), None) is not None:
                self.db.set_setting(KEYS, keys)
            links = self._links()
            drop = [a for a, k in links.items() if k == key]
            if drop:
                for a in drop:
                    links.pop(a, None)
                self.db.set_setting(LINKS, links)

    # ---------- API key ↔ tài khoản ----------
    def _links(self) -> dict:
        v = self.db.get_setting(LINKS, {}) or {}
        return v if isinstance(v, dict) else {}

    def link(self, account_id: str, key: str) -> None:
        with _lock:
            links = self._links()
            links[account_id] = key.strip()
            self.db.set_setting(LINKS, links)

    def unlink(self, account_id: str) -> None:
        with _lock:
            links = self._links()
            if links.pop(account_id, None) is not None:
                self.db.set_setting(LINKS, links)

    def key_of(self, account_id: str) -> str:
        return self._links().get(account_id) or ""

    def accounts_of(self, key: str) -> list[str]:
        key = (key or "").strip()
        return [a for a, k in self._links().items() if k == key]
