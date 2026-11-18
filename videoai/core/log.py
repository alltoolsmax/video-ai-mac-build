"""Logging ra file + phát lên giao diện (trang Log Chi Tiết)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import logs_dir

_listeners: list = []


class _UiHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        for cb in list(_listeners):
            try:
                cb(msg, record.levelno)
            except Exception:
                pass


def setup() -> logging.Logger:
    log = logging.getLogger("videoai")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    fh = RotatingFileHandler(logs_dir() / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    ui = _UiHandler()
    ui.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(ui)
    return log


def add_listener(cb) -> None:
    _listeners.append(cb)


def get(name: str) -> logging.Logger:
    return logging.getLogger("videoai." + name)
