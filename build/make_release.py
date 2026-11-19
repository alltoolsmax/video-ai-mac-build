"""Tạo latest.json cho bản cài mới:  python build/make_release.py https://.../download/v{version}/
In ra nội dung và lưu dist/latest.json. Tải bộ cài + latest.json lên nơi lưu trữ (vd. GitHub Releases)."""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ver = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "videoai/core/paths.py").read_text(encoding="utf-8")).group(1)
setup = ROOT / "dist" / f"VideoAI-MrHuynh-Setup-{ver}.exe"
if not setup.exists():
    sys.exit(f"Không thấy {setup}. Hãy build bộ cài trước (build Windows.bat, cần Inno Setup).")
base = (sys.argv[1] if len(sys.argv) > 1 else "").replace("{version}", ver)
if base and not base.endswith("/"):
    base += "/"
notes = (ROOT / "CHANGELOG.txt").read_text(encoding="utf-8").split("\n\n")[0] if (ROOT / "CHANGELOG.txt").exists() else ""
info = {"version": ver, "url": base + setup.name, "sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
        "size": setup.stat().st_size, "notes": notes, "mandatory": False}
(ROOT / "dist" / "latest.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(info, ensure_ascii=False, indent=2))
