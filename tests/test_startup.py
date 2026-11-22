"""Mở tools THẬT (python -m videoai.main) như khách mở – có dữ liệu của bản cũ – và phải khởi động xong, tự thoát êm.
Bắt các lỗi chỉ lộ ra ở đường khởi động thật (vd biến bị xóa trong main.py làm tools tắt ngay khi mở – lỗi bản 2.0.2)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_real_startup_with_old_data(tmp_path):
    home = tmp_path / "home"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", VIDEOAI_HOME=str(home), VIDEOAI_HEADLESS="1",
               VIDEOAI_SMOKE="2500")
    seed = ("from videoai.core.db import Database\n"
            "db = Database()\n"
            "db.set_setting('page_flow_image', {'ratio': '16:9 Ngang', 'draft': 'abc', 'save_dir': '/tmp/kq'})\n"
            "db.set_setting('page_flow_video', {'ratio': '16:9', 'draft': 'x'})\n"
            "db.set_setting('script_dialog', {'idea': 'cũ'})\n"
            "db.create_batch('flow', 'flow_image', {}, '/tmp', 'flat', [{'mode': 't2i', 'prompt': 'a', 'count': 1}])\n")
    subprocess.run([sys.executable, "-c", seed], cwd=ROOT, env=env, check=True, timeout=60)
    for run in (1, 2):                                  # mở 2 lần: lần đầu có dữ liệu cũ, lần sau như mới
        p = subprocess.run([sys.executable, "-m", "videoai.main"], cwd=ROOT, env=env, timeout=120,
                           capture_output=True, text=True)
        out = p.stdout + p.stderr
        assert p.returncode == 0, out[-3000:]
        assert "Traceback" not in out, out[-3000:]
        log = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in (home / "logs").glob("*.log"))
        assert log.count("Khởi động xong") >= run, log[-2000:]
