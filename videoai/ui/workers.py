"""Chạy việc nặng (ffmpeg, upscale) ở luồng nền, báo tiến độ về giao diện."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Sig(QObject):
    progress = Signal(int, str)
    done = Signal(object)
    error = Signal(str)


class Task(QRunnable):
    def __init__(self, fn, *args, **kw):
        super().__init__()
        self.fn, self.args, self.kw = fn, args, kw
        self.sig = _Sig()

    def run(self):
        try:
            res = self.fn(*self.args, progress=lambda p, m="": self.sig.progress.emit(int(p), m), **self.kw)
            self.sig.done.emit(res)
        except Exception as e:
            traceback.print_exc()
            self.sig.error.emit(str(e)[:600])


def run_bg(fn, *args, on_done=None, on_error=None, on_progress=None, **kw) -> Task:
    t = Task(fn, *args, **kw)
    if on_done:
        t.sig.done.connect(on_done)
    if on_error:
        t.sig.error.connect(on_error)
    if on_progress:
        t.sig.progress.connect(on_progress)
    QThreadPool.globalInstance().start(t)
    return t
