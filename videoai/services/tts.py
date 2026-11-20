"""Giọng nói AI tiếng Việt bằng VieNeu-TTS v3 Turbo (mã nguồn mở, Apache-2.0, tác giả Phạm Nguyễn Ngọc Bảo).

- Chạy trên máy người dùng, CPU qua ONNX Runtime (không cần GPU, không cần torch), âm thanh 48 kHz.
- Lần đầu tự tải mô hình từ Hugging Face (pnnbao-ump/VieNeu-TTS-v3-Turbo) vào thư mục dữ liệu của tools.
- Giọng mẫu (đọc từ gói vieneu, không cần mạng): tên, giới tính, vùng miền.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from ..core import log
from ..core.paths import data_dir

L = log.get("tts")
MODEL_NAME = "VieNeu-TTS v3 Turbo"
MODEL_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"

_tts = None
_lock = threading.Lock()


def models_dir() -> Path:
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("vieneu") is not None and importlib.util.find_spec("onnxruntime") is not None
    except Exception:
        return False


def voices() -> list[tuple[str, str]]:
    """[(nhãn hiển thị, tên giọng)] – đọc trực tiếp tệp giọng mẫu trong gói vieneu (không tải mô hình)."""
    try:
        import importlib.util
        spec = importlib.util.find_spec("vieneu")
        f = Path(spec.origin).parent / "assets" / "voices_v3_turbo.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        pres = d.get("presets", d)
        items = sorted(pres.items(), key=lambda kv: (kv[1].get("featured") is None, kv[1].get("featured") or 0))
        out = []
        for name, v in items:
            desc = v.get("description") or " · ".join(x for x in (v.get("gender"), v.get("region")) if x)
            out.append((f"{'⭐ ' if v.get('featured') else ''}{name} — {desc}" if desc else name, name))
        return out
    except Exception as e:
        L.info("Không đọc được danh sách giọng VieNeu: %s", e)
        return []


def _load(on_status=None):
    global _tts
    if _tts is not None:
        return _tts
    if not available():
        raise RuntimeError(f"Bản cài này chưa có {MODEL_NAME} (gói vieneu + onnxruntime). Build lại bằng 'build Windows.bat'.")
    os.environ.setdefault("HF_HOME", str(models_dir()))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    say = on_status or (lambda m: None)
    say(f"Đang nạp {MODEL_NAME} (lần đầu tự tải mô hình ~vài trăm MB, cần mạng)…")
    from vieneu import Vieneu
    t0 = time.time()
    _tts = Vieneu(mode="v3turbo", backend="onnx", device="cpu")
    L.info("Nạp %s xong sau %.1fs", MODEL_NAME, time.time() - t0)
    return _tts


def clean_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", (text or "").replace("\r", "")).strip()


def synthesize(text: str, voice: str | None, out_path: str, on_status=None) -> str:
    """Tạo giọng nói → tệp WAV 48 kHz. Chạy ở luồng nền (mất vài giây đến vài chục giây tùy độ dài và CPU)."""
    text = clean_text(text)
    if not text:
        raise RuntimeError("Nhập nội dung cần đọc.")
    with _lock:                                     # mô hình dùng chung: mỗi lần một yêu cầu
        try:
            tts = _load(on_status)
        except RuntimeError:
            raise
        except Exception as e:
            L.exception("Nạp VieNeu-TTS lỗi")
            if re.search(r"(Hub|connect|resolve|timed out|SSL|HTTP|offline|LocalEntryNotFound)", f"{type(e).__name__} {e}", re.I):
                raise RuntimeError(f"Không tải được mô hình {MODEL_NAME} (lần đầu cần mạng để tải từ Hugging Face). "
                                   "Kiểm tra kết nối Internet rồi thử lại.") from e
            raise RuntimeError(f"Không nạp được {MODEL_NAME}: {e}") from e
        (on_status or (lambda m: None))("Đang tạo giọng nói…")
        audio = tts.infer(text, voice=voice or None)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        tts.save(audio, out_path)
    return out_path


def output_path(text: str, voice: str | None) -> str:
    d = data_dir() / "tts"
    d.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", clean_text(text)[:28], flags=re.U).strip("_") or "giong_noi"
    return str(d / f"{time.strftime('%Y%m%d_%H%M%S')}_{(voice or 'mac_dinh').replace(' ', '')}_{slug}.wav")
