"""Theme: đọc tokens.json → QSS; bộ icon nét (vẽ bằng SVG, tô màu khi dùng)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

TOKENS = json.loads((Path(__file__).with_name("tokens.json")).read_text(encoding="utf-8"))
C = TOKENS["color"]
G = TOKENS["gradient"]

# icon 24x24, nét 2px (tự vẽ, phong cách đường nét đơn giản)
ICONS = {
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
    "video": '<rect x="2" y="5" width="15" height="14" rx="2"/><path d="M17 10l5-3v10l-5-3z"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M10 9l5 3-5 3z"/>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
    "clapper": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4"/>',
    "sparkle": '<path d="M12 3l2.5 5.5L20 11l-5.5 2.5L12 19l-2.5-5.5L4 11l5.5-2.5z"/>',
    "stars": '<path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "palette": '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="10" r="1.3"/><circle cx="12" cy="7.5" r="1.3"/><circle cx="16" cy="10" r="1.3"/><path d="M12 21a3 3 0 010-6h2"/>',
    "bot": '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01"/>',
    "library": '<rect x="3" y="5" width="14" height="14" rx="2"/><path d="M7 3h12a2 2 0 012 2v12"/><circle cx="8" cy="10" r="1.5"/><path d="M17 16l-4-4-7 7"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 010 10h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 000 10h3"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5M4 19h16"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "check2": '<path d="M5 12l5 5L20 7"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0M16 4.5a3.5 3.5 0 010 7M18 14a5 5 0 014 6"/>',
    "nodes": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M6 8.5v7M8.5 18h7M8 7.5l8 8.5"/>',
    "link": '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
    "zoom": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5M11 8v6M8 11h6"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.1 15.9M14.5 14.5L20 20M8.1 8.1L12 12"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "play": '<path d="M7 4l12 8-12 8z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "alert": '<path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17.5h.01"/>',
    "user_ok": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0"/><path d="M17 11l2 2 4-4"/>',
    "sliders": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "upload": '<path d="M12 15V3M7 8l5-5 5 5M4 15v4a2 2 0 002 2h12a2 2 0 002-2v-4"/>',
    "folder": '<path d="M3 7h6l2 2h10v10H3z"/>',
    "eye": '<circle cx="12" cy="12" r="3"/><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
    "retry": '<path d="M3 12a9 9 0 1015-6.7L21 8M21 3v5h-5"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "wand": '<path d="M15 4V2M15 10V8M11 6h2M17 6h2M4 20L14 10"/><path d="M19 13l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "chev_down": '<path d="M6 9l6 6 6-6"/>',
    "chev_right": '<path d="M9 6l6 6-6 6"/>',
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h8V3M8 21v-7h8v7"/>',
    "login": '<path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3"/>',
}


@lru_cache(maxsize=512)
def icon_pixmap(name: str, color: str = "#ffffff", size: int = 18) -> QPixmap:
    body = ICONS.get(name, ICONS["sparkle"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#ffffff", size: int = 18) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


def gradient(rect, stops: list[str], horizontal: bool = True) -> QLinearGradient:
    g = QLinearGradient(rect.topLeft(), rect.topRight() if horizontal else rect.bottomRight())
    n = len(stops)
    for i, s in enumerate(stops):
        g.setColorAt(i / max(1, n - 1), QColor(s))
    return g


def qss() -> str:
    c = C
    ga = G["primary"]
    gs = G["start"]
    return f"""
* {{ font-family: "Inter", "Segoe UI", sans-serif; font-size: 13px; color: {c['text']}; }}
QMainWindow, QWidget#root {{ background: {c['bg']}; }}
QWidget#sidebar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #0b1340, stop:1 {c['sidebar']});
                   border-right: 1px solid {c['border']}; }}
QWidget#statusbar {{ background: #050820; border-top: 1px solid {c['border']}; }}
QLabel#muted, QLabel[muted="true"] {{ color: {c['text-muted']}; }}
QLabel#faint {{ color: {c['text-faint']}; font-size: 11px; }}
QLabel#h1 {{ font-size: 18px; font-weight: 700; }}
QLabel#h2 {{ font-size: 14px; font-weight: 600; }}
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px; }}
QFrame#card2 {{ background: {c['surface-2']}; border: 1px solid {c['border']}; border-radius: 11px; }}
QLabel#fieldLabel {{ color: {c['text-muted']}; font-size: 11.5px; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit {{
  background: {c['input-bg']}; border: 1px solid {c['border-input']}; border-radius: 9px;
  padding: 6px 10px; min-height: 20px; selection-background-color: {c['accent-strong']}; }}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: {c['accent']}; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {c['accent']}; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {c['text-faint']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {c['surface-2']}; border: 1px solid {c['border']};
  selection-background-color: {c['accent-strong']}; outline: 0; padding: 4px; }}
