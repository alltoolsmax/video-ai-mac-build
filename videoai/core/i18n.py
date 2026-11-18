"""Đa ngôn ngữ đơn giản: chuỗi gốc tiếng Việt, file languages/<code>.json ánh xạ sang ngôn ngữ khác."""
from __future__ import annotations

import json

from .paths import package_dir

_lang = "vi"
_table: dict[str, str] = {}

LANGUAGES = {"vi": "Tiếng Việt", "en": "English"}


def set_language(code: str) -> None:
    global _lang, _table
    _lang = code if code in LANGUAGES else "vi"
    _table = {}
    if _lang != "vi":
        f = package_dir() / "languages" / f"{_lang}.json"
        if f.exists():
            _table = json.loads(f.read_text(encoding="utf-8"))


def tr(text: str) -> str:
    return _table.get(text, text)


def current() -> str:
    return _lang
