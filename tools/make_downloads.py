"""Chuẩn bị thư mục tải lên mrhuynh.net/downloads/ (cPanel File Manager):
dist/downloads/ = video_ai_mrhuynh.exe (bộ cài Setup, tên cố định) + index.html (trang tải + hướng dẫn) + .htaccess
và dist/downloads-upload.zip (tải lên rồi bấm Extract trong cPanel).
Dùng:  python tools/make_downloads.py [đường dẫn bộ cài Setup]"""
import re
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "video_ai_mrhuynh.exe"


def main(setup: Path | None = None) -> Path:
    ver = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "videoai/core/paths.py").read_text(encoding="utf-8")).group(1)
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
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
