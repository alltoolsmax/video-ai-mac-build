"""Xuất danh sách clip (+ nhạc, phụ đề SRT) thành một dự án nháp CapCut desktop.

CapCut không công bố định dạng; file này tạo cấu trúc tối thiểu (draft_content.json + draft_meta_info.json)
mà CapCut desktop đọc được ở các bản phổ biến. Nếu bản CapCut của bạn không mở được, dùng
'Xuất thư mục' (clip đánh số + SRT) rồi kéo vào CapCut.
Thư mục nháp mặc định: %LOCALAPPDATA%/CapCut/User Data/Projects/com.lveditor.draft
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .ffmpeg import duration, probe
from .srt import parse_srt

US = 1_000_000


def default_draft_root() -> Path:
    base = os.environ.get("LOCALAPPDATA", str(Path.home()))
    return Path(base) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _wh(path: str) -> tuple[int, int]:
    try:
        v = next(s for s in probe(path)["streams"] if s.get("codec_type") == "video")
        return int(v["width"]), int(v["height"])
    except Exception:
        return 1920, 1080


def export_folder(clips: list[str], out_dir: str, srt: str | None = None, music: str | None = None) -> Path:
    o = Path(out_dir)
    o.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(clips, 1):
        shutil.copy(c, o / f"{i:03d}_{Path(c).name}")
    if srt:
        shutil.copy(srt, o / Path(srt).name)
    if music:
        shutil.copy(music, o / ("music" + Path(music).suffix))
    return o


def export_draft(name: str, clips: list[str], srt: str | None = None, music: str | None = None,
                 root: str | None = None, canvas: tuple[int, int] = (1920, 1080)) -> Path:
    root_p = Path(root) if root else default_draft_root()
    draft = root_p / name
    k = 1
    while draft.exists():
        draft = root_p / f"{name}_{k}"
        k += 1
    media = draft / "media"
    media.mkdir(parents=True)

    videos, segs_v, audios, segs_a, texts, segs_t = [], [], [], [], [], []
    t = 0
    for c in clips:
        dst = media / Path(c).name
        shutil.copy(c, dst)
        d = int(duration(str(dst)) * US)
        w, h = _wh(str(dst))
        mid = _uid()
        videos.append({"id": mid, "type": "video", "path": str(dst).replace("\\", "/"), "duration": d,
                       "width": w, "height": h, "material_name": dst.name})
        segs_v.append({"id": _uid(), "material_id": mid, "source_timerange": {"start": 0, "duration": d},
                       "target_timerange": {"start": t, "duration": d}, "speed": 1.0, "volume": 1.0,
                       "visible": True, "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0},
                                                   "rotation": 0.0, "alpha": 1.0}})
        t += d
    total = t
    if music:
        dst = media / ("music" + Path(music).suffix)
        shutil.copy(music, dst)
        d = int(duration(str(dst)) * US)
        mid = _uid()
        audios.append({"id": mid, "type": "extract_music", "path": str(dst).replace("\\", "/"), "duration": d,
                       "name": dst.name})
        segs_a.append({"id": _uid(), "material_id": mid, "source_timerange": {"start": 0, "duration": min(d, total)},
                       "target_timerange": {"start": 0, "duration": min(d, total)}, "speed": 1.0, "volume": 0.4})
    if srt:
        for cue in parse_srt(Path(srt).read_text(encoding="utf-8-sig")):
            mid = _uid()
            texts.append({"id": mid, "type": "subtitle", "content": json.dumps({"text": cue["text"]}, ensure_ascii=False)})
            segs_t.append({"id": _uid(), "material_id": mid,
                           "target_timerange": {"start": int(cue["start"] * US), "duration": int((cue["end"] - cue["start"]) * US)}})

    tracks = [{"id": _uid(), "type": "video", "segments": segs_v}]
    if segs_a:
        tracks.append({"id": _uid(), "type": "audio", "segments": segs_a})
    if segs_t:
        tracks.append({"id": _uid(), "type": "text", "segments": segs_t})
    now_us = int(time.time() * US)
    content = {
        "id": _uid(), "name": draft.name, "duration": total, "fps": 30.0,
        "canvas_config": {"width": canvas[0], "height": canvas[1], "ratio": "original"},
        "materials": {"videos": videos, "audios": audios, "texts": texts},
        "tracks": tracks, "create_time": now_us // US, "update_time": now_us // US, "version": 360000,
        "platform": {"os": "windows", "app_source": "cc"},
    }
    meta = {
        "draft_id": _uid(), "draft_name": draft.name, "draft_fold_path": str(draft).replace("\\", "/"),
        "draft_root_path": str(root_p).replace("\\", "/"), "tm_duration": total,
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "draft_materials": [{"type": 0, "value": [{"file_Path": v["path"], "duration": v["duration"],
                                                   "width": v["width"], "height": v["height"]} for v in videos]}],
    }
    (draft / "draft_content.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (draft / "draft_info.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (draft / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return draft
