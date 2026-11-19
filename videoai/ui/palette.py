"""Bộ màu giao diện: 2 tối + 2 sáng.

Giao diện gốc được thiết kế cho nền tối (Xanh đêm). Các bộ màu khác được tạo bằng cách biến đổi
MỌI mã màu #rrggbb của ứng dụng theo vai trò của nó (nền / viền / chữ / màu nhấn), áp dụng ở 3 chỗ:
QSS chung, setStyleSheet của từng widget và QColor("#…") khi tự vẽ. Gọi install() TRƯỚC khi tạo giao diện.
Đổi bộ màu cần khởi động lại phần mềm.
"""
from __future__ import annotations

import colorsys
import re
from functools import lru_cache

THEMES = {   # khóa: (tên hiển thị, kiểu, màu mẫu nền, màu mẫu nhấn)
    "dark_navy": ("Tối · Xanh đêm", "dark", "#070b24", "#22d3ee"),
    "dark_graphite": ("Tối · Than chì", "dark", "#141518", "#f59e0b"),
    "light_ivory": ("Sáng · Trắng ngà", "light", "#faf6ee", "#ea580c"),
    "light_ice": ("Sáng · Xanh băng", "light", "#eef5fc", "#2563eb"),
}
DEFAULT = "dark_navy"
_theme = DEFAULT
_HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_KEEP = {"#ffffff", "#000000"}       # chữ trắng trên nút màu, bóng đen: giữ nguyên


def current() -> str:
    return _theme


def is_light() -> bool:
    return THEMES[_theme][1] == "light"


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r, g, b) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(x * 255))) for x in (r, g, b))


@lru_cache(maxsize=4096)
def map_hex(h: str, theme: str | None = None) -> str:
    theme = theme or _theme
    low = h.lower()
    if len(low) == 4:
        low = "#" + "".join(c * 2 for c in low[1:])
    if theme == "dark_navy" or low in _KEEP:
        return low
    r, g, b = _rgb(low)
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    accent = ss >= 0.5 and 0.3 <= ll <= 0.8
    if theme == "dark_graphite":
        if accent:
            return low
        # nền/viền/chữ ánh xanh → xám than trung tính, ấm nhẹ
        return _hex(*colorsys.hls_to_rgb(0.1, ll * (1.03 if ll < 0.5 else 1.0), ss * 0.12))
    # ---- sáng
    tint_h, tint_s = (0.11, 0.35) if theme == "light_ivory" else (0.58, 0.45)
    if accent:
        if ll > 0.5:                           # màu nhấn sáng (dùng làm chữ trên nền tối) → đậm hơn cho nền sáng
            return _hex(*colorsys.hls_to_rgb(hh, 0.38, min(1.0, ss)))
        return _hex(*colorsys.hls_to_rgb(hh, ll * 0.92, ss))
    if ll < 0.30:                              # nền / bề mặt
        navy = 0.55 <= hh <= 0.72              # nền xanh đêm của bộ gốc → nền trung tính của bộ sáng
        if ss > 0.35 and ll > 0.08 and not navy:   # nền nhuốm màu (ô trạng thái, thẻ thống kê) → màu nhạt cùng sắc
            return _hex(*colorsys.hls_to_rgb(hh, 0.92, min(0.8, ss)))
        nl = 0.985 - ll * 0.38
        return _hex(*colorsys.hls_to_rgb(tint_h, nl, tint_s * 0.6))
    if ll < 0.55:                              # viền / nền phụ
        nl = 0.84 - (ll - 0.30) * 0.35
        navy = 0.55 <= hh <= 0.72
        return _hex(*colorsys.hls_to_rgb(tint_h if (ss < 0.5 or navy) else hh, nl, min(0.45, ss * 0.5 + 0.1)))
    # chữ sáng → chữ tối
    nl = max(0.10, min(0.45, 1.08 - ll))
    navy = 0.55 <= hh <= 0.72 and ss < 0.9
    return _hex(*colorsys.hls_to_rgb(tint_h if (ss < 0.4 or navy) else hh, nl, min(0.40, ss * 0.4 + 0.12)))


def map_css(text: str) -> str:
    if _theme == DEFAULT or not text or "#" not in text:
        return text
    return _HEX.sub(lambda m: map_hex(m.group(0)), text)


_installed = False


def install(theme: str) -> None:
    """Chọn bộ màu và vá Qt để mọi màu viết trong mã đi qua bộ biến đổi. Gọi một lần, trước khi tạo giao diện."""
    global _theme, _installed
    _theme = theme if theme in THEMES else DEFAULT
    map_hex.cache_clear()
    if _installed or _theme == DEFAULT:
        return
    _installed = True
    from PySide6 import QtGui, QtWidgets
    orig_ss = QtWidgets.QWidget.setStyleSheet

    def set_style_sheet(self, css):
        return orig_ss(self, map_css(css))
    QtWidgets.QWidget.setStyleSheet = set_style_sheet

    orig_app_ss = QtWidgets.QApplication.setStyleSheet

    def app_style_sheet(self, css):
        return orig_app_ss(self, map_css(css))
    QtWidgets.QApplication.setStyleSheet = app_style_sheet

    for cls in (QtWidgets.QLabel, QtWidgets.QAbstractButton):   # chữ có định dạng (HTML) chứa màu
        orig_txt = cls.setText

        def set_text(self, text, _o=orig_txt):
            if isinstance(text, str) and "<" in text:
                text = map_css(text)
            return _o(self, text)
        cls.setText = set_text
    orig_doc = QtGui.QTextDocument.setDefaultStyleSheet

    def doc_css(self, css):
        return orig_doc(self, map_css(css))
    QtGui.QTextDocument.setDefaultStyleSheet = doc_css

    base = QtGui.QColor

    class ThemedColor(base):
        """QColor("#…") → trả về QColor THẬT đã đổi màu (không phải lớp con, để Qt nhận đúng kiểu khi vẽ)."""
        def __new__(cls, *a):
            if a and isinstance(a[0], str) and a[0].startswith("#") and len(a[0]) in (4, 7):
                a = (map_hex(a[0]),) + a[1:]
            return base(*a)
    QtGui.QColor = ThemedColor
