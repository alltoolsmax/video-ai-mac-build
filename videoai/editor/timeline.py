"""Timeline nhiều track: Chữ · Video (nối liền) · Nhạc · Lồng tiếng.

Kéo thân clip để di chuyển (video: đổi thứ tự), kéo mép để cắt bớt đầu/cuối, bấm thước để tua.
Phím: S = cắt tại kim, Delete = xóa, Space = phát/dừng, Ctrl+Z / Ctrl+Y = hoàn tác / làm lại.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..core.paths import data_dir
from ..media.ffmpeg import NOWIN, ffmpeg
from ..ui.theme import C
from .model import AudioItem, Clip, Project, TextItem

RULER = 24
TRACKS = [("text", "Chữ", 30), ("video", "Video", 66), ("music", "Nhạc", 34), ("voice", "Lồng tiếng", 34)]
GAP = 6
EDGE = 7
COL = {"text": "#7c3aed", "music": "#047857", "voice": "#9a3412"}


def track_rects(width: int) -> dict[str, tuple[int, int]]:
    y = RULER + 4
    out = {}
    for key, _, h in TRACKS:
        out[key] = (y, h)
        y += h + GAP
    return out


TOTAL_H = RULER + 4 + sum(h + GAP for _, _, h in TRACKS) + 8


# ------------------------------------------------------------------ ảnh thu nhỏ & dạng sóng (chạy nền)
class _Sig(QObject):
    ready = Signal()


_SIG = None
_THUMBS: dict[str, QPixmap] = {}
_IMAGES: dict[str, QImage] = {}
_WAVES: dict[str, list[float]] = {}
_PENDING: set[str] = set()


def _sig() -> _Sig:
    global _SIG
    if _SIG is None:
        _SIG = _Sig()
    return _SIG


class _Job(QRunnable):
    def __init__(self, kind: str, src: str):
        super().__init__()
        self.kind, self.src = kind, src

    def run(self):
        try:
            if self.kind == "thumb":
                d = data_dir() / "thumbs"
                d.mkdir(exist_ok=True)
                out = d / (hashlib.md5(("tl" + self.src).encode()).hexdigest() + ".jpg")
                if not out.exists():
                    subprocess.run([ffmpeg(), "-y", "-ss", "0.3", "-i", self.src, "-frames:v", "1", "-vf", "scale=-2:120", str(out)],
                                   capture_output=True, creationflags=NOWIN, timeout=30)
                _IMAGES[self.src] = QImage(str(out)) if out.exists() else QImage()   # QPixmap chỉ tạo ở luồng giao diện
            else:
                p = subprocess.run([ffmpeg(), "-v", "error", "-i", self.src, "-ac", "1", "-ar", "100", "-f", "s16le", "-"],
                                   capture_output=True, creationflags=NOWIN, timeout=120)
                import array
                a = array.array("h")
                a.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
                peak = max(1, max((abs(x) for x in a), default=1))
                _WAVES[self.src] = [abs(x) / peak for x in a]      # 100 mẫu / giây
        except Exception:
            if self.kind == "thumb":
                _IMAGES[self.src] = QImage()
            else:
                _WAVES[self.src] = []
        _PENDING.discard(self.kind + self.src)
        _sig().ready.emit()


def thumb_pixmap(src: str) -> QPixmap | None:
    """Gọi ở luồng giao diện: đổi ảnh đã tạo ở luồng nền sang QPixmap."""
    if src not in _THUMBS and src in _IMAGES:
        _THUMBS[src] = QPixmap.fromImage(_IMAGES.pop(src))
    return _THUMBS.get(src)


def _want(kind: str, src: str):
    key = kind + src
    have = _THUMBS if kind == "thumb" else _WAVES
    if kind == "thumb" and src in _IMAGES:
        return
    if src in have or key in _PENDING:
        return
    _PENDING.add(key)
    QThreadPool.globalInstance().start(_Job(kind, src))


def fmt_time(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:04.1f}"


class Timeline(QWidget):
    seek = Signal(float)              # người dùng tua kim
    selected = Signal(object)         # item hoặc None
    about_to_change = Signal()        # trước khi sửa (để lưu hoàn tác)
    changed = Signal()                # sau khi sửa
    dropped_media = Signal(str, float)  # kéo media từ kho vào (đường dẫn, thời điểm)

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.pps = 60.0               # điểm ảnh / giây
        self.playhead = 0.0
        self.sel_id: str | None = None
        self._drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.setMinimumHeight(TOTAL_H)
        _sig().ready.connect(self.update)

    # ------------------------------------------------------------ hình học
    def set_project(self, p: Project):
        self.project = p
        if self.sel_id and not p.find(self.sel_id):
            self.sel_id = None
        self._resize()
        self.update()

    def set_zoom(self, pps: float):
        self.pps = max(8.0, min(400.0, pps))
        self._resize()
        self.update()

    def _resize(self):
        w = int((self.project.duration + 30) * self.pps) + 40
        self.setMinimumWidth(max(w, 600))
        self.setMinimumHeight(TOTAL_H)

    def sizeHint(self):
        return QSize(int((self.project.duration + 30) * self.pps), TOTAL_H)

    def x_of(self, t: float) -> float:
        return 10 + t * self.pps

    def t_of(self, x: float) -> float:
        return max(0.0, (x - 10) / self.pps)

    def item_rects(self):
        """[(item, loại track, QRectF)] để vẽ và bắt chuột."""
        tr = track_rects(self.width())
        out = []
        acc = 0.0
        y, h = tr["video"]
        for c in self.project.clips:
            out.append((c, "video", QRectF(self.x_of(acc), y, c.dur * self.pps, h)))
            acc += c.dur
        y, h = tr["text"]
        for t in self.project.texts:
            out.append((t, "text", QRectF(self.x_of(t.start), y, t.dur * self.pps, h)))
        for a in self.project.audios:
            y, h = tr["voice" if a.track == "voice" else "music"]
            out.append((a, a.track, QRectF(self.x_of(a.start), y, a.dur * self.pps, h)))
        return out

    # ------------------------------------------------------------ vẽ
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0a0f33"))
        tr = track_rects(self.width())
        for key, _, h in TRACKS:
            y, h = tr[key]
            p.fillRect(QRectF(0, y, self.width(), h), QColor("#0d1442" if key != "video" else "#101a52"))
        # thước
        p.fillRect(QRectF(0, 0, self.width(), RULER), QColor("#070b24"))
        step = 1
        for s in (1, 2, 5, 10, 15, 30, 60):
            if s * self.pps >= 70:
                step = s
                break
        f = QFont(self.font())
        f.setPointSizeF(7.6)
        p.setFont(f)
        t = 0
        end = self.t_of(self.width()) + step
        while t <= end:
            x = self.x_of(t)
            p.setPen(QColor("#33407e"))
            p.drawLine(QPointF(x, RULER - 7), QPointF(x, RULER))
            p.setPen(QColor(C["text-faint"]))
            p.drawText(QPointF(x + 3, RULER - 9), fmt_time(t)[:-2])
            sub = step / 5
            for k in range(1, 5):
                xs = self.x_of(t + k * sub)
                p.setPen(QColor("#22357a"))
                p.drawLine(QPointF(xs, RULER - 4), QPointF(xs, RULER))
            t += step
        # các clip
        for it, kind, r in self.item_rects():
            self._draw_item(p, it, kind, r)
        # kim phát
        x = self.x_of(self.playhead)
        p.setPen(QPen(QColor("#f0abfc"), 2))
        p.drawLine(QPointF(x, 2), QPointF(x, self.height()))
        head = QPainterPath()
        head.moveTo(x - 6, 0)
        head.lineTo(x + 6, 0)
        head.lineTo(x, 9)
        head.closeSubpath()
        p.fillPath(head, QColor("#f0abfc"))
        if not self.project.clips:
            y, h = tr["video"]
            p.setPen(QColor(C["text-faint"]))
            p.drawText(QRectF(10, y, 600, h), Qt.AlignVCenter | Qt.AlignLeft,
                       "  Kéo video / ảnh từ khung Media vào đây, hoặc bấm đúp vào media để thêm.")
        p.end()

    def _draw_item(self, p: QPainter, it, kind: str, r: QRectF):
        sel = it.id == self.sel_id
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(1, 2, -1, -2), 6, 6)
        p.save()
        p.setClipPath(path)
        if kind == "video":
            _want("thumb", it.src) if it.kind == "video" else None
            pm = thumb_pixmap(it.src) if it.kind == "video" else None
            if pm is None and it.kind == "image":
                pm = _THUMBS.get(it.src)
                if pm is None:
                    _THUMBS[it.src] = QPixmap(it.src).scaledToHeight(120, Qt.SmoothTransformation)
                    pm = _THUMBS[it.src]
            p.fillRect(r, QColor("#1e2a6e"))
            if pm and not pm.isNull():
                th = r.height() - 4
                tw = pm.width() * th / max(1, pm.height())
                x = r.left()
                while x < r.right():
                    p.drawPixmap(QRectF(x, r.top() + 2, tw, th), pm, QRectF(pm.rect()))
                    x += tw
            p.fillRect(QRectF(r.left(), r.top(), r.width(), 16), QColor(5, 8, 32, 150))
            p.setPen(QColor("#e0e7ff"))
            f = QFont(self.font())
            f.setPointSizeF(7.6)
            p.setFont(f)
            label = Path(it.src).name + (f"  ×{it.speed:g}" if abs(it.speed - 1) > 1e-3 else "") + f"  {it.dur:.1f}s"
            p.drawText(r.adjusted(5, 1, -4, 0), Qt.AlignTop | Qt.AlignLeft, label)
        else:
            g = QLinearGradient(r.topLeft(), r.topRight())
            base = QColor(COL[kind])
            g.setColorAt(0, base)
            g.setColorAt(1, base.darker(130))
            p.fillPath(path, g)
            f = QFont(self.font())
            f.setPointSizeF(7.8)
            p.setFont(f)
            if kind == "text":
                p.setPen(QColor("white"))
                p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, "T  " + it.text.replace("\n", " "))
            else:
                _want("wave", it.src)
                wave = _WAVES.get(it.src)
                p.setPen(QPen(QColor(255, 255, 255, 110), 1))
                mid = r.center().y()
                amp = r.height() / 2 - 3
                if wave:
                    step = max(1, int(100 / self.pps))
                    for px in range(0, int(r.width()), 2):
                        i = int((it.in_s + px / self.pps) * 100)
                        v = max(wave[i:i + step] or [0]) if i < len(wave) else 0
                        x = r.left() + px
                        p.drawLine(QPointF(x, mid - v * amp), QPointF(x, mid + v * amp))
                p.setPen(QColor("white"))
                p.drawText(r.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, ("♪ " if kind == "music" else "Lồng tiếng: ") + Path(it.src).name)
        p.restore()
        pen = QPen(QColor(C["accent"]) if sel else QColor(0, 0, 0, 120), 2 if sel else 1)
        p.setPen(pen)
        p.drawPath(path)
        if sel:   # tay nắm 2 mép
            for x in (r.left() + 1, r.right() - 5):
                hp = QPainterPath()
                hp.addRoundedRect(QRectF(x, r.top() + 4, 4, r.height() - 8), 2, 2)
                p.fillPath(hp, QColor(C["accent"]))

    # ------------------------------------------------------------ chuột
    def _hit(self, pos):
        for it, kind, r in reversed(self.item_rects()):
            if r.contains(pos):
                zone = "body"
                if pos.x() - r.left() <= EDGE:
                    zone = "left"
                elif r.right() - pos.x() <= EDGE:
                    zone = "right"
                return it, kind, r, zone
        return None

    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        if pos.y() <= RULER:
            self._drag = {"type": "playhead"}
            self.playhead = self.t_of(pos.x())
            self.seek.emit(self.playhead)
            self.update()
            return
        hit = self._hit(pos)
        if not hit:
            self.sel_id = None
            self.selected.emit(None)
            self.playhead = self.t_of(pos.x())
            self.seek.emit(self.playhead)
            self.update()
            return
        it, kind, r, zone = hit
        self.sel_id = it.id
        self.selected.emit(it)
        self.about_to_change.emit()
        snap = {k: getattr(it, k) for k in ("in_s", "out_s", "start", "dur") if hasattr(it, k) and not isinstance(getattr(type(it), k, None), property)}
        self._drag = {"type": "item", "it": it, "kind": kind, "zone": zone, "x0": pos.x(), "snap": snap, "moved": False}
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self._drag:
            hit = self._hit(pos)
            self.setCursor(Qt.SizeHorCursor if hit and hit[3] != "body" else (Qt.OpenHandCursor if hit else Qt.ArrowCursor))
            return
        if self._drag["type"] == "playhead":
            self.playhead = self.t_of(pos.x())
            self.seek.emit(self.playhead)
            self.update()
            return
        d = self._drag
        it, kind, zone, s = d["it"], d["kind"], d["zone"], d["snap"]
        dt = (pos.x() - d["x0"]) / self.pps
        if abs(pos.x() - d["x0"]) > 2:
            d["moved"] = True
        if kind == "video":
            c: Clip = it
            if zone == "left":
                c.in_s = min(max(0.0, s["in_s"] + dt * c.speed), c.out_s - 0.1)
            elif zone == "right":
                hi = c.src_dur if c.kind == "video" else 3600
                c.out_s = max(min(hi, s["out_s"] + dt * c.speed), c.in_s + 0.1)
            else:   # đổi thứ tự
                clips = self.project.clips
                t = self.t_of(pos.x())
                acc, target = 0.0, len(clips) - 1
                for i, o in enumerate(clips):
                    if t < acc + o.dur / 2:
                        target = i
                        break
                    acc += o.dur
                cur = clips.index(c)
                if target != cur:
                    clips.insert(target, clips.pop(cur))
        elif kind == "text":
            t: TextItem = it
            if zone == "left":
                ns = min(max(0.0, s["start"] + dt), s["start"] + s["dur"] - 0.2)
                t.dur = s["dur"] - (ns - s["start"])
                t.start = ns
            elif zone == "right":
                t.dur = max(0.2, s["dur"] + dt)
            else:
                t.start = max(0.0, s["start"] + dt)
        else:
            a: AudioItem = it
            if zone == "left":
                nin = min(max(0.0, s["in_s"] + dt), a.out_s - 0.2)
                a.start = max(0.0, s["start"] + (nin - s["in_s"]))
                a.in_s = nin
            elif zone == "right":
                a.out_s = max(min(a.src_dur, s["out_s"] + dt), a.in_s + 0.2)
            else:
                a.start = max(0.0, s["start"] + dt)
        self._resize()
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag and self._drag.get("type") == "item" and self._drag.get("moved"):
            self.changed.emit()
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        hit = self._hit(e.position())
        if hit:
            self.selected.emit(hit[0])

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.pps * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15))
            e.accept()
        else:
            e.ignore()

    # ------------------------------------------------------------ kéo-thả từ kho media
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        t = self.t_of(e.position().x())
        paths = [u.toLocalFile() for u in e.mimeData().urls()] if e.mimeData().hasUrls() else e.mimeData().text().splitlines()
        for pth in paths:
            if pth and Path(pth).exists():
                self.dropped_media.emit(pth, t)
        e.acceptProposedAction()
