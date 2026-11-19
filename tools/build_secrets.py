"""Giữ các file riêng của người bán NGOÀI thư mục mã nguồn (người dùng hay xóa cả thư mục cũ khi có mã mới).

Nơi lưu: %APPDATA%\\VideoAI-MrHuynh-build  (Windows)  ·  ~/.videoai-build  (máy khác)
- license-server/.signing_key.jwk   khóa ký (BÍ MẬT)
- hosting/.hosting_state.json       tên miền + mật khẩu quản trị
- hosting/video_seed.hex            seed cho config.php trên hosting (BÍ MẬT)
- videoai/license_config.json       địa chỉ máy chủ + khóa công khai (gắn vào phần mềm)
restore(): chép từ nơi lưu vào thư mục mã nguồn nếu thư mục mã nguồn đang thiếu.
backup():  chép từ thư mục mã nguồn ra nơi lưu (chỉ khi file có nội dung).
"""
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["license-server/.signing_key.jwk", "hosting/.hosting_state.json", "hosting/video_seed.hex",
         "videoai/license_config.json"]


def store() -> Path:
    base = os.environ.get("VIDEOAI_BUILD_STORE")
    if base:
        d = Path(base)
    elif os.name == "nt" and os.environ.get("APPDATA"):
        d = Path(os.environ["APPDATA"]) / "VideoAI-MrHuynh-build"
    else:
        d = Path.home() / ".videoai-build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _complete_cfg(p: Path) -> bool:
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
        return bool(c.get("server_url") and c.get("public_key"))
    except Exception:
        return False


def restore() -> list[str]:
    done = []
    for rel in FILES:
        src, dst = store() / rel, ROOT / rel
        if not src.exists():
            continue
        if rel.endswith("license_config.json"):
            if _complete_cfg(dst) or not _complete_cfg(src):
                continue
        elif dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        done.append(rel)
    return done


def backup() -> list[str]:
    done = []
    for rel in FILES:
        src, dst = ROOT / rel, store() / rel
        if not src.exists() or src.stat().st_size == 0:
            continue
        if rel.endswith("license_config.json") and not _complete_cfg(src):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        done.append(rel)
    return done


if __name__ == "__main__":
    print("Restore:", restore() or "-")
    print("Backup :", backup() or "-")
    print("Noi luu:", store())
