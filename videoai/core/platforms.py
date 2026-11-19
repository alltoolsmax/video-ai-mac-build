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
    ready: bool = False           # đã hoàn thiện (hiện chỉ Google Flow); chưa xong thì menu ghi "sắp có"


T2I = Mode("t2i", "Văn bản → Ảnh")
I2I = Mode("i2i", "Tham chiếu", needs_ref=True)
T2V = Mode("t2v", "Văn bản → Video")
I2V = Mode("i2v", "Ảnh - Video", needs_ref=True, frames=True)
COMPOSE = Mode("compose", "Tham chiếu", needs_ref=True)

PAGES: list[PageDef] = [
    PageDef("flow_image", "Tạo ảnh Flow", "flow", "image", 0, "image",
            "https://flow.google.com/", [T2I, I2I],
            ["Nano Banana 2.1", "Nano Banana Pro", "Nano Banana 2 Lite"], RATIOS_IMG,
            {"quality": ["1K", "2K", "4K"]}, ready=True),
    PageDef("flow_video", "Tạo Video Flow", "flow", "video", 1, "video",
            "https://flow.google.com/", [T2V, I2V, COMPOSE],
            ["Omni 1.2 Flash", "Veo 3.1 - Lite"], RATIOS_VID,      # từ 5/12/2026 Flow chỉ còn 2 model video này
            {"quality": ["720p", "1080p", "4K"],
             # thời lượng chỉnh được theo từng model (đọc từ Flow 11/2026); model khác dùng thời lượng cố định của model
             "durations": {"Omni 1.2 Flash": (3, 15, 8)}}, ready=True),
    PageDef("gpics", "Tạo ảnh Pics", "gpics", "camera", 3, "image",
            "https://labs.google/fx/tools/whisk", [T2I, I2I], ["Mặc định"], RATIOS_IMG),
    PageDef("gvids", "Tạo Video Vids", "gvids", "film", 2, "video",
            "https://vids.google.com", [T2V, I2V], ["Veo 3.1"], RATIOS_VID),
    PageDef("dreamina", "Tạo Video Dreamina", "dreamina", "clapper", 4, "video",
            "https://dreamina.capcut.com/ai-tool/home", [T2V, I2V], ["Seedance 1.0 Pro", "Seedance 1.0 Lite"], RATIOS_VID),
    PageDef("gpt_image", "Tạo ảnh GPT", "gpt", "sparkle", 5, "image",
            "https://chatgpt.com/images", [T2I, I2I], ["GPT Image"], RATIOS_IMG),
    PageDef("meta_muse", "Tạo Video Muse", "muse", "stars", 6, "video",
            "https://www.meta.ai/media", [T2V, I2V], ["Mặc định"], RATIOS_VID),
    PageDef("meta_vibes", "Tạo Video Meta Vibes", "vibes", "palette", 7, "video",
            "https://www.meta.ai/vibes", [T2V, I2V], ["Mặc định"], RATIOS_VID),
    PageDef("grok_image", "Tạo ảnh Grok", "grok", "bot", 8, "image",
            "https://grok.com/imagine", [T2I, I2I], ["Grok Imagine"], RATIOS_IMG),
    PageDef("grok_video", "Tạo Video Grok", "grok", "bot", 8, "video",
            "https://grok.com/imagine", [T2V, I2V], ["Grok Imagine"], RATIOS_VID),
]

PAGE_BY_KEY = {p.key: p for p in PAGES}

PLATFORM_LABELS = {
    "flow": "Google Flow", "gvids": "Google Vids", "gpics": "Google Pics", "dreamina": "Dreamina",
    "gpt": "ChatGPT (GPT Image)", "muse": "Meta AI (Muse)", "vibes": "Meta AI (Vibes)", "grok": "Grok",
}

# Mục công cụ (không phải trang tạo)
TOOL_ITEMS = [
    ("refs", "Kho ảnh tham chiếu", "library", 0),
    ("workflow", "Workflow", "nodes", 1),
    ("webhook", "Webhook API", "link", 2),      # ẩn mặc định (Cài Đặt › Chung › Hiện Webhook API)
    ("upscale", "Nâng Cấp Ảnh", "zoom", 3),
    ("video_tools", "Công Cụ Video", "scissors", 4),
]
FOOTER_ITEMS = [
    ("settings", "Cài Đặt", "gear", 8),
    ("eula", "Thông tin bản quyền", "shield", 3),
    ("logs", "Log Chi Tiết", "list", 8),
]
