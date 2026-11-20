"""Danh sách trang tạo nội dung (mỗi mục menu) và tùy chọn của chúng.

URL và tên model có thể đổi theo thời gian: người dùng sửa được trong Cài Đặt › Nền tảng,
và adapter đọc selector từ adapters/selectors/<platform>.json (sửa được, không cần build lại)."""
from __future__ import annotations

from dataclasses import dataclass, field

RATIOS_IMG = ["16:9 Ngang", "9:16 Dọc", "1:1 Vuông", "4:3 Ngang", "3:4 Dọc"]  # Flow có đủ 5 tỷ lệ
RATIOS_VID = ["16:9 Ngang", "9:16 Dọc"]


@dataclass
class Mode:
    key: str           # t2i, i2i, t2v, i2v, compose, extend
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
I2V = Mode("i2v", "Ảnh → Video", needs_ref=True, frames=True)
COMPOSE = Mode("compose", "Tham chiếu", needs_ref=True)
EXTEND = Mode("extend", "Kéo dài")       # tạo video rồi Kéo dài ngay trong Flow: "cảnh đầu || đoạn kéo dài"
# Trang ảnh chỉ còn 1 chế độ: tác vụ có ảnh tham chiếu (cột "Ảnh tham chiếu" / @Tên) tự chuyển sang Tham chiếu

DREAMINA_MODELS = ["Dreamina Seedance 2.0 Mini", "Dreamina Seedance 2.5 Flash", "Dreamina Seedance 2.0 Fast",
                   "Dreamina Seedance 2.0", "Dreamina Seedance 2.5"]

PAGES: list[PageDef] = [
    PageDef("flow_image", "Tạo ảnh Flow", "flow", "image", 0, "image",
            "https://flow.google.com/", [T2I],
            ["Nano Banana 2.1", "Nano Banana Pro", "Nano Banana 2 Lite"], RATIOS_IMG,
            {"quality": ["1K", "2K", "4K"]}, ready=True),
    PageDef("flow_video", "Tạo Video Flow", "flow", "video", 1, "video",
            "https://flow.google.com/", [T2V, I2V, EXTEND],
            ["Omni 1.2 Flash", "Veo 3.1 - Lite"], RATIOS_VID,      # từ 5/12/2026 Flow chỉ còn 2 model video này
            {"quality": ["720p", "1080p", "4K"],
             # thời lượng chỉnh được theo từng model (đọc từ Flow 11/2026); model khác dùng thời lượng cố định của model
             "durations": {"Omni 1.2 Flash": (3, 15, 8)},
             "extend_secs": (3, 10, 4)}, ready=True),     # Kéo dài: thanh trượt 3–10 giây (~3 tín dụng/giây, đọc từ Flow 11/2026)
    PageDef("dreamina", "Tạo Video Dreamina", "dreamina", "clapper", 4, "video",
            "https://dreamina.capcut.com/ai-tool/home?type=video", [T2V, I2V], DREAMINA_MODELS, RATIOS_VID,
            {"durations": {m: (5, 15, 5) for m in DREAMINA_MODELS},       # thanh thời lượng 0–15 giây (11/2026)
             "quality": ["720P", "1080P"]}, max_count=1, ready=True),
    PageDef("gpt_image", "Tạo ảnh GPT", "gpt", "sparkle", 5, "image",
            "https://chatgpt.com/images/", [T2I], ["GPT Image"],
            ["1:1 Vuông", "3:2 Ngang", "2:3 Dọc", "16:9 Ngang", "9:16 Dọc"],   # ChatGPT nhận tỷ lệ qua prompt
            max_count=1, ready=True),
    PageDef("meta_muse", "Tạo Video Muse", "muse", "stars", 6, "video",
            "https://muse.ai/", [T2V, I2V], ["Muse Video"], RATIOS_VID,      # muse.ai = trợ lý Muse của Meta (video 10 giây)
            max_count=1, ready=True),
    PageDef("grok_image", "Tạo ảnh Grok", "grok", "bot", 8, "image",
            "https://grok.com/", [T2I], ["Grok Imagine"],
            ["2:3 Dọc", "3:2 Ngang", "1:1 Vuông", "9:16 Dọc", "16:9 Ngang"], max_count=4, ready=True),
    PageDef("muse_image", "Tạo ảnh Muse", "muse", "stars", 6, "image",
            "https://muse.ai/", [T2I], ["Muse Image"],
            ["1:1 Vuông", "16:9 Ngang", "9:16 Dọc", "4:3 Ngang", "3:4 Dọc"], max_count=4, ready=True),   # tỷ lệ ghi trong yêu cầu
    PageDef("grok_video", "Tạo Video Grok", "grok", "bot", 8, "video",
            "https://grok.com/", [T2V, I2V], ["Grok Imagine"], RATIOS_VID,
            max_count=1, ready=True),      # bản thử nghiệm: dò giao diện + ghi "Grok chẩn đoán" vào Log
]

PAGE_BY_KEY = {p.key: p for p in PAGES}

PLATFORM_LABELS = {
    "flow": "Google Flow", "gvids": "Google Vids", "gpics": "Google Pics", "dreamina": "Dreamina",
    "gpt": "ChatGPT (GPT Image)", "muse": "Meta Muse (muse.ai)", "grok": "Grok",
}

# Mục công cụ (không phải trang tạo)
TOOL_ITEMS = [
    ("refs", "Kho ảnh tham chiếu", "library", 0),
    ("workflow", "Workflow", "nodes", 1),
    ("webhook", "Webhook API", "link", 2),      # ẩn mặc định (Cài Đặt › Chung › Hiện Webhook API)
    ("upscale", "Nâng Cấp Ảnh", "zoom", 3),
    ("video_tools", "Edit Video", "film", 4),
    ("download", "Download", "download", 5),
]
FOOTER_ITEMS = [
    ("logs", "Log Chi Tiết", "list", 8),
]
# Cài Đặt nằm ở góc trên bên phải; "Thông tin bản quyền" nằm dưới thương hiệu (không còn trong menu)
