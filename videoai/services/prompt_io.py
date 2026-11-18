"""Đọc / ghi danh sách prompt: TXT, CSV, Excel (.xlsx)."""
from __future__ import annotations

import csv
from pathlib import Path


def split_prompts(text: str, mode: str = "line") -> list[str]:
    """mode='line': mỗi dòng một prompt. mode='block': các prompt cách nhau bằng dòng trống."""
    text = text.replace("\r\n", "\n")
    if mode == "block":
        parts = [p.strip() for p in text.split("\n\n")]
    else:
        parts = [p.strip() for p in text.split("\n")]
    return [p for p in parts if p]


def load_file(path: str | Path) -> list[str]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(p, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        # tìm cột tên "prompt" nếu có, không thì lấy cột đầu tiên có chữ
        header = [str(c or "").strip().lower() for c in rows[0]]
        col = next((i for i, h in enumerate(header) if h in ("prompt", "prompts", "nội dung", "noi dung")), None)
        start = 1 if col is not None else 0
        col = col or 0
        return [str(r[col]).strip() for r in rows[start:] if r and len(r) > col and r[col] and str(r[col]).strip()]
    if ext == ".csv":
        with open(p, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        if not rows:
            return []
        header = [h.strip().lower() for h in rows[0]]
        if "prompt" in header:
            i = header.index("prompt")
            return [r[i].strip() for r in rows[1:] if len(r) > i and r[i].strip()]
        return [r[0].strip() for r in rows if r and r[0].strip()]
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    mode = "block" if "\n\n" in text.replace("\r\n", "\n") and text.count("\n\n") >= 2 else "line"
    return split_prompts(text, mode)


def save_txt(prompts: list[str], path: str | Path) -> None:
    Path(path).write_text("\n".join(prompts), encoding="utf-8")
