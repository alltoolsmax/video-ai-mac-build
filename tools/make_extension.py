#!/usr/bin/env python3
"""Đóng gói Tiện ích Chrome thành ZIP: python tools/make_extension.py [thư_mục_đích]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from videoai.services import ext_package  # noqa: E402


def main():
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    z = ext_package.make_zip(dest)
    print("Đã tạo:", z, f"({z.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
