"""Danh sách trang tạo nội dung (mỗi mục menu) và tùy chọn của chúng.

URL và tên model có thể đổi theo thời gian: người dùng sửa được trong Cài Đặt › Nền tảng,
và adapter đọc selector từ adapters/selectors/<platform>.json (sửa được, không cần build lại)."""
from __future__ import annotations

from dataclasses import dataclass, field

RATIOS_IMG = ["16:9 Ngang", "9:16 Dọc", "1:1 Vuông", "4:3 Ngang", "3:4 Dọc"]  # Flow có đủ 5 tỷ lệ
RATIOS_VID = ["16:9 Ngang", "9:16 Dọc"]


@dataclass
class Mode:
    key: str           # t2i, i2i, t2v, i2v, compose
    label: str
    needs_ref: bool = False      # bắt buộc có ảnh tham chiếu
    frames: bool = False         # có ô khung đầu / khung cuối


@dataclass
class PageDef:
    key: str
    label: str
    platform: str
    icon: str
    tile: int                     # chỉ số gradient icon trong tokens
    kind: str                     # image | video
    url: str
    modes: list[Mode]
    models: list[str]
    ratios: list[str]
    extra: dict = field(default_factory=dict)   # resolutions, durations...
    max_count: int = 4


T2I = Mode("t2i", "Văn bản → Ảnh")
I2I = Mode("i2i", "Ảnh → Ảnh", needs_ref=True)
T2V = Mode("t2v", "Văn bản → Video")
I2V = Mode("i2v", "Ảnh → Video", needs_ref=True, frames=True)
COMPOSE = Mode("compose", "Thành phần (ảnh tham chiếu)", needs_ref=True)

PAGES: list[PageDef] = [
    PageDef("flow_image", "Flow Ảnh", "flow", "image", 0, "image",
            "https://flow.google.com/", [T2I, I2I],
            ["Nano Banana 2.1", "Nano Banana Pro", "Nano Banana 2 Lite"], RATIOS_IMG),
    PageDef("flow_video", "Flow Video", "flow", "video", 1, "video",
            "https://flow.google.com/", [T2V, I2V, COMPOSE],
            ["Omni 1.2 Flash", "Omni 1.1 Flash", "Veo 3.1 - Lite", "Veo 3.1 - Fast", "Veo 3.1 - Quality"], RATIOS_VID,
            {"resolutions": ["720p", "360p", "1080p"],
             "durations": ["Mặc định", "4 giây", "6 giây", "8 giây", "10 giây", "12 giây", "15 giây"]}),
    PageDef("gvids", "Google Vids", "gvids", "film", 2, "video",
            "https://vids.google.com", [T2V, I2V],
            ["Veo 3.1"], RATIOS_VID),
    PageDef("gpics", "Google Pics", "gpics", "camera", 3, "image",
            "https://labs.google/fx/tools/whisk", [T2I, I2I],
            ["Mặc định"], RATIOS_IMG),
    PageDef("dreamina", "Dreamina", "dreamina", "clapper", 4, "image",
            "https://dreamina.capcut.com/ai-tool/home", [T2I, I2I, T2V, I2V],
            ["Seedream 4.0", "Seedance 1.0 Pro", "Seedance 1.0 Lite"], RATIOS_IMG,
            {"durations": ["5s", "10s"]}),
    PageDef("gpt_image", "GPT Image", "gpt", "sparkle", 5, "image",
            "https://chatgpt.com/images", [T2I, I2I],
            ["GPT Image"], RATIOS_IMG),
    PageDef("meta_muse", "Meta Muse", "muse", "stars", 6, "image",
            "https://www.meta.ai/media", [T2I, I2I],
            ["Mặc định"], RATIOS_IMG),
    PageDef("meta_vibes", "Meta Vibes", "vibes", "palette", 7, "video",
            "https://www.meta.ai/vibes", [T2V, I2V],
            ["Mặc định"], RATIOS_VID),
    PageDef("grok", "Grok Imagine", "grok", "bot", 8, "image",
            "https://grok.com/imagine", [T2I, I2I, T2V, I2V],
            ["Grok Imagine"], RATIOS_IMG, {"durations": ["6s", "10s"]}),
]

PAGE_BY_KEY = {p.key: p for p in PAGES}

PLATFORM_LABELS = {
    "flow": "Google Flow", "gvids": "Google Vids", "gpics": "Google Pics", "dreamina": "Dreamina",
    "gpt": "ChatGPT (GPT Image)", "muse": "Meta AI (Muse)", "vibes": "Meta AI (Vibes)", "grok": "Grok",
}

# Mục công cụ (không phải trang tạo)
TOOL_ITEMS = [
    ("characters", "Nhân Vật", "users", 0),
    ("workflow", "Workflow", "nodes", 1),
    ("webhook", "Webhook API", "link", 2),
    ("upscale", "Nâng Cấp Ảnh", "zoom", 3),
    ("video_tools", "Công Cụ Video", "scissors", 4),
]
FOOTER_ITEMS = [
    ("settings", "Cài Đặt", "gear", 8),
    ("logs", "Log Chi Tiết", "list", 8),
]
