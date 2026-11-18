"""Đọc / ghi phụ đề SRT."""
from __future__ import annotations

import re

_T = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, l in enumerate(lines):
            m = _T.search(l)
            if m:
                g = m.groups()
                cues.append({"start": _sec(*g[:4]), "end": _sec(*g[4:]), "text": "\n".join(lines[i + 1:]).strip()})
                break
    return cues


def fmt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(cues: list[dict]) -> str:
    return "\n\n".join(f"{i}\n{fmt(c['start'])} --> {fmt(c['end'])}\n{c['text']}" for i, c in enumerate(cues, 1)) + "\n"


def from_lines(lines: list[str], seconds_each: float) -> str:
    """Mỗi dòng một câu phụ đề, chia đều theo thời lượng mỗi cảnh."""
    return build_srt([{"start": i * seconds_each, "end": (i + 1) * seconds_each, "text": l}
                      for i, l in enumerate(lines) if l.strip()])
