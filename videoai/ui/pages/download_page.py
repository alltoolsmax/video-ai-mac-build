"""Download: dán link YouTube / TikTok / Facebook… → tải file video (TikTok lấy bản không logo)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QPlainTextEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..widgets import Card, GradientBar, PathPicker, button, combo, field, icon_button, label
from ..workers import run_bg
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...media import downloader as dl

COLS = ["#", "Nền tảng", "Video", "Tiến độ", "Trạng thái", ""]
PLATFORM_COLOR = {"YouTube": "#f87171", "TikTok": "#f0abfc", "Facebook": "#60a5fa", "Instagram": "#fb923c",
                  "X / Twitter": "#e2e8f0"}


class DownloadPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.rows: list[dict] = []          # {url, platform, title, pct, status, file, state}
        self.busy = False
        self._stop = False
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)
        v.addWidget(label("Download video", "h1"))
        row = QHBoxLayout()
        row.setSpacing(14)
        v.addLayout(row, 1)

        cfg = Card("Dán link video", "download")
        cfg.setFixedWidth(380)
        self.links = QPlainTextEdit()
        self.links.setPlaceholderText(tr("Dán link YouTube, TikTok, Facebook… mỗi dòng một link.\n"
                                         "Ví dụ:\nhttps://www.youtube.com/watch?v=…\nhttps://www.tiktok.com/@…/video/…\n"
                                         "https://www.facebook.com/…/videos/…"))
        self.links.setMinimumHeight(150)
        cfg.add(self.links)
        r = QHBoxLayout()
        b_paste = button("Dán từ bộ nhớ", "chip", "edit", "#67e8f9")
        b_paste.clicked.connect(self.paste)
        b_add = button("Thêm vào danh sách", "primary", "plus")
        b_add.clicked.connect(self.add_links)
        r.addWidget(b_paste)
        r.addWidget(b_add, 1)
        cfg.add(r)
        self.quality = combo(list(dl.QUALITIES))
        self.cookies = combo(list(dl.COOKIE_BROWSERS))
        self.cookies.setToolTip(tr("Chỉ cần khi video riêng tư / cần đăng nhập (thường gặp ở Facebook). "
                                   "Dùng tài khoản đã đăng nhập trên trình duyệt đó."))
        self.out = PathPicker(str(default_output_dir() / "download"))
        cfg.add(field("Chất lượng", self.quality))
        cfg.add(field("Cookie từ trình duyệt", self.cookies))
        cfg.add(field("Thư mục lưu", self.out))
        note = label("TikTok: tự lấy bản KHÔNG có logo. YouTube, Facebook: file gốc không gắn logo. "
                     "Chỉ tải video bạn có quyền sử dụng.", "faint")
        note.setWordWrap(True)
        cfg.add(note)
        cfg.body_layout.addStretch()
        self.bar = GradientBar()
        self.state = label("", "faint")
        self.state.setWordWrap(True)
        cfg.add(self.bar)
        cfg.add(self.state)
        r2 = QHBoxLayout()
        self.b_run = button("Bắt đầu tải", "start", "download")
        self.b_run.clicked.connect(self.run)
        self.b_stop = button("Dừng", "chip", "stop", "#fb7185")
        self.b_stop.clicked.connect(self.stop)
        self.b_stop.setEnabled(False)
        r2.addWidget(self.b_run, 1)
        r2.addWidget(self.b_stop)
        cfg.add(r2)
        row.addWidget(cfg)

        lst = Card("Danh sách tải (xong: bấm biểu tượng mắt để xem, thư mục để mở nơi lưu)", "list", icon_color="#a5b4fc")
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in COLS])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        h.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 128)
        self.table.setColumnWidth(4, 180)
        h.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 84)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.cellDoubleClicked.connect(self.open_row)
        lst.add(self.table)
        r3 = QHBoxLayout()
        b_dir = button("Mở thư mục lưu", "chip", "folder", "#67e8f9")
        b_dir.clicked.connect(lambda: self._open(self.out.text()))
        b_retry = button("Tải lại mục lỗi", "chip", "retry", "#fbbf24")
        b_retry.clicked.connect(self.retry_failed)
        b_clr = button("Xóa mục đã xong", "chip", "trash", "#fb7185")
        b_clr.clicked.connect(self.clear_done)
        r3.addWidget(b_dir)
        r3.addWidget(b_retry)
        r3.addWidget(b_clr)
        r3.addStretch()
        lst.add(r3)
        row.addWidget(lst, 1)

    # ------------------------------------------------------------ danh sách
    def paste(self):
        t = QGuiApplication.clipboard().text()
        if t:
            cur = self.links.toPlainText().rstrip()
            self.links.setPlainText((cur + "\n" if cur else "") + t.strip())

    def add_links(self) -> int:
        urls = dl.split_links(self.links.toPlainText())
        have = {r["url"] for r in self.rows}
        new = [u for u in urls if u not in have]
        for u in new:
            self.rows.append({"url": u, "platform": dl.platform_of(u), "title": "", "pct": 0.0, "status": tr("Chờ tải"),
                              "file": "", "state": "wait"})
        if urls:
            self.links.clear()
        elif self.links.toPlainText().strip():
            self.ctx.toast("error", tr("Không thấy link hợp lệ (cần bắt đầu bằng http:// hoặc https://)."))
        self._render()
        return len(new)

    def _render(self):
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            cells = [str(i + 1), r["platform"], r["title"] or r["url"], self._pct_text(r), r["status"]]
            for c, txt in enumerate(cells):
                it = self.table.item(i, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.table.setItem(i, c, it)
                it.setText(txt)
                if c == 2:
                    it.setToolTip(r["file"] or r["url"])
            self.table.item(i, 1).setForeground(QColor(PLATFORM_COLOR.get(r["platform"], "#94a3b8")))
            col = {"done": "#4ade80", "error": "#fb7185", "run": "#67e8f9"}.get(r["state"], "#94a3b8")
            self.table.item(i, 4).setForeground(QColor(col))
            self._actions(i, r)

    def _actions(self, i: int, r: dict):
        """Tác vụ đã tải xong: nút mở thư mục chứa file + nút mắt để xem ngay."""
        has = self.table.cellWidget(i, 5)
        want = r["state"] == "done" and bool(r["file"])
        if has is not None and (not want or has.property("file") != r["file"]):
            self.table.removeCellWidget(i, 5)
            has = None
        if want and has is None:
            w = QWidget()
            w.setProperty("file", r["file"])
            hl = QHBoxLayout(w)
            hl.setContentsMargins(4, 2, 4, 2)
            hl.setSpacing(6)
            b_dir = icon_button("folder", tr("Mở thư mục chứa file"), "#67e8f9")
            b_eye = icon_button("eye", tr("Xem video"), "#4ade80")
            for b in (b_dir, b_eye):
                b.setFixedSize(32, 30)
                hl.addWidget(b)
            f = r["file"]
            b_dir.clicked.connect(lambda _=False, f=f: self.reveal(f))
            b_eye.clicked.connect(lambda _=False, f=f: self.view(f))
            self.table.setCellWidget(i, 5, w)

    def reveal(self, f: str):
        from .gen_page import reveal
        reveal(f)

    def view(self, f: str):
        if not Path(f).exists():
            return self.ctx.toast("error", tr("Không tìm thấy file (có thể đã bị xóa hoặc di chuyển)."))
        from ..viewer import MediaViewer
        MediaViewer(self, [{"path": f, "kind": "video"}], Path(f).stem).exec()

    @staticmethod
    def _pct_text(r) -> str:
        if r["state"] == "done":
            return "100%"
        if r["state"] == "run":
            n = int(r["pct"] / 10)
            return f"{r['pct']:.0f}%  " + "▰" * (n // 2) + "▱" * (5 - n // 2)
        return ""

    def clear_done(self):
        if self.busy:
            return self.ctx.toast("info", tr("Đang tải, chờ xong rồi xóa."))
        self.rows = [r for r in self.rows if r["state"] != "done"]
        self._render()

    def retry_failed(self):
        for r in self.rows:
            if r["state"] == "error":
                r.update(state="wait", status=tr("Chờ tải"), pct=0.0)
        self._render()
        self.run()

    def _open(self, path):
        Path(path).mkdir(parents=True, exist_ok=True) if not Path(path).suffix else None
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_row(self, i, _c):
        if 0 <= i < len(self.rows) and self.rows[i]["file"]:
            self.view(self.rows[i]["file"])

    # ------------------------------------------------------------ tải
    def run(self):
        if self.busy:
            return
        if self.links.toPlainText().strip():
            self.add_links()
        todo = [i for i, r in enumerate(self.rows) if r["state"] == "wait"]
        if not todo:
            return self.ctx.toast("info", tr("Dán link video rồi bấm Bắt đầu tải."))
        quality = list(dl.QUALITIES)[self.quality.currentIndex()]          # combo hiển thị bản dịch → lấy theo vị trí
        cookies = list(dl.COOKIE_BROWSERS.values())[self.cookies.currentIndex()]
        out = self.out.text()
        urls = {i: self.rows[i]["url"] for i in todo}
        self._stop = False

        def job(progress):
            ok = 0
            for n, i in enumerate(todo):
                if self._stop:
                    break

                def ev(kind, val, i=i):
                    if kind == "progress":
                        val = {"p": val.percent, "s": val.speed, "e": val.eta}
                    progress(0, json.dumps({"i": i, "k": kind, "v": val}))
                progress(0, json.dumps({"i": i, "k": "start", "v": n}))
                try:
                    f = dl.download(urls[i], out, quality, cookies, on_event=ev, cancel=lambda: self._stop,
                                    log=lambda m, i=i: progress(0, json.dumps({"i": i, "k": "log", "v": m})))
                    ok += 1
                    progress(0, json.dumps({"i": i, "k": "file", "v": f}))
                except Exception as e:
                    progress(0, json.dumps({"i": i, "k": "error", "v": str(e)}))
            return ok

        self.busy = True
        self._todo = todo
        self.b_run.setEnabled(False)
        self.b_run.setText(tr("Đang tải…"))
        self.b_stop.setEnabled(True)
        self.bar.set(0)
        for i in todo:
            self.rows[i]["status"] = tr("Chờ tải")
        self._render()
        run_bg(job, on_done=self._done, on_error=self._err, on_progress=self._progress)

    def _progress(self, _p, msg):
        try:
            d = json.loads(msg)
        except Exception:
            return
        r = self.rows[d["i"]]
        k, v = d["k"], d["v"]
        if k == "start":
            r.update(state="run", status=tr("Đang lấy thông tin…"), pct=0.0)
        elif k == "log":
            r["status"] = tr(v)
        elif k == "title":
            r["title"] = v
            r["status"] = tr("Đang tải…")
        elif k == "progress":
            r["pct"] = v["p"]
            r["status"] = tr("Đang tải") + (f" · {v['s']}" if v["s"] else "") + (f" · {tr('còn')} {v['e']}" if v["e"] else "")
        elif k == "merge":
            r["pct"] = 100.0
            r["status"] = tr("Đang ghép hình + tiếng…")
        elif k == "file":
            r.update(state="done", file=v, status="✓ " + tr("Xong") + " · " + Path(v).suffix.lstrip(".").upper())
            if not r["title"]:
                r["title"] = Path(v).stem
        elif k == "error":
            r.update(state="error", status="✗ " + tr(v))
            r["error"] = v
        done = sum(1 for i in self._todo if self.rows[i]["state"] in ("done", "error"))
        cur = r["pct"] / 100 if r["state"] == "run" else 0
        self.bar.set((done + cur) / max(1, len(self._todo)))
        self.state.setText(tr("Đang tải") + f" {min(done + 1, len(self._todo))}/{len(self._todo)}"
                           + (f" · {r['title'][:50]}" if r["title"] else ""))
        self._render()

    def stop(self):
        self._stop = True
        self.b_stop.setEnabled(False)
        self.state.setText(tr("Đang dừng…"))

    def _finish(self):
        self.busy = False
        self.b_run.setEnabled(True)
        self.b_run.setText(tr("Bắt đầu tải"))
        self.b_stop.setEnabled(False)
        for r in self.rows:
            if r["state"] == "run":
                r.update(state="wait", status=tr("Đã dừng"), pct=0.0)
        self._render()

    def _done(self, ok):
        self._finish()
        err = sum(1 for i in self._todo if self.rows[i]["state"] == "error")
        self.bar.set(1.0 if not self._stop else self.bar.value)
        self.state.setText(tr("Đã tải xong") + f" {ok} video" + (f" · {err} " + tr("lỗi") if err else ""))
        if ok:
            self.ctx.toast("ok", tr("Đã tải xong") + f" {ok} video")
        if err:
            first = next(self.rows[i] for i in self._todo if self.rows[i]["state"] == "error")
            self.ctx.toast("error", first.get("error", ""))

    def _err(self, msg):
        self._finish()
        self.ctx.toast("error", msg)
