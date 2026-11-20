"""Mô hình dự án dựng video (kiểu CapCut): track video chính (nối liền), track chữ, track nhạc, track lồng tiếng.

Thời gian tính bằng giây. Clip video có điểm vào/ra trên tệp gốc (in_s/out_s) và tốc độ;
thời lượng trên timeline = (out_s - in_s) / speed.
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
AUD_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
FILTERS = {"Gốc": "", "Ấm": "colorbalance=rs=.08:gs=.02:bs=-.08",
           "Lạnh": "colorbalance=rs=-.06:bs=.1", "Film": "eq=contrast=1.08:saturation=0.85,curves=preset=vintage",
           "Đen trắng": "hue=s=0", "Rực rỡ": "eq=saturation=1.35:contrast=1.05"}


def _id() -> str:
    return uuid.uuid4().hex[:10]


def media_kind(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMG_EXT:
        return "image"
    if ext in AUD_EXT:
        return "audio"
    return "video"


@dataclass
class Clip:
    src: str
    kind: str = "video"          # video | image
    in_s: float = 0.0
    out_s: float = 3.0
    src_dur: float = 3.0         # thời lượng tệp gốc (ảnh: không giới hạn)
    speed: float = 1.0
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    filter: str = "Gốc"
    scale: float = 1.0           # 1 = vừa khung
    has_audio: bool = True
    id: str = field(default_factory=_id)

    @property
    def dur(self) -> float:
        return max(0.05, (self.out_s - self.in_s) / max(0.05, self.speed))


@dataclass
class TextItem:
    text: str = "Nhập chữ"
    start: float = 0.0
    dur: float = 3.0
    size: int = 56
    color: str = "#ffffff"
    pos: str = "Dưới"            # Trên | Giữa | Dưới
    box: bool = True
    id: str = field(default_factory=_id)


@dataclass
class AudioItem:
    src: str
    track: str = "music"         # music | voice
    start: float = 0.0
    in_s: float = 0.0
    out_s: float = 10.0
    src_dur: float = 10.0
    volume: float = 0.6
    fade_in: float = 0.0
    fade_out: float = 0.0
    id: str = field(default_factory=_id)

    @property
    def dur(self) -> float:
        return max(0.05, self.out_s - self.in_s)


@dataclass
class Project:
    name: str = "Dự án mới"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    auto_canvas: bool = True     # khung hình tự theo tỷ lệ video / ảnh đầu tiên đưa vào timeline
    clips: list[Clip] = field(default_factory=list)
    texts: list[TextItem] = field(default_factory=list)
    audios: list[AudioItem] = field(default_factory=list)
    media: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ thời gian
    @property
    def duration(self) -> float:
        end = sum(c.dur for c in self.clips)
        for t in self.texts:
            end = max(end, t.start + t.dur)
        for a in self.audios:
            end = max(end, a.start + a.dur)
        return end

    @property
    def video_duration(self) -> float:
        return sum(c.dur for c in self.clips)

    def clip_starts(self) -> list[float]:
        out, t = [], 0.0
        for c in self.clips:
            out.append(t)
            t += c.dur
        return out

    def clip_at(self, t: float) -> tuple[int, float] | None:
        """(chỉ số clip, thời điểm trong tệp gốc) tại thời điểm t trên timeline."""
        acc = 0.0
        for i, c in enumerate(self.clips):
            if acc <= t < acc + c.dur or (i == len(self.clips) - 1 and abs(t - (acc + c.dur)) < 1e-6):
                return i, c.in_s + (t - acc) * c.speed
            acc += c.dur
        return None

    def find(self, item_id: str):
        for lst in (self.clips, self.texts, self.audios):
            for x in lst:
                if x.id == item_id:
                    return x
        return None

    # ------------------------------------------------------------ thao tác
    def split(self, t: float, item_id: str | None = None) -> bool:
        """Cắt đôi clip (hoặc chữ / âm thanh đang chọn) tại thời điểm t."""
        target = self.find(item_id) if item_id else None
        if isinstance(target, TextItem) and target.start < t < target.start + target.dur:
            if True:
                b = copy.deepcopy(target)
                b.id = _id()
                b.start, b.dur = t, target.start + target.dur - t
                target.dur = t - target.start
                self.texts.insert(self.texts.index(target) + 1, b)
                return True
            return False
        if isinstance(target, AudioItem) and target.start < t < target.start + target.dur:
            if True:
                b = copy.deepcopy(target)
                b.id = _id()
                cut = target.in_s + (t - target.start)
                b.start, b.in_s = t, cut
                target.out_s = cut
                self.audios.insert(self.audios.index(target) + 1, b)
                return True
            return False
        hit = self.clip_at(t)
        if not hit:
            return False
        i, src_t = hit
        c = self.clips[i]
        if src_t - c.in_s < 0.05 or c.out_s - src_t < 0.05:
            return False
        b = copy.deepcopy(c)
        b.id = _id()
        b.in_s = src_t
        c.out_s = src_t
        b.fade_in = 0.0
        c.fade_out = 0.0
        self.clips.insert(i + 1, b)
        return True

    def edit_points(self) -> list[float]:
        """Các điểm chỉnh sửa (đầu / cuối mỗi clip, chữ, âm thanh) – phím ↑ / ↓ nhảy giữa các điểm này."""
        pts = {0.0, round(self.duration, 3)}
        for t in self.clip_starts() + [self.video_duration]:
            pts.add(round(t, 3))
        for x in self.texts + self.audios:
            pts.add(round(x.start, 3))
            pts.add(round(x.start + x.dur, 3))
        return sorted(pts)

    def trim(self, t: float, item_id: str | None, side: str) -> bool:
        """Kiểu CapCut: Q = xóa phần BÊN TRÁI kim phát, W = xóa phần BÊN PHẢI kim phát của mục đang chọn
        (không chọn gì: clip dưới kim phát). Clip phía sau tự dồn lại."""
        target = self.find(item_id) if item_id else None
        if isinstance(target, TextItem):
            if not target.start < t < target.start + target.dur:
                return False
            if side == "left":
                target.dur -= t - target.start
                target.start = t
            else:
                target.dur = t - target.start
            return True
        if isinstance(target, AudioItem):
            if not target.start < t < target.start + target.dur:
                return False
            if side == "left":
                target.in_s += t - target.start
                target.start = t
            else:
                target.out_s = target.in_s + (t - target.start)
            return True
        hit = self.clip_at(t)
        if not hit:
            return False
        i, src_t = hit
        c = self.clips[i]
        if isinstance(target, Clip) and target is not c:
            return False
        if src_t - c.in_s < 0.05 or c.out_s - src_t < 0.05:
            return False
        if side == "left":
            c.in_s = src_t
        else:
            c.out_s = src_t
        return True

    def delete(self, item_id: str) -> bool:
        for lst in (self.clips, self.texts, self.audios):
            for x in list(lst):
                if x.id == item_id:
                    lst.remove(x)
                    return True
        return False

    def detach_audio(self, clip_id: str) -> AudioItem | None:
        c = self.find(clip_id)
        if not isinstance(c, Clip) or c.kind != "video" or not c.has_audio:
            return None
        start = self.clip_starts()[self.clips.index(c)]
        a = AudioItem(src=c.src, track="voice", start=start, in_s=c.in_s, out_s=c.out_s, src_dur=c.src_dur, volume=c.volume)
        c.volume = 0.0
        self.audios.append(a)
        return a

    # ------------------------------------------------------------ lưu / mở
    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "Project":
        p = Project(**{k: v for k, v in d.items() if k in ("name", "width", "height", "fps", "media", "auto_canvas")})
        p.clips = [Clip(**c) for c in d.get("clips", [])]
        p.texts = [TextItem(**t) for t in d.get("texts", [])]
        p.audios = [AudioItem(**a) for a in d.get("audios", [])]
        return p

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def load(path: str) -> "Project":
        return Project.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


class History:
    """Hoàn tác / làm lại bằng ảnh chụp trạng thái dự án."""

    def __init__(self, limit: int = 80):
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.limit = limit

    def push(self, p: Project):
        self.undo_stack.append(copy.deepcopy(p.to_json()))
        self.undo_stack = self.undo_stack[-self.limit:]
        self.redo_stack.clear()

    def undo(self, p: Project) -> Project | None:
        if not self.undo_stack:
            return None
        self.redo_stack.append(copy.deepcopy(p.to_json()))
        return Project.from_json(self.undo_stack.pop())

    def redo(self, p: Project) -> Project | None:
        if not self.redo_stack:
            return None
        self.undo_stack.append(copy.deepcopy(p.to_json()))
        return Project.from_json(self.redo_stack.pop())
