"""Gói phát hành Video AI (giống Voice AI).

Windows (build Windows.bat tự gọi):  python tools/make_downloads.py [bộ cài Setup .exe]
  → dist/downloads-upload.zip – tải lên mrhuynh.net/downloads/ rồi Extract (ghi đè). Chỉ gồm:
      video_ai_mrhuynh_win.exe   bộ cài – phần mềm TỰ CẬP NHẬT tải file này
      video_ai_mrhuynh_win.zip   cho khách tải lần đầu (bên trong 1 tệp .exe)
      video_win.json             phiên bản, SHA-256, dung lượng, ngày – trang quản trị + trang tải đọc file này
  (không có index.html / .htaccess: trang tải mrhuynh.net/downloads tự đọc video_win.json, không phải tải lại)

macOS (GitHub Actions tự gọi, anh không cần làm gì):
    python tools/make_downloads.py --mac apple=<arm64.dmg> intel=<intel.dmg>
  → dist/downloads-mac/ = các tệp đưa lên GitHub Releases với TÊN CỐ ĐỊNH:
      video_ai_mrhuynh_mac.zip           khách tải lần đầu (bên trong 2 bộ cài: chip Apple M + Intel)
                                         link cố định: github.com/alltoolsmax/video-ai-mac-build/releases/latest/download/video_ai_mrhuynh_mac.zip
      video_ai_mrhuynh_mac_apple.dmg / video_ai_mrhuynh_mac_intel.dmg   phần mềm Mac tự cập nhật (máy chủ chọn đúng chip)
      video_mac.json                     phiên bản + SHA-256 từng chip (máy chủ đọc)"""
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
WIN_ZIP = "video_ai_mrhuynh_win.zip"            # khách tải
WIN_JSON = "video_win.json"
MAC_ZIP = "video_ai_mrhuynh_mac.zip"
MAC_JSON = "video_mac.json"
MAC_ARCH_NAME = {"apple": "video_ai_mrhuynh_mac_apple.dmg", "intel": "video_ai_mrhuynh_mac_intel.dmg"}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
        with open(p_, "rb") as f:
            f.seek(max(0, p_.stat().st_size - 512))
            if not f.read().startswith(b"koly"):
                sys.exit(f"Tệp {p_.name} không phải ảnh đĩa macOS (.dmg).")
        items[a_] = p_
    if not items:
        sys.exit("Chưa có tệp .dmg")
    ver = _ver()
    out = ROOT / "dist" / "downloads-mac"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    info: dict = {"version": ver, "date": date.today().strftime("%d/%m/%Y"), "archs": sorted(items)}
    for a_, src in items.items():
        dst = out / MAC_ARCH_NAME[a_]
        shutil.copy(src, dst)
        info[a_] = {"file": MAC_ARCH_NAME[a_], "sha256": _sha(dst), "size": dst.stat().st_size}
    with zipfile.ZipFile(out / MAC_ZIP, "w", zipfile.ZIP_STORED) as zf:      # .dmg đã nén sẵn
        for a_ in ("apple", "intel"):
            if a_ in items:
                zf.write(out / MAC_ARCH_NAME[a_], MAC_ARCH_NAME[a_])
    info["zip"] = MAC_ZIP
    info["zip_size"] = (out / MAC_ZIP).stat().st_size
    (out / MAC_JSON).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã tạo {out}: " + ", ".join(sorted(p.name for p in out.iterdir())))
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
    shutil.copy(setup, out / NAME)
    with zipfile.ZipFile(out / WIN_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:   # khách tải: zip chứa 1 tệp exe
        zf.write(setup, NAME)
    info = {"version": ver, "sha256": _sha(out / NAME), "size": (out / NAME).stat().st_size,
            "zip_size": (out / WIN_ZIP).stat().st_size, "date": date.today().strftime("%d/%m/%Y")}
    (out / WIN_JSON).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    z = ROOT / "dist" / "downloads-upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
        for f in (NAME, WIN_ZIP, WIN_JSON):
            zf.write(out / f, f)
    print(f"Đã tạo {z}")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--mac":
        main_mac(*sys.argv[2:])
    else:
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
