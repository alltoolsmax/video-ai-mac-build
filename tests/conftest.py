import functools
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["VIDEOAI_HEADLESS"] = "1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOAI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("VIDEOAI_KEEP_BROWSERS", "1")      # kiểm thử cần đọc lại trang sau khi chạy xong
    return tmp_path


@pytest.fixture()
def db(home):
    from videoai.core.db import Database
    return Database()


@pytest.fixture(scope="session")
def mock_site():
    d = Path(__file__).parent / "mock_site"

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(d)))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def clip():
    return str(Path(__file__).parent / "mock_site" / "clip.mp4")


@pytest.fixture(autouse=True)
def _ai_agent_not_stopped():
    """Mỗi bài kiểm thử bắt đầu với AI Agent chưa bị dừng (trạng thái dừng là toàn cục)."""
    from videoai.services import llm
    llm.begin()
    yield
    llm.begin()
