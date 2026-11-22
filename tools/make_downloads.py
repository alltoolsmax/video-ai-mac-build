"""Chuẩn bị thư mục tải lên mrhuynh.net/downloads/ (cPanel File Manager):
dist/downloads/ = video_ai_mrhuynh_win.exe (bộ cài Setup, tên cố định) + index.html (trang tải + hướng dẫn) + .htaccess
và dist/downloads-upload.zip (tải lên rồi bấm Extract trong cPanel).
Dùng:  python tools/make_downloads.py [đường dẫn bộ cài Setup]
macOS: python tools/make_downloads.py --mac <tệp .dmg>
  → dist/downloads-mac/ = video_ai_mrhuynh_mac.dmg + mac.json (phiên bản, dung lượng, chip, SHA-256)
    và dist/downloads-mac-upload.zip (KHÔNG có index.html: trang tải của bản Windows tự đọc mac.json)."""
import hashlib
import json
import platform
import re
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "video_ai_mrhuynh_win.exe"
MAC_NAME = "video_ai_mrhuynh_mac.dmg"


def _ver() -> str:
    return re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "videoai/core/paths.py").read_text(encoding="utf-8")).group(1)


def main_mac(dmg: Path, arch: str | None = None) -> Path:
    dmg = Path(dmg)
    if not dmg.exists():
        sys.exit(f"Không thấy {dmg}")
    data = dmg.read_bytes()
    if not data[-512:].startswith(b"koly"):
        sys.exit("Tệp này không phải ảnh đĩa macOS (.dmg).")
    ver = _ver()
    out = ROOT / "dist" / "downloads-mac"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(dmg, out / MAC_NAME)
    arch = arch or platform.machine() or "arm64"
    info = {"version": ver, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "arch": arch,
            "date": date.today().strftime("%d/%m/%Y"), "file": MAC_NAME}
    (out / "mac.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    z = ROOT / "dist" / "downloads-mac-upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:      # .dmg đã nén sẵn
        for f in (MAC_NAME, "mac.json"):
            zf.write(out / f, f)
    print(f"Đã tạo {out} và {z}")
    return out


def main(setup: Path | None = None) -> Path:
    ver = _ver()
    setup = Path(setup) if setup else ROOT / "dist" / f"VideoAI-MrHuynh-Setup-{ver}.exe"
    if not setup.exists():
        sys.exit(f"Không thấy bộ cài {setup}")
    if b"Inno Setup" not in setup.read_bytes():
        sys.exit("Tệp này không phải bộ cài Setup (Inno Setup) – không đưa lên trang tải.")
    out = ROOT / "dist" / "downloads"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    tpl = ROOT / "hosting" / "downloads"
    shutil.copy(setup, out / NAME)
    shutil.copy(tpl / ".htaccess", out / ".htaccess")
    html = (tpl / "index.template.html").read_text(encoding="utf-8")
    html = (html.replace("{VERSION}", ver).replace("{SIZE_MB}", f"{setup.stat().st_size / 1e6:.0f}")
            .replace("{DATE}", date.today().strftime("%d/%m/%Y")))
    (out / "index.html").write_text(html, encoding="utf-8")
    z = ROOT / "dist" / "downloads-upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in (NAME, "index.html", ".htaccess"):
            zf.write(out / f, f)
    print(f"Đã tạo {out} và {z}")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--mac":
        main_mac(Path(sys.argv[2]))
    else:
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
