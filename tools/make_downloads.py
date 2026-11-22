"""Chuẩn bị thư mục tải lên mrhuynh.net/downloads/ (cPanel File Manager).

Windows:  python tools/make_downloads.py [bộ cài Setup .exe]
  → dist/downloads/ = video_ai_mrhuynh_win.zip (KHÁCH TẢI: bên trong 1 tệp video_ai_mrhuynh_win.exe)
                    + video_ai_mrhuynh_win.exe (TỰ CẬP NHẬT – không đổi) + index.html + .htaccess
    và dist/downloads-upload.zip (tải lên rồi bấm Extract trong cPanel).
macOS:    python tools/make_downloads.py --mac <tệp .dmg> [<tệp .dmg chip khác>]
  (mỗi tệp có thể ghi kèm chip: apple=<.dmg> intel=<.dmg>; không ghi thì đoán theo tên tệp / máy đang chạy)
  → dist/downloads-mac/ = video_ai_mrhuynh_mac.zip (KHÁCH TẢI: bên trong video_ai_mrhuynh_mac_apple.dmg cho chip
    Apple M + video_ai_mrhuynh_mac_intel.dmg cho Mac Intel) + video_ai_mrhuynh_mac.dmg (TỰ CẬP NHẬT – không đổi;
    ưu tiên bản Intel vì chạy được trên mọi máy Mac) + mac.json
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
MAC_NAME = "video_ai_mrhuynh_mac.dmg"           # tự cập nhật
WIN_ZIP = "video_ai_mrhuynh_win.zip"            # khách tải
MAC_ZIP = "video_ai_mrhuynh_mac.zip"
MAC_ARCH_NAME = {"apple": "video_ai_mrhuynh_mac_apple.dmg", "intel": "video_ai_mrhuynh_mac_intel.dmg"}


def _arch_of(spec: str) -> tuple[str, Path]:
    if "=" in spec and spec.split("=", 1)[0] in MAC_ARCH_NAME:
        a, p_ = spec.split("=", 1)
        return a, Path(p_)
    p_ = Path(spec)
    n = p_.name.lower()
    if "intel" in n or "x86" in n:
        return "intel", p_
    if "arm64" in n or "apple" in n:
        return "apple", p_
    return ("intel" if platform.machine() in ("x86_64", "AMD64") else "apple"), p_


def _ver() -> str:
    return re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "videoai/core/paths.py").read_text(encoding="utf-8")).group(1)


def main_mac(*dmgs, arch: str | None = None) -> Path:
    items: dict[str, Path] = {}
    for d in dmgs:
        a_, p_ = _arch_of(str(d))
        if arch and len(dmgs) == 1:
            a_ = "intel" if arch in ("x86_64", "intel") else "apple"
        if not p_.exists():
            sys.exit(f"Không thấy {p_}")
        if not p_.read_bytes()[-512:].startswith(b"koly"):
            sys.exit(f"Tệp {p_.name} không phải ảnh đĩa macOS (.dmg).")
        items[a_] = p_
    if not items:
        sys.exit("Chưa có tệp .dmg")
    ver = _ver()
    out = ROOT / "dist" / "downloads-mac"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    upd = items.get("intel") or items["apple"]          # tự cập nhật: bản Intel chạy được cả máy chip Apple
    shutil.copy(upd, out / MAC_NAME)
    with zipfile.ZipFile(out / MAC_ZIP, "w", zipfile.ZIP_STORED) as zf:      # .dmg đã nén sẵn
        for a_ in ("apple", "intel"):
            if a_ in items:
                zf.write(items[a_], MAC_ARCH_NAME[a_])
    data = (out / MAC_NAME).read_bytes()
    info = {"version": ver, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "arch": "x86_64" if upd is items.get("intel") else "arm64", "archs": sorted(items),
            "zip": MAC_ZIP, "zip_size": (out / MAC_ZIP).stat().st_size,
            "date": date.today().strftime("%d/%m/%Y"), "file": MAC_NAME}
    (out / "mac.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    z = ROOT / "dist" / "downloads-mac-upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in (MAC_ZIP, MAC_NAME, "mac.json"):
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
    with zipfile.ZipFile(out / WIN_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:   # khách tải: zip chứa 1 tệp exe
        zf.write(setup, NAME)
    shutil.copy(tpl / ".htaccess", out / ".htaccess")
    html = (tpl / "index.template.html").read_text(encoding="utf-8")
    html = (html.replace("{VERSION}", ver).replace("{SIZE_MB}", f"{(out / WIN_ZIP).stat().st_size / 1e6:.0f}")
            .replace("{DATE}", date.today().strftime("%d/%m/%Y")))
    (out / "index.html").write_text(html, encoding="utf-8")
    z = ROOT / "dist" / "downloads-upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in (WIN_ZIP, NAME, "index.html", ".htaccess"):
            zf.write(out / f, f)
    print(f"Đã tạo {out} và {z}")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--mac":
        main_mac(*sys.argv[2:])
    else:
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