QSpinBox, QDoubleSpinBox {{ padding-left: 10px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid #7f8bc4; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #7f8bc4; }}
QPlainTextEdit, QTextEdit, QListWidget, QTreeWidget {{ background: {c['input-bg']}; border: 1px solid {c['border-input']};
  border-radius: 12px; padding: 6px; }}
QListWidget::item {{ padding: 6px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {c['accent-strong']}; }}

QPushButton {{ background: {c['surface']}; border: 1px solid {c['border-input']}; border-radius: 10px;
  padding: 8px 14px; font-weight: 600; color: {c['text']}; }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['surface-2']}; }}
QPushButton:focus {{ border: 2px solid {c['accent']}; }}
QPushButton:disabled {{ color: {c['text-faint']}; border-color: {c['border']}; }}
QPushButton[kind="primary"] {{ border: none; color: white;
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {ga[0]}, stop:0.55 {ga[1]}, stop:1 {ga[2]}); }}
QPushButton[kind="primary"]:hover {{ border: 1px solid {c['accent']}; }}
QPushButton[kind="start"] {{ border: none; color: white; padding: 10px;
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {gs[0]}, stop:1 {gs[1]}); }}
QPushButton[kind="pause"] {{ background: {c['warning-bg']}; border: 1px solid #5a4416; color: {c['warning']}; padding: 10px; }}
QPushButton[kind="stop"] {{ background: {c['danger-bg']}; border: 1px solid #62202f; color: {c['danger']}; padding: 10px; }}
QPushButton[kind="chip"] {{ background: {c['surface-2']}; border: 1px solid {c['border']}; border-radius: 8px;
  padding: 4px 10px; font-weight: 500; color: #b9c3ee; }}
QPushButton[kind="chip"]:checked {{ color: white; border: none;
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0e7490, stop:1 #6d28d9); }}
QPushButton[kind="seg"] {{ background: {c['surface-2']}; border: 1px solid #2a3d8f; border-radius: 9px;
  padding: 6px 8px; font-weight: 600; color: #b9c3ee; }}
QPushButton[kind="seg"]:hover {{ border-color: {c['accent']}; }}
QPushButton[kind="seg"]:checked {{ color: white; border: 1px solid #67e8f9;
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0e7490, stop:1 #6d28d9); }}
QPushButton[kind="icon"] {{ background: {c['surface-2']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 4px; }}

QCheckBox {{ spacing: 8px; color: #c7cdea; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 2px solid #5b51c9; background: transparent; }}
QCheckBox::indicator:checked {{ background: {c['accent-2']}; border-color: {c['accent']}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {c['text-muted']}; padding: 8px 14px; border: none;
  border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QTabBar::tab:hover {{ color: {c['text']}; }}

QTableView::indicator, QListWidget::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 2px solid #5b51c9; background: #0b1030; }}
QTableView::indicator:checked, QListWidget::indicator:checked {{ background: {c['accent-2']}; border-color: {c['accent']}; }}
QTableView {{ background: {c['surface']}; border: none; gridline-color: transparent;
  selection-background-color: #1a2a6e; alternate-background-color: #0f174a; }}
QTableView::item {{ border-bottom: 1px solid #1a2660; padding: 4px; }}
QHeaderView::section {{ background: #0b1238; color: {c['text-faint']}; border: none; border-bottom: 1px solid {c['border']};
  padding: 8px; font-size: 11px; font-weight: 600; text-transform: uppercase; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a3d8f; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a3d8f; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QToolTip {{ background: {c['surface-2']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
QMenu {{ background: {c['surface-2']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {c['accent-strong']}; }}
QSlider::groove:horizontal {{ height: 6px; background: {c['surface-2']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px; background: {c['accent']}; }}
QSlider::sub-page:horizontal {{ background: {c['accent-2']}; border-radius: 3px; }}
QDialog {{ background: {c['bg']}; }}
QGraphicsView {{ background: {c['bg']}; border: 1px solid {c['border']}; border-radius: 12px; }}
"""
