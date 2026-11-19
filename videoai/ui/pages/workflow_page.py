"""Workflow: nối các bước Prompt → Tạo ảnh → Tạo video → Tách khung → ... thành một quy trình chạy tự động."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGraphicsItem, QGraphicsPathItem, QGraphicsProxyWidget,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QInputDialog, QLineEdit, QMenu,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from ..theme import C, G
from ..widgets import FrameSlot, button, label
from ...core.db import new_id
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...core.platforms import PAGE_BY_KEY, PAGES
from ...media import ffmpeg

TYPE_COLOR = {"prompt": "#22d3ee", "image": "#c084fc", "video": "#f472b6"}
NODE_TYPES = {
    "prompt": ("Prompt", [], [("Prompt", "prompt")]),
    "reference": ("Ảnh tham chiếu", [], [("Ảnh", "image")]),
    "generate": ("Tạo ảnh", [("Prompt", "prompt"), ("Ảnh 1", "image")], [("Ảnh", "image")]),
    "video_generate": ("Tạo video", [("Prompt", "prompt"), ("Ảnh đầu", "image"), ("Ảnh cuối (tùy chọn)", "image")], [("Video", "video")]),
    "frame_extract": ("Tách khung cuối", [("Video", "video")], [("Ảnh", "image")]),
    "join": ("Ghép video", [("Video 1", "video"), ("Video 2", "video"), ("Video 3", "video"), ("Video 4", "video")], [("Video", "video")]),
}
IMG_PAGES = [p.key for p in PAGES if p.ready and any(m.key in ("t2i", "i2i") for m in p.modes)]
VID_PAGES = [p.key for p in PAGES if p.ready and any(m.key in ("t2v", "i2v") for m in p.modes)]


class Socket(QGraphicsItem):
    R = 6

    def __init__(self, node, idx, name, kind, is_out):
        super().__init__(node)
        self.node, self.idx, self.name, self.kind, self.is_out = node, idx, name, kind, is_out
        self.edges: list = []
        self.setAcceptHoverEvents(True)

    def boundingRect(self):
        return QRectF(-self.R - 2, -self.R - 2, 2 * self.R + 4, 2 * self.R + 4)

    def paint(self, p, *a):
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(TYPE_COLOR[self.kind]))
        p.setPen(QPen(QColor("#0b1030"), 2))
        p.drawEllipse(QPointF(0, 0), self.R, self.R)

    def mousePressEvent(self, e):
        self.scene().start_drag(self)

    def center(self):
        return self.scenePos()


class Edge(QGraphicsPathItem):
    def __init__(self, a: Socket, b: Socket | None = None):
        super().__init__()
        self.a, self.b = a, b
        self.end = a.center()
        self.setZValue(-1)
        self.setPen(QPen(QColor(TYPE_COLOR[a.kind]), 2.4))
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.update_path()

    def update_path(self):
        p1 = self.a.center()
        p2 = self.b.center() if self.b else self.end
        dx = max(60, abs(p2.x() - p1.x()) / 2)
        path = QPainterPath(p1)
        path.cubicTo(p1 + QPointF(dx, 0), p2 - QPointF(dx, 0), p2)
        self.setPath(path)


class Node(QGraphicsItem):
    W = 320

    def __init__(self, ntype: str, nid: int, values: dict | None = None):
        super().__init__()
        self.ntype, self.id = ntype, nid
        self.title, ins, outs = NODE_TYPES[ntype]
        self.values = values or {}
        self.status = ""
        self.result = None
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.inputs = [Socket(self, i, n, k, False) for i, (n, k) in enumerate(ins)]
        self.outputs = [Socket(self, i, n, k, True) for i, (n, k) in enumerate(outs)]
        self.form = self._form()
        self.proxy = QGraphicsProxyWidget(self)
        self.proxy.setWidget(self.form)
        top = 34 + 22 * max(len(ins), len(outs))
        self.proxy.setPos(10, top)
        self.form.setFixedWidth(self.W - 20)
        self.H = top + self.form.sizeHint().height() + 14
        for s in self.inputs:
            s.setPos(0, 44 + 22 * s.idx)
        for s in self.outputs:
            s.setPos(self.W, 44 + 22 * s.idx)

    def _form(self):
        w = QWidget()
        w.setStyleSheet(f"QWidget{{background:transparent;}} QPlainTextEdit,QComboBox,QLineEdit{{background:{C['input-bg']};"
                        f"border:1px solid {C['border-input']};border-radius:8px;}}")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.widgets = {}
        if self.ntype == "prompt":
            t = QPlainTextEdit(self.values.get("prompt", ""))
            t.setPlaceholderText(tr("Nội dung prompt…"))
            t.setFixedHeight(90)
            self.widgets["prompt"] = t
            v.addWidget(t)
        elif self.ntype == "reference":
            s = FrameSlot("Ảnh tham chiếu")
            s.set_path(self.values.get("path", ""))
            self.widgets["path"] = s
            v.addWidget(s)
        elif self.ntype in ("generate", "video_generate"):
            pages = IMG_PAGES if self.ntype == "generate" else VID_PAGES
            cb = QComboBox()
            for k in pages:
                cb.addItem(PAGE_BY_KEY[k].label, k)
            i = cb.findData(self.values.get("page"))
            cb.setCurrentIndex(max(0, i))
            self.widgets["page"] = cb
            v.addWidget(cb)
            extra = QLineEdit(self.values.get("suffix", ""))
            extra.setPlaceholderText(tr("Thêm vào cuối prompt (tùy chọn)"))
            self.widgets["suffix"] = extra
            v.addWidget(extra)
        elif self.ntype == "join":
            o = QLineEdit(self.values.get("name", "workflow.mp4"))
            self.widgets["name"] = o
            v.addWidget(o)
        return w

    def get_values(self) -> dict:
        out = {}
        for k, w in self.widgets.items():
            if isinstance(w, QPlainTextEdit):
                out[k] = w.toPlainText()
            elif isinstance(w, QComboBox):
                out[k] = w.currentData()
            elif isinstance(w, QLineEdit):
                out[k] = w.text()
            elif isinstance(w, FrameSlot):
                out[k] = w.path
        return out

    def boundingRect(self):
        return QRectF(-8, -8, self.W + 16, self.H + 16)

    def paint(self, p, *a):
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.W, self.H)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(C["surface-2"]))
        sel = self.isSelected()
        col = {"running": C["info"], "done": C["success"], "error": C["danger"]}.get(self.status)
        p.setPen(QPen(QColor(col or (C["accent"] if sel else C["border"])), 2 if (sel or col) else 1))
        p.drawPath(path)
        hr = QRectF(0, 0, self.W, 30)
        hp = QPainterPath()
        hp.addRoundedRect(hr, 12, 12)
        p.save()
        p.setClipRect(hr)
        p.fillPath(hp, QBrush(_grad(hr)))
        p.restore()
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(hr.adjusted(12, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, f"{tr(self.title)}  #{self.id}")
        if self.status:
            p.drawText(hr.adjusted(12, 0, -12, 0), Qt.AlignVCenter | Qt.AlignRight,
                       {"running": "…", "done": "✓", "error": "!"}.get(self.status, ""))
        f.setBold(False)
        f.setPointSizeF(8.8)
        p.setFont(f)
        p.setPen(QColor(C["text-muted"]))
        for s in self.inputs:
            p.drawText(QRectF(12, s.pos().y() - 9, 140, 18), Qt.AlignVCenter | Qt.AlignLeft, tr(s.name))
        for s in self.outputs:
            p.drawText(QRectF(self.W - 152, s.pos().y() - 9, 140, 18), Qt.AlignVCenter | Qt.AlignRight, tr(s.name))

    def itemChange(self, ch, val):
        if ch == QGraphicsItem.ItemPositionHasChanged:
            for s in self.inputs + self.outputs:
                for e in s.edges:
                    e.update_path()
        return super().itemChange(ch, val)


def _grad(r):
    from ..theme import gradient
    return gradient(r, G["active"])


class Scene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.drag: Edge | None = None
        self.next_id = 1

    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor(C["bg"]))
        p.setPen(QPen(QColor("#18245e"), 1.6))
        step = 24
        x0 = int(rect.left()) - int(rect.left()) % step
        y0 = int(rect.top()) - int(rect.top()) % step
        for x in range(x0, int(rect.right()), step):
            for y in range(y0, int(rect.bottom()), step):
                p.drawPoint(x, y)

    def nodes(self) -> list[Node]:
        return [i for i in self.items() if isinstance(i, Node)]

    def add_node(self, ntype, pos, values=None, nid=None):
        n = Node(ntype, nid or self.next_id, values)
        self.next_id = max(self.next_id, n.id + 1)
        n.setPos(pos)
        self.addItem(n)
        return n

    def connect(self, a: Socket, b: Socket):
        if a.is_out == b.is_out or a.kind != b.kind or a.node is b.node:
            return None
        if not a.is_out:
            a, b = b, a
        for e in list(b.edges):  # một ô vào chỉ nhận một dây
            self.remove_edge(e)
        e = Edge(a, b)
        a.edges.append(e)
        b.edges.append(e)
        self.addItem(e)
        return e

    def remove_edge(self, e):
        for s in (e.a, e.b):
            if s and e in s.edges:
                s.edges.remove(e)
        self.removeItem(e)

    def start_drag(self, s: Socket):
        self.drag = Edge(s)
        self.addItem(self.drag)

    def mouseMoveEvent(self, e):
        if self.drag:
            self.drag.end = e.scenePos()
            self.drag.update_path()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.drag:
            target = next((i for i in self.items(e.scenePos()) if isinstance(i, Socket)), None)
            a = self.drag.a
            self.removeItem(self.drag)
            self.drag = None
            if target:
                self.connect(a, target)
        super().mouseReleaseEvent(e)

    def delete_selected(self):
        for i in self.selectedItems():
            if isinstance(i, Edge):
                self.remove_edge(i)
            elif isinstance(i, Node):
                for s in i.inputs + i.outputs:
                    for ed in list(s.edges):
                        self.remove_edge(ed)
                self.removeItem(i)

    def to_json(self) -> dict:
        nodes = []
        for n in self.nodes():
            nodes.append({"id": n.id, "type": n.ntype, "x": n.pos().x(), "y": n.pos().y(), "values": n.get_values()})
        edges = []
        for i in self.items():
            if isinstance(i, Edge) and i.b:
                edges.append({"from": i.a.node.id, "out": i.a.idx, "to": i.b.node.id, "in": i.b.idx})
        return {"version": 1, "nodes": nodes, "edges": edges}

    def from_json(self, d: dict):
        self.clear()
        self.next_id = 1
        by = {}
        for n in d.get("nodes", []):
            if n["type"] in NODE_TYPES:
                by[n["id"]] = self.add_node(n["type"], QPointF(n["x"], n["y"]), n.get("values"), n["id"])
        for e in d.get("edges", []):
            a, b = by.get(e["from"]), by.get(e["to"])
            if a and b and e["out"] < len(a.outputs) and e["in"] < len(b.inputs):
                self.connect(a.outputs[e["out"]], b.inputs[e["in"]])


class View(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._pan = None

    def wheelEvent(self, e):
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and e.modifiers() & Qt.AltModifier):
            self._pan = e.position()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._pan = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.scene().delete_selected()
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        pos = self.mapToScene(e.pos())
        m = QMenu(self)
        for k, (title, _, _) in NODE_TYPES.items():
            m.addAction(tr("Thêm") + ": " + tr(title), lambda k=k: self.scene().add_node(k, pos))
        m.exec(e.globalPos())


# ---------------------------------------------------------------- chạy workflow
class _RunSig(QObject):
    node = Signal(int, str)
    done = Signal(str)


class WorkflowRunner:
    """Chạy theo thứ tự phụ thuộc. Bước tạo ảnh/video đưa tác vụ vào hàng đợi của trang tương ứng và chờ xong."""

    def __init__(self, ctx, graph: dict, sig: _RunSig):
        self.ctx, self.g, self.sig = ctx, graph, sig
        self.stop = False

    def _account_for(self, page_key):
        st = self.ctx.db.get_setting(f"page_{page_key}", {}) or {}
        pdef = PAGE_BY_KEY[page_key]
        accs = [a for a in self.ctx.db.accounts(pdef.platform) if a["enabled"]]
        ids = [a["id"] for a in accs]
        for a in (st.get("account_ids") or [st.get("account_id")]):
            if a in ids:
                return a
        return ids[0] if ids else None

    def _queue_and_wait(self, page_key, mode, prompt, refs) -> list[str]:
        pdef = PAGE_BY_KEY[page_key]
        acc = self._account_for(page_key)
        if not acc:
            raise RuntimeError(f"{pdef.label}: chưa có tài khoản")
        st = self.ctx.db.get_setting(f"page_{page_key}", {}) or {}
        params = {"model": st.get("model", pdef.models[0]), "ratio": st.get("ratio", pdef.ratios[0])}
        out = str(default_output_dir() / "workflow" / time.strftime("%Y-%m-%d"))
        bid = self.ctx.db.create_batch(pdef.platform, page_key, params, out, "flat",
                                       [{"mode": mode, "prompt": prompt, "refs": refs, "count": 1}], source="workflow")
        self.ctx.engine.start_page(page_key, acc, 1, (0, 0))
        while not self.stop:
            j = self.ctx.db.one("SELECT * FROM jobs WHERE batch_id=?", (bid,))
            if j["status"] == "done":
                return [o["path"] for o in self.ctx.db.outputs(j["id"])]
            if j["status"] in ("failed", "blocked", "cancelled"):
                from ...core.errors import friendly
                raise RuntimeError(friendly(j["error_code"]))
            time.sleep(2)
        raise RuntimeError("đã dừng")

    def run(self):
        nodes = {n["id"]: n for n in self.g["nodes"]}
        ins: dict[int, dict[int, tuple[int, int]]] = {}
        for e in self.g["edges"]:
            ins.setdefault(e["to"], {})[e["in"]] = (e["from"], e["out"])
        results: dict[int, list] = {}
        order, seen = [], set()

        def visit(i, stack=()):
            if i in seen:
                return
            if i in stack:
                raise RuntimeError("Workflow có vòng lặp")
            for (src, _) in ins.get(i, {}).values():
                visit(src, stack + (i,))
            seen.add(i)
            order.append(i)

        for i in nodes:
            visit(i)
        for i in order:
            if self.stop:
                break
            n = nodes[i]
            v = n.get("values", {})
            get = lambda k: (results.get(ins[i][k][0], [None])[ins[i][k][1]] if i in ins and k in ins[i] else None)
            self.sig.node.emit(i, "running")
            try:
                t = n["type"]
                if t == "prompt":
                    results[i] = [v.get("prompt", "")]
                elif t == "reference":
                    results[i] = [v.get("path", "")]
                elif t == "generate":
                    prompt = " ".join(x for x in (get(0) or "", v.get("suffix", "")) if x)
                    ref = get(1)
                    files = self._queue_and_wait(v.get("page") or "flow_image", "i2i" if ref else "t2i", prompt, [ref] if ref else [])
                    results[i] = [files[0] if files else None]
                elif t == "video_generate":
                    prompt = " ".join(x for x in (get(0) or "", v.get("suffix", "")) if x)
                    refs = [r for r in (get(1), get(2)) if r]
                    files = self._queue_and_wait(v.get("page") or "flow_video", "i2v" if refs else "t2v", prompt, refs)
                    results[i] = [files[0] if files else None]
                elif t == "frame_extract":
                    src = get(0)
                    out = str(Path(src).with_name(Path(src).stem + "_last.png"))
                    ffmpeg.extract_frame(src, out, "last")
                    results[i] = [out]
                elif t == "join":
                    clips = [c for c in (get(k) for k in range(4)) if c]
                    out = str(default_output_dir() / "workflow" / (v.get("name") or "workflow.mp4"))
                    Path(out).parent.mkdir(parents=True, exist_ok=True)
                    ffmpeg.concat(clips, out)
                    results[i] = [out]
                self.sig.node.emit(i, "done")
            except Exception as e:
                self.sig.node.emit(i, "error")
                self.sig.done.emit(f"#{i}: {e}")
                return
        self.sig.done.emit("")


class WorkflowPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.runner = None
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        top.addWidget(label("Workflow", "h1"))
        top.addSpacing(10)
        top.addWidget(label("Chuột phải để thêm bước · kéo từ chấm tròn bên phải sang chấm bên trái để nối · Delete để xóa · Alt+kéo để di chuyển", "faint"))
        top.addStretch()
        for text, kind, ic, fn in (("Mới", "chip", "plus", self.new), ("Mở", "chip", "folder", self.open),
                                   ("Lưu", "chip", "save", self.save), ("Mẫu", "chip", "sparkle", self.sample),
                                   ("Chạy", "start", "play", self.run), ("Dừng", "stop", "stop", self.stop)):
            b = button(text, kind, ic, "#67e8f9" if kind == "chip" else "#ffffff")
            b.clicked.connect(fn)
            top.addWidget(b)
        v.addLayout(top)
        self.scene = Scene()
        self.view = View(self.scene)
        v.addWidget(self.view, 1)
        self.state = label("", "faint")
        v.addWidget(self.state)
        self.sig = _RunSig()
        self.sig.node.connect(self._node_state)
        self.sig.done.connect(self._done)
        saved = ctx.db.get_setting("workflow_current")
        if saved:
            self.scene.from_json(saved)
        else:
            self.sample()

    def new(self):
        self.scene.clear()
        self.scene.next_id = 1

    def sample(self):
        """Mẫu: prompt → ảnh → video (ảnh đầu) → tách khung cuối → video cảnh 2 → ghép."""
        self.scene.from_json({"nodes": [
            {"id": 1, "type": "prompt", "x": 0, "y": 0, "values": {"prompt": "Một cô gái mặc áo dài trắng đứng bên hồ sen lúc bình minh"}},
            {"id": 2, "type": "generate", "x": 380, "y": 0, "values": {"page": "flow_image"}},
            {"id": 3, "type": "prompt", "x": 380, "y": 260, "values": {"prompt": "Cô gái quay lại mỉm cười, máy quay tiến chậm"}},
            {"id": 4, "type": "video_generate", "x": 760, "y": 60, "values": {"page": "flow_video"}},
            {"id": 5, "type": "frame_extract", "x": 1140, "y": 60, "values": {}},
            {"id": 6, "type": "prompt", "x": 1140, "y": 260, "values": {"prompt": "Cô gái bước đi dọc bờ hồ, gió thổi nhẹ"}},
            {"id": 7, "type": "video_generate", "x": 1520, "y": 60, "values": {"page": "flow_video"}},
            {"id": 8, "type": "join", "x": 1900, "y": 60, "values": {"name": "canh_ho_sen.mp4"}},
        ], "edges": [
            {"from": 1, "out": 0, "to": 2, "in": 0}, {"from": 3, "out": 0, "to": 4, "in": 0},
            {"from": 2, "out": 0, "to": 4, "in": 1}, {"from": 4, "out": 0, "to": 5, "in": 0},
            {"from": 6, "out": 0, "to": 7, "in": 0}, {"from": 5, "out": 0, "to": 7, "in": 1},
            {"from": 4, "out": 0, "to": 8, "in": 0}, {"from": 7, "out": 0, "to": 8, "in": 1},
        ]})
        self._fitted = False
        if self.isVisible():
            self._fit()

    def save(self):
        f, _ = QFileDialog.getSaveFileName(self, tr("Lưu workflow"), "workflow.json", "Workflow (*.json)")
        if f:
            Path(f).write_text(json.dumps(self.scene.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
            self.ctx.toast("ok", tr("Đã lưu workflow"))

    def open(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Mở workflow"), "", "Workflow (*.json)")
        if f:
            self.scene.from_json(json.loads(Path(f).read_text(encoding="utf-8")))

    def run(self):
        if self.runner:
            return
        g = self.scene.to_json()
        self.ctx.db.set_setting("workflow_current", g)
        for n in self.scene.nodes():
            n.status = ""
            n.update()
        self.runner = WorkflowRunner(self.ctx, g, self.sig)
        threading.Thread(target=self.runner.run, daemon=True).start()
        self.state.setText(tr("Đang chạy workflow…"))

    def stop(self):
        if self.runner:
            self.runner.stop = True

    def _node_state(self, nid, st):
        for n in self.scene.nodes():
            if n.id == nid:
                n.status = st
                n.update()

    def _done(self, err):
        self.runner = None
        if err:
            self.state.setText(tr("Lỗi") + " " + err)
            self.ctx.toast("error", tr("Workflow dừng ở bước") + " " + err)
        else:
            self.state.setText(tr("Workflow chạy xong."))
            self.ctx.toast("ok", tr("Workflow chạy xong."))

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()

    def _fit(self):
        if not getattr(self, "_fitted", False) and self.scene.nodes():
            self._fitted = True
            r = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
            self.view.fitInView(r, Qt.KeepAspectRatio)
            if self.view.transform().m11() > 1:
                self.view.resetTransform()
                self.view.centerOn(r.center())

    def hideEvent(self, e):
        self.ctx.db.set_setting("workflow_current", self.scene.to_json())
        super().hideEvent(e)
