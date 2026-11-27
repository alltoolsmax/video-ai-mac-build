"""Mã hóa cookie tài khoản lưu trong app.db.

Khóa Fernet (AES-128 + HMAC) được cất trong kho mật khẩu của hệ điều hành qua `keyring`
(Windows Credential Manager / macOS Keychain). Không dùng được kho mật khẩu (hoặc đặt VIDEOAI_HOME – chế độ di động /
kiểm thử) thì khóa nằm trong tệp `cookie.key` cạnh app.db. Mất khóa → cookie đã lưu không đọc lại được (phải dán lại),
phiên đăng nhập trong hồ sơ trình duyệt vẫn còn.
"""
from __future__ import annotations

import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from .paths import APP_SLUG, data_dir

_SERVICE = APP_SLUG
_ENTRY = "cookie-key"
_lock = threading.Lock()
_keys: dict[str, bytes] = {}          # theo thư mục dữ liệu (VIDEOAI_HOME có thể đổi giữa các lần kiểm thử)


def _file_key() -> bytes:
    f = data_dir() / "cookie.key"
    if f.exists():
        k = f.read_bytes().strip()
        if k:
            return k
    k = Fernet.generate_key()
    f.write_bytes(k)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return k


def _load_key() -> bytes:
    if os.environ.get("VIDEOAI_HOME"):
        return _file_key()
    try:
        import keyring
        k = keyring.get_password(_SERVICE, _ENTRY)
        if not k:
            k = Fernet.generate_key().decode()
            keyring.set_password(_SERVICE, _ENTRY, k)
            if keyring.get_password(_SERVICE, _ENTRY) != k:
                raise RuntimeError("kho mật khẩu không lưu được khóa")
        return k.encode()
    except Exception:
        return _file_key()


def _fernet() -> Fernet:
    slot = os.environ.get("VIDEOAI_HOME") or "keyring"
    with _lock:
        if slot not in _keys:
            _keys[slot] = _load_key()
        return Fernet(_keys[slot])


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """'' nếu không giải mã được (khóa đã đổi / dữ liệu hỏng)."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
