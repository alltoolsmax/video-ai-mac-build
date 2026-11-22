"""Tạo kịch bản: AI Agent (tài khoản đã đăng nhập) xem ảnh tham chiếu (nhân vật NV*, sản phẩm SP*, bối cảnh BC*),
viết kịch bản theo chủ đề và chia đúng số cảnh theo thời lượng, mỗi cảnh = 1 prompt video (+ prompt ảnh khung đầu).

Tin nhắn gửi AI gồm 4 phần: hướng dẫn chung · hướng dẫn theo chủ đề · bảng ảnh + thông số · định dạng JSON bắt buộc.
Kết quả sai (JSON hỏng, sai số cảnh, nhãn lạ) → tự yêu cầu AI sửa (tối đa 2 lần)."""
from __future__ import annotations

import json
import math
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..core.paths import data_dir

# ------------------------------------------------------------------ chủ đề
TOPICS: dict[str, tuple[str, str]] = {
    "review": ("Review sản phẩm",
               "Mục tiêu: người xem tin sản phẩm đáng mua nhờ trải nghiệm thật.\n"
               "Cấu trúc: (1) Móc câu 3 giây đầu – nêu vấn đề / câu hỏi gây tò mò, nhân vật cầm sản phẩm. "
               "(2) Cận cảnh sản phẩm – chi tiết, chất liệu, bao bì. (3) Trải nghiệm – dùng thử, phản ứng chân thật. "
               "(4) Kết quả / so sánh trước-sau. (5) Kết luận + kêu gọi mua.\n"
               "Giọng: tự nhiên như người thật chia sẻ, không quá quảng cáo. Ưu tiên cận cảnh tay + sản phẩm."),
    "ads": ("Quảng cáo",
            "Mục tiêu: ấn tượng mạnh, nhớ sản phẩm, thôi thúc mua.\n"
            "Cấu trúc: (1) Hình ảnh mở đầu gây ấn tượng thị giác. (2) Vấn đề của khách hàng. "
            "(3) Sản phẩm xuất hiện như giải pháp – hero shot. (4) Lợi ích nổi bật (mỗi cảnh 1 lợi ích). "
            "(5) Hero shot cuối + câu slogan ngắn bằng lời thoại.\n"
            "Hình ảnh: điện ảnh, chuyển động máy mượt, ánh sáng studio, nhịp nhanh."),
    "intro": ("Giới thiệu",
              "Mục tiêu: giới thiệu rõ ràng sản phẩm / dịch vụ / thương hiệu / địa điểm.\n"
              "Cấu trúc: (1) Lời chào + nhân vật giới thiệu chủ đề. (2…) Từng đặc điểm chính, mỗi cảnh 1 đặc điểm. "
              "(cuối) Tổng kết + thông tin liên hệ bằng lời thoại (không chèn chữ).\n"
              "Giọng: thân thiện, rõ ràng, mạch lạc."),
    "film": ("Làm phim",
             "Mục tiêu: kể 1 câu chuyện có cảm xúc.\n"
             "Cấu trúc 3 hồi: Mở (bối cảnh + nhân vật) → Xung đột / bước ngoặt → Cao trào → Kết (giải quyết hoặc kết mở). "
             "Các cảnh nối tiếp hợp lý về thời gian, địa điểm, trang phục. Sản phẩm (nếu có) xuất hiện tự nhiên.\n"
             "Ngôn ngữ điện ảnh: cỡ cảnh đa dạng, góc máy có chủ đích, ánh sáng tạo cảm xúc."),
    "howto": ("Hướng dẫn",
              "Mục tiêu: người xem làm theo được.\n"
              "Cấu trúc: (1) Kết quả cuối cùng + \"làm thế nào?\". (2…) Mỗi cảnh = 1 bước, đánh số trong lời thoại "
              "(\"Bước 1…\"). (cuối) Kết quả + mẹo nhỏ. Ưu tiên cận cảnh tay thao tác, góc máy từ trên xuống."),
    "unbox": ("Unboxing",
              "Cấu trúc: (1) Hộp sản phẩm còn nguyên + phấn khích. (2) Mở hộp – cận cảnh. (3) Lấy sản phẩm ra, xoay ngắm. "
              "(4) Phụ kiện đi kèm / dùng thử nhanh. (5) Cảm nhận đầu tiên + kêu gọi.\n"
              "Âm thanh mở hộp, giấy sột soạt; ánh sáng sáng, sạch."),
    "vlog": ("Vlog / Kể chuyện",
             "Góc nhìn ngôi thứ nhất, nhân vật nói trực tiếp vào máy (selfie / cầm tay), bối cảnh đời thường thay đổi "
             "theo mạch chuyện. Giọng gần gũi, cảm xúc thật, có chi tiết cá nhân."),
    "news": ("Tin tức",
             "Nhân vật là người dẫn tin, trang phục lịch sự, bối cảnh phòng tin / hiện trường.\n"
             "Cấu trúc: (1) Tiêu đề tin bằng lời. (2…) Từng ý chính, khách quan, ngắn gọn. (cuối) Tổng kết.\n"
             "Không bịa số liệu – chỉ dùng thông tin trong Ý TƯỞNG."),
}
TOPIC_ORDER = ["review", "ads", "intro", "film", "howto", "unbox", "vlog", "news"]

LANGS = ["Tiếng Việt", "Tiếng Anh", "Không thoại (nhạc nền)"]
STYLES = ["Chân thực (quay thật)", "Điện ảnh", "Hoạt hình 3D", "Anime"]
KIND_LABEL = {"NV": "Nhân vật", "SP": "Sản phẩm / vật liệu", "BC": "Bối cảnh"}

# ------------------------------------------------------------------ giọng nói Flow (đọc từ Flow 11/2026)
VOICES = [("Achernar", "Female, soft, high pitch"), ("Achird", "Male, friendly, mid pitch"),
          ("Algenib", "Male, gravelly, low pitch"), ("Algieba", "Male, easy-going, mid-low pitch"),
          ("Alnilam", "Male, firm, mid-low pitch"), ("Aoede", "Female, breezy, mid pitch"),
          ("Autonoe", "Female, bright, mid pitch"), ("Callirrhoe", "Female, easy-going, mid pitch"),
          ("Charon", "Male, informative, lower pitch"), ("Despina", "Female, smooth, mid pitch"),
          ("Enceladus", "Male, breathy, lower pitch"), ("Erinome", "Female, clear, mid pitch"),
          ("Fenrir", "Male, excitable, younger pitch"), ("Gacrux", "Female, mature, mid pitch"),
          ("Iapetus", "Male, clear, mid-low pitch"), ("Kore", "Female, firm, mid pitch"),
          ("Laomedeia", "Female, upbeat, mid-high pitch"), ("Leda", "Female, youthful, mid-high pitch"),
          ("Orus", "Male, firm, mid-low pitch"), ("Puck", "Male, upbeat, mid pitch"),
          ("Rasalgethi", "Male, informative, mid pitch"), ("Sadachbia", "Male, lively, low pitch"),
          ("Sadaltager", "Male, knowledgeable, mid pitch"), ("Schedar", "Male, even, mid-low pitch"),
          ("Sulafat", "Female, warm, mid pitch"), ("Umbriel", "Male, smooth, lower pitch"),
          ("Vindemiatrix", "Female, gentle, mid pitch"), ("Zephyr", "Female, bright, mid-high pitch"),
          ("Zubenelgenubi", "Male, casual, mid-low pitch")]
VOICE_SAMPLE_URL = "https://www.gstatic.com/aitestkitchen/voices/samples/{name}.wav"   # đoạn mẫu công khai của Flow
_VI = {"Female": "Nữ", "Male": "Nam", "soft": "nhẹ nhàng", "friendly": "thân thiện", "gravelly": "khàn",
       "easy-going": "thoải mái", "firm": "chắc chắn", "breezy": "tươi tắn", "bright": "trong trẻo",
       "informative": "thuyết minh", "smooth": "mượt mà", "breathy": "thì thầm", "clear": "rõ ràng",
       "excitable": "hào hứng", "mature": "trưởng thành", "upbeat": "vui tươi", "youthful": "trẻ trung",
       "lively": "sôi nổi", "knowledgeable": "điềm đạm", "even": "đều giọng", "warm": "ấm áp", "gentle": "dịu dàng",
       "casual": "tự nhiên", "high pitch": "giọng cao", "mid pitch": "giọng trung", "mid-low pitch": "trung trầm",
       "low pitch": "giọng trầm", "lower pitch": "giọng trầm", "mid-high pitch": "trung cao", "younger pitch": "giọng trẻ"}


# Grok / Muse không có danh sách giọng: chọn kiểu giọng, AI Agent ghi đúng mô tả này vào mọi cảnh nhân vật nói
VOICE_PRESETS = {
    "Nữ trẻ": "Nữ, trẻ trung, trong trẻo, vui tươi",
    "Nữ trầm": "Nữ, trưởng thành, ấm, trầm",
    "Nam trẻ": "Nam, trẻ trung, năng động",
    "Nam trầm": "Nam, trưởng thành, trầm ấm, chắc chắn",
    "Trẻ em": "Trẻ em, hồn nhiên, giọng cao",
    "Lớn tuổi": "Người lớn tuổi, chậm rãi, hiền hậu",
}


def voice_text(name: str) -> str:
    """Mô tả giọng gửi AI: giọng Flow (Leda…) hoặc kiểu giọng (Nữ trẻ…)."""
    return voice_desc(name) or VOICE_PRESETS.get(name, name)


def voice_desc(name: str) -> str:
    d = dict(VOICES).get(name, "")
    return ", ".join(_VI.get(x.strip(), x.strip()) for x in d.split(",")) if d else ""


def voice_gender(name: str) -> str:
    return "Nữ" if dict(VOICES).get(name, "").startswith("Female") else "Nam"


def voice_cache_dir() -> Path:
    d = data_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ dữ liệu
@dataclass
class RefImage:
    tag: str            # NV1, SP2, BC1
    path: str
    voice: str = ""     # chỉ nhân vật

    @property
    def kind(self) -> str:
        return self.tag[:2]


@dataclass
class Brief:
    topic: str
    idea: str
    total_secs: int
    clip_secs: int
    ratio: str = "9:16"
    lang: str = "Tiếng Việt"
    style: str = "Chân thực (quay thật)"
    refs: list[RefImage] = field(default_factory=list)
    model: str = "Veo 3"
    keyframe: bool = True
    platform: str = "flow"
    kind: str = "video"          # "video" | "image" (Quy trình tự động ở trang tạo ảnh)
    count: int = 0               # số ảnh (kind="image")
    text_on: bool = False        # ảnh có chữ tiêu đề (kind="image")

    @property
    def silent(self) -> bool:
        """Không lời thoại (người dùng chọn "Không thoại") → nhịp nhanh + nhạc nền."""
        return self.lang.startswith("Không")

    @property
    def n(self) -> int:
        if self.kind == "image":
            return max(1, int(self.count or 1))
        return scene_count(self.total_secs, self.clip_secs)


def scene_count(total_secs: int, clip_secs: int) -> int:
    return max(1, math.ceil(max(1, total_secs) / max(1, clip_secs)))


def words_per_scene(clip_secs: int) -> int:
    return max(4, int(clip_secs * 2.5))


# ------------------------------------------------------------------ tin nhắn gửi AI
GENERAL = """Bạn là đạo diễn và biên kịch video ngắn chuyên nghiệp, viết prompt cho mô hình AI tạo video {model}.
Mỗi prompt tạo ra ĐÚNG 1 clip dài {secs} giây. Video hoàn chỉnh = {n} clip nối liền.

QUY TẮC BẮT BUỘC
1. Trả về ĐÚNG {n} cảnh – không hơn, không kém.
2. Ảnh đính kèm đã được gắn nhãn (xem BẢNG ẢNH). Chỉ dùng nhãn đó để gọi nhân vật / sản phẩm / bối cảnh.
   Không tự thêm nhân vật chính hoặc sản phẩm không có trong ảnh.
3. BƯỚC A – trước khi viết cảnh, quan sát kỹ từng ảnh và viết "hồ sơ nhận dạng" ngắn cho mỗi nhãn:
   – Nhân vật: giới tính, độ tuổi, khuôn mặt, kiểu tóc + màu tóc, trang phục, phụ kiện.
   – Sản phẩm / vật liệu: hình dạng, màu sắc, chất liệu, chữ / logo nhìn thấy, kích thước tương đối.
   – Bối cảnh: loại không gian, đồ vật chính, màu sắc, ánh sáng.
4. BƯỚC B – mỗi cảnh phải tự đứng được một mình (mô hình video KHÔNG nhớ cảnh trước):
   – Lặp lại mô tả nhận dạng NGẮN GỌN của mọi nhân vật / sản phẩm / bối cảnh xuất hiện trong cảnh, GIỐNG HỆT hồ sơ ở Bước A
     (cùng từ ngữ, cùng màu, cùng trang phục) để hình ảnh nhất quán giữa các cảnh.
   – Ghi rõ: cỡ cảnh (close-up, medium, wide…), chuyển động máy quay, bối cảnh, ánh sáng, hành động.
   – Chỉ 1 hành động chính vừa đủ {secs} giây.
5. Lời thoại: {lang_rule}
6. Tỷ lệ khung hình {ratio}; phong cách hình ảnh: {style}; giữ ánh sáng và tông màu nhất quán giữa các cảnh.
7. Không chèn chữ, phụ đề, logo, watermark lên hình. Không nhắc tên thương hiệu thật nếu người dùng không cung cấp.
8. Nội dung an toàn: không bạo lực, không khiêu dâm, không người thật nổi tiếng, không tuyên bố y tế / tài chính sai sự thật.
9. Thời gian: cảnh 1 = 0-{secs}s, cảnh 2 = {secs}-{secs2}s, … (cảnh k = (k-1)×{secs} đến k×{secs} giây).
10. Với mỗi cảnh viết thêm "frame": mô tả ẢNH TĨNH khung hình đầu tiên của cảnh (bố cục, vị trí nhân vật / sản phẩm,
    bối cảnh, ánh sáng, góc máy) – không có chuyển động, không có lời thoại. Ảnh này được tạo trước rồi dựng thành video."""

FORMAT = """ĐỊNH DẠNG TRẢ VỀ BẮT BUỘC: chỉ JSON hợp lệ (đặt giữa hai mốc như quy định bên dưới), không viết gì khác:
{{
  "profiles": {{{profile_keys}}},
  "scenes": [
    {{"time": "0-{secs}s", "title": "tiêu đề ngắn của cảnh", "refs": ["NV1", "SP1"], "frame": "mô tả ảnh khung đầu",
      "prompt": "{prompt_desc}"}}
  ]
}}
- "refs": chỉ chứa nhãn có trong BẢNG ẢNH và thật sự xuất hiện trong cảnh (có thể rỗng).
- Số phần tử của "scenes" PHẢI = {n}."""


SILENT_RULE = ("KHÔNG có lời thoại: không nhân vật nào nói, không cử động môi như đang nói, không lồng tiếng, không chữ trên hình. "
               "Kể chuyện hoàn toàn bằng hình ảnh, biểu cảm và hành động.")

SILENT_GUIDE = """VIDEO KHÔNG THOẠI – NHỊP NHANH + NHẠC NỀN (bắt buộc, ưu tiên hơn mọi phần lời thoại trong hướng dẫn chủ đề)
- Bỏ toàn bộ lời thoại / lời dẫn của hướng dẫn chủ đề; thay bằng hành động, biểu cảm, cử chỉ (chỉ tay, giơ sản phẩm,
  gật đầu, cười, ngạc nhiên…) và cận cảnh chi tiết sản phẩm để truyền tải đúng thông điệp.
- Nhịp NHANH, năng động: mỗi cảnh 1 hành động dứt khoát; máy quay chuyển động mạnh (push-in nhanh, whip pan, orbit
  nhanh, dolly, handheld năng động); có thể có 2-3 nhịp góc máy liên tiếp trong cùng cảnh; cảnh mở đầu có móc câu
  thị giác ngay giây đầu (chuyển động bất ngờ, cận cảnh nổi bật).
- Mỗi "prompt" PHẢI ghi nhạc nền cụ thể và GIỐNG NHAU ở mọi cảnh để video liền mạch: thể loại nhạc phù hợp chủ đề,
  tempo nhanh (khoảng 115-130 BPM), cảm xúc (sôi động / hào hứng / sang trọng nhịp nhanh…), nhấn beat theo chuyển động;
  kèm âm thanh hành động (whoosh khi chuyển máy, tiếng sản phẩm…). Ví dụ: "Background music: upbeat energetic electronic
  pop, ~124 BPM, punchy beat drops synced to camera moves; whoosh SFX on transitions. No dialogue, no voice-over."
- Tuyệt đối không viết câu thoại trong ngoặc kép, không "nói", "giới thiệu bằng lời", "voice-over"."""

MUSE_GUIDE = """NỀN TẢNG: Muse (Meta) – Muse KHÔNG tạo video có người nói thoại / nhép môi từ ảnh người thật.
Viết prompt để Muse tạo được ngay: người trong ảnh chỉ diễn bằng hành động, biểu cảm (không nói), tập trung vào sản phẩm
và chuyển động; không yêu cầu nhép môi, không ghi giọng nói."""


def lang_rule(b: Brief) -> str:
    if b.silent:
        return SILENT_RULE
    w = words_per_scene(b.clip_secs)
    lang = "tiếng Việt" if b.lang == "Tiếng Việt" else "tiếng Anh"
    rule = (f"{lang}. Mỗi cảnh tối đa {w} chữ (≈ 2,5 chữ / giây), đặt trong ngoặc kép cong “…” (không dùng dấu ngoặc kép thẳng), ghi rõ ai nói "
            f"(dùng nhãn, vd: NV1 nói: \"…\").")
    vs = [r for r in b.refs if r.kind == "NV" and r.voice]
    if vs:
        rule += " Giọng nói cố định của từng nhân vật (ghi đúng mô tả giọng này trong mọi cảnh nhân vật đó nói): " + \
                "; ".join(f"{r.tag} = giọng {voice_text(r.voice).lower()}" for r in vs) + "."
    return rule


def table(b: Brief) -> str:
    if not b.refs:
        return ("BẢNG ẢNH: không có ảnh. Hãy tự sáng tạo nhân vật / sản phẩm / bối cảnh theo ý tưởng, đặt nhãn NV1, SP1, BC1…, "
                "vẫn viết hồ sơ nhận dạng và lặp lại ở mỗi cảnh.")
    lines = ["BẢNG ẢNH (theo đúng thứ tự ảnh đính kèm)"]
    for i, r in enumerate(b.refs, 1):
        lines.append(f"Ảnh {i} = {r.tag} – {KIND_LABEL[r.kind]} {r.tag[2:]}")
    return "\n".join(lines)


def build_message(b: Brief) -> tuple[str, str]:
    """(hướng dẫn hệ thống, nội dung yêu cầu)."""
    label, guide = TOPICS.get(b.topic, TOPICS["review"])
    n, secs = b.n, b.clip_secs
    system = GENERAL.format(model=b.model, secs=secs, n=n, secs2=secs * 2, lang_rule=lang_rule(b), ratio=b.ratio,
                            style=b.style)
    system += f"\n\nHƯỚNG DẪN THEO CHỦ ĐỀ \"{label}\"\n{guide}\n"
    if b.silent:
        system += "\n" + SILENT_GUIDE + "\n"
    if b.platform == "muse" and b.silent:
        system += "\n" + MUSE_GUIDE + "\n"
    if n == 1:
        system += "Chỉ có 1 cảnh: gộp móc câu + nội dung chính + kết / kêu gọi vào cùng 1 clip.\n"
    elif n < 5:
        system += f"Chỉ có {n} cảnh: rút gọn cấu trúc trên cho vừa {n} cảnh, giữ phần mở đầu và kết.\n"
    else:
        system += f"Có {n} cảnh: phân bổ cấu trúc trên đều cho {n} cảnh.\n"
    keys = ", ".join(f"\"{r.tag}\": \"…\"" for r in b.refs) or "\"NV1\": \"…\""
    desc = ("prompt video hoàn chỉnh của cảnh: hành động, máy quay nhịp nhanh, nhạc nền (thể loại, tempo, cảm xúc) + âm thanh, "
            "KHÔNG lời thoại" if b.silent else "prompt video hoàn chỉnh của cảnh, gồm cả lời thoại trong ngoặc kép cong “…” và ai nói")
    system += "\n" + FORMAT.format(profile_keys=keys, secs=secs, n=n, prompt_desc=desc)
    user = (f"{table(b)}\n\nCHỦ ĐỀ: {label}\nÝ TƯỞNG CỦA NGƯỜI DÙNG: {b.idea.strip() or '(không có – tự đề xuất theo chủ đề và ảnh)'}\n"
            f"SỐ CẢNH: {n} · MỖI CẢNH: {secs} giây · TỔNG: {n * secs} giây\n"
            f"TỶ LỆ: {b.ratio} · LỜI THOẠI: {'Không thoại – nhịp nhanh, có nhạc nền' if b.silent else b.lang} · "
            f"PHONG CÁCH: {b.style}")
    return system, user


# ------------------------------------------------------------------ đọc & kiểm tra kết quả
class ScriptError(ValueError):
    pass


def _json_part(text: str) -> str:
    t = text.replace("[[OUT]]", " ").replace("[[END]]", " ").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, z = t.find("{"), t.rfind("}")
    la, lz = t.find("["), t.rfind("]")
    if 0 <= la < (a if a >= 0 else 10 ** 9) and lz > la:   # JSON là danh sách [...]
        return t[la:lz + 1]
    if a < 0 or z <= a:
        raise ScriptError("không có JSON trong câu trả lời")
    return t[a:z + 1]


def _repair_json(t: str) -> str:
    """Vá JSON AI hay viết sai: dấu " thẳng bên trong chuỗi (lời thoại "…"), xuống dòng trong chuỗi, dấu ',' thừa."""
    out, in_str, esc, n = [], False, False, len(t)

    def nxt(j: int) -> tuple[str, int]:
        while j < n and t[j] in " \t\r\n":
            j += 1
        return (t[j] if j < n else ""), j

    for i, c in enumerate(t):
        if not in_str:
            in_str = c == '"'
            out.append(c)
            continue
        if esc:
            esc = False
            out.append(c)
        elif c == "\\":
            esc = True
            out.append(c)
        elif c == '"':
            ch, j = nxt(i + 1)
            end = ch in ("", "}", "]", ":")
            if ch == ",":                              # sau dấu phẩy phải là khóa / giá trị JSON mới thật là hết chuỗi
                ch2, _ = nxt(j + 1)
                end = ch2 in ('"', "{", "[", "}", "]") or ch2.isdigit()
            if end:
                in_str = False
                out.append(c)
            else:
                out.append('\\"')
        elif c in "\r\n":
            out.append("\\n" if c == "\n" else "")
        else:
            out.append(c)
    return re.sub(r",\s*([}\]])", r"\1", "".join(out))


def _pick(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _scenes_of(data) -> list:
    """Danh sách cảnh: data["scenes"], hoặc danh sách đầu tiên trong JSON (images / canh…), hoặc JSON là danh sách."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    sc = data.get("scenes") or data.get("Scenes")
    if isinstance(sc, list) and sc:
        return sc
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], (dict, str)):
            return v
    return []


def parse(text: str, n: int, tags: list[str]) -> dict:
    raw = _json_part(text)
    try:
        data = json.loads(raw)
    except Exception as e:
        try:
            data = json.loads(_repair_json(raw))
        except Exception:
            raise ScriptError(f"JSON không hợp lệ ({e})") from e
    scenes = _scenes_of(data)
    if not scenes:
        raise ScriptError("thiếu danh sách \"scenes\"")
    if len(scenes) > n:                              # AI viết thừa → lấy đúng n cảnh / ảnh đầu
        scenes = scenes[:n]
    if len(scenes) < n:
        raise ScriptError(f"trả về {len(scenes)} cảnh, cần đúng {n} cảnh")
    out = []
    allowed = set(tags)
    for i, sc in enumerate(scenes, 1):
        if isinstance(sc, str) and sc.strip():      # AI trả thẳng danh sách prompt (chuỗi)
            sc = {"prompt": sc}
        if not isinstance(sc, dict):
            raise ScriptError(f"cảnh {i} thiếu \"prompt\"")
        prompt = _pick(sc, "prompt", "Prompt", "PROMPT", "text", "description", "mo_ta", "noi_dung")
        if not prompt:
            raise ScriptError(f"cảnh {i} thiếu \"prompt\"")
        raw_refs = sc.get("refs") or sc.get("Refs") or []
        if isinstance(raw_refs, str):
            raw_refs = [raw_refs]
        refs = []                                    # nhận "NV1", "nv 1", "NV1 (cô gái)"…; nhãn lạ thì bỏ qua
        for r in raw_refs:
            for k_, num in re.findall(r"\b(NV|SP|BC)\s*0*(\d{1,2})\b", str(r).upper()):
                t_ = f"{k_}{num}"
                if t_ in allowed and t_ not in refs:
                    refs.append(t_)
        out.append({"time": str(sc.get("time") or ""), "title": str(_pick(sc, "title", "Title", "tieu_de") or "").strip(),
                    "refs": refs, "frame": " ".join(str(sc.get("frame") or "").split()),
                    "prompt": " ".join(str(prompt).split())})
    prof = data.get("profiles") if isinstance(data, dict) and isinstance(data.get("profiles"), dict) else {}
    return {"profiles": {str(k): str(v) for k, v in prof.items()}, "scenes": out}


def fix_times(scenes: list[dict], secs: int):
    for i, sc in enumerate(scenes):
        sc["time"] = f"{i * secs}-{(i + 1) * secs}s"


# ------------------------------------------------------------------ ảnh gửi AI
def prepare_images(refs: list[RefImage], long_side: int = 1024) -> list[str]:
    """Thu nhỏ ảnh + đặt tên tệp theo nhãn (NV1.jpg…) để AI thấy nhãn ngay trong tên tệp."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    d = data_dir() / "tmp" / f"script_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for r in refs:
        dst = d / f"{r.tag}.jpg"
        im = QImage(r.path)
        if im.isNull():
            dst = d / f"{r.tag}{Path(r.path).suffix.lower() or '.jpg'}"
            shutil.copy(r.path, dst)
        else:
            if max(im.width(), im.height()) > long_side:
                im = im.scaled(long_side, long_side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            im.convertToFormat(QImage.Format_RGB888).save(str(dst), "JPG", 90)
        out.append(str(dst))
    return out


def keep_refs(refs: list[RefImage]) -> list[RefImage]:
    """Chép ảnh tham chiếu vào thư mục dữ liệu của tools (tác vụ vẫn chạy được khi ảnh gốc bị di chuyển / xóa)."""
    d = data_dir() / "scripts" / uuid.uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    res = []
    for r in refs:
        dst = d / f"{r.tag}{Path(r.path).suffix.lower() or '.jpg'}"
        shutil.copy(r.path, dst)
        res.append(RefImage(r.tag, str(dst), r.voice))
    return res


# ------------------------------------------------------------------ gọi AI Agent
def _ask(db, engine, system: str, user: str, files: list[str], on_status, check=None) -> str:
    from . import llm
    if check is None:
        return llm.ask(db, engine, system, user, files=files or None, timeout_s=420, on_status=on_status)
    return llm.ask(db, engine, system, user, files=files or None, timeout_s=420, on_status=on_status,
                   check=check, want_json=True)


CHUNK = 10          # > 10 cảnh / ảnh: AI viết theo từng phần 10 (câu trả lời ngắn → không bị cắt, ít sai)


def _part_note(k: int, parts: int, s0: int, c: int, n: int, unit: str, prev: list[dict], profiles: dict) -> str:
    t = (f"\n\nVIẾT THEO TỪNG PHẦN: toàn bộ có {n} {unit}, chia {parts} phần. Đây là PHẦN {k + 1}/{parts}: chỉ viết "
         f"{unit} {s0 + 1} đến {s0 + c} (\"scenes\" gồm đúng {c} mục), nối tiếp mạch chung của cả {n} {unit}.")
    if prev:
        t += ("\nHồ sơ nhận dạng đã chốt ở phần trước – dùng y nguyên và trả lại trong \"profiles\":\n"
              + json.dumps(profiles, ensure_ascii=False)
              + f"\nCác {unit} đã viết (giữ mạch, không lặp lại):\n"
              + "\n".join(f"{i + 1}. {p_['title']} – {p_['prompt'][:160]}" for i, p_ in enumerate(prev)))
    return t


def _write_parts(db, engine, b: Brief, build, unit: str, again: str, on_status) -> dict:
    """Gửi AI Agent (chia phần nếu nhiều), kiểm tra định dạng ngay khi nhận (sai → AI tự sửa / đổi tài khoản)."""
    from dataclasses import replace
    say = on_status or (lambda m: None)
    files = prepare_images(b.refs) if b.refs else []
    tags = [r.tag for r in b.refs]
    n = b.n
    plan = [(s0, min(CHUNK, n - s0)) for s0 in range(0, n, CHUNK)]
    scenes: list[dict] = []
    profiles: dict = {}
    for k, (s0, c) in enumerate(plan):
        pb = replace(b, count=c) if b.kind == "image" else replace(b, total_secs=c * b.clip_secs)
        system, user = build(pb)
        if len(plan) > 1:
            user += _part_note(k, len(plan), s0, c, n, unit, scenes, profiles)
            say(f"AI Agent đang viết phần {k + 1}/{len(plan)} ({unit} {s0 + 1}–{s0 + c})…")
        else:
            say(f"AI Agent đang xem ảnh và viết {unit}…" if files else f"AI Agent đang viết {unit}…")
        try:
            ans = _ask(db, engine, system, user, files, say, check=lambda a_, c=c: parse(a_, c, tags))
            res = parse(ans, c, tags)
        except ScriptError as e:
            raise RuntimeError(f"AI Agent trả kết quả chưa đúng ({e}). Bấm {again} để thử lại.") from e
        except RuntimeError as e:
            raise RuntimeError(f"{e}. Bấm {again} để thử lại.") from e
        if not profiles:
            profiles = res["profiles"]
        scenes += res["scenes"]
    return {"profiles": profiles, "scenes": scenes}


def generate(db, engine, b: Brief, on_status=None, retries: int = 2) -> dict:
    res = _write_parts(db, engine, b, build_message, "cảnh", "Phân tích và tạo kịch bản", on_status)
    fix_times(res["scenes"], b.clip_secs)
    return res


def rewrite_scene(db, engine, b: Brief, script: dict, k: int, on_status=None) -> dict:
    """Viết lại riêng cảnh k (0-based), giữ hồ sơ nhận dạng và mạch truyện."""
    system, user = build_message(b)
    files = prepare_images(b.refs) if b.refs else []
    ctx = json.dumps({"profiles": script.get("profiles", {}),
                      "scenes": [{"title": s["title"], "prompt": s["prompt"]} for s in script["scenes"]]},
                     ensure_ascii=False)
    req = (f"{user}\n\nKỊCH BẢN HIỆN TẠI:\n{ctx}\n\nChỉ viết lại CẢNH {k + 1} cho hay hơn, giữ nguyên hồ sơ nhận dạng, "
           f"mạch truyện và độ dài {b.clip_secs} giây. Trả về JSON cùng định dạng nhưng \"scenes\" chỉ gồm 1 cảnh.")
    tags = [r.tag for r in b.refs]
    try:
        ans = _ask(db, engine, system, req, files, on_status, check=lambda a_: parse(a_, 1, tags))
        sc = parse(ans, 1, tags)["scenes"][0]
    except (ScriptError, RuntimeError) as e:
        raise RuntimeError(f"AI Agent viết lại cảnh chưa được ({e}) – thử lại.") from e
    sc["time"] = f"{k * b.clip_secs}-{(k + 1) * b.clip_secs}s"
    return sc


# ------------------------------------------------------------------ cảnh → tác vụ
def to_tasks(b: Brief, script: dict, refs: list[RefImage], chain: bool, flow: bool) -> list[dict]:
    """Mỗi cảnh = 1 tác vụ: {"prompt", "refs" (đường dẫn ảnh), "params" (riêng của tác vụ)}."""
    by_tag = {r.tag: r for r in refs}
    sid = uuid.uuid4().hex[:10]
    tasks = []
    for i, sc in enumerate(script["scenes"]):
        used = [by_tag[t] for t in sc["refs"] if t in by_tag]
        params: dict = {"script_id": sid, "scene": i + 1}
        if flow:
            voices = [] if b.silent else [r.voice for r in used if r.kind == "NV" and r.voice]
            if voices:
                params["voices"] = voices
            if b.keyframe and used:
                params["keyframe"] = True
                params["frame_prompt"] = sc.get("frame") or sc["prompt"]
            if chain and i > 0:
                params["chain"] = True                  # khung đầu = khung cuối video của cảnh trước (cùng script_id)
            paths = [r.path for r in used][:3 if not b.keyframe else 10]
        else:
            # Grok / Muse (chat): Nhất quán cao = tạo ảnh khung đầu từ tối đa 4 ảnh của cảnh rồi dựng video từ ảnh đó;
            # Nhanh = ảnh chính của cảnh làm ảnh đầu (nhân vật › sản phẩm › bối cảnh). Giọng: mô tả trong prompt.
            if b.keyframe and used:
                params["keyframe"] = True
                params["frame_prompt"] = sc.get("frame") or sc["prompt"]
                paths = [r.path for r in used][:4]
            else:
                main = sorted(used, key=lambda r: "NSB".index(r.kind[0]) if r.kind[0] in "NSB" else 9)[:1]
                paths = [r.path for r in main]
            if chain and i > 0:
                params["chain"] = True
        tasks.append({"prompt": sc["prompt"], "refs": paths, "params": params, "title": sc.get("title", "")})
    return tasks


# ================================================================== QUY TRÌNH TỰ ĐỘNG – ẢNH
IMG_TOPICS: dict[str, tuple[str, str]] = {
    "product": ("Quảng cáo sản phẩm",
                "Bộ ảnh bán hàng: (1) Hero shot – sản phẩm nổi bật trên nền sạch, ánh sáng studio. (2) Cận cảnh chi tiết / "
                "chất liệu / bao bì. (3) Sản phẩm trong bối cảnh sử dụng thật (lifestyle), có nhân vật nếu có ảnh NV. "
                "(4) Thành phần / tính năng minh họa bằng đạo cụ. (5) Ảnh kết – sản phẩm + không khí thương hiệu. "
                "Đa dạng góc chụp (chính diện, 3/4, top-down, macro) nhưng giữ cùng tông màu."),
    "fashion": ("Lookbook / thời trang",
                "Bộ ảnh thời trang: nhân vật mặc / dùng sản phẩm, đa dạng dáng (đứng, bước đi, ngồi, quay lưng, cận chi tiết "
                "vải / phụ kiện). Ánh sáng editorial, bố cục tạp chí, nền đồng nhất hoặc phố / studio theo ý tưởng. "
                "Giữ nguyên khuôn mặt, kiểu tóc và trang phục giữa các ảnh."),
    "social": ("Bài mạng xã hội",
               "Bộ ảnh cho 1 bài đăng / carousel: ảnh 1 là móc câu thị giác mạnh, các ảnh sau kể tiếp 1 mạch (trước – sau, "
               "các bước, các lợi ích). Màu sắc tươi, bắt mắt trên điện thoại, chủ thể lớn, rõ ở giữa khung."),
    "thumb": ("Thumbnail video",
              "Ảnh bìa video: chủ thể lớn, biểu cảm mạnh (ngạc nhiên, hào hứng), tương phản cao, nền đơn giản, "
              "chừa khoảng trống rõ ràng ở 1 bên cho tiêu đề. Mỗi ảnh là 1 phương án bìa khác nhau để chọn."),
    "poster": ("Poster / banner",
               "Bố cục poster quảng bá: chủ thể chính + không gian trống cho tiêu đề và thông tin, phân cấp thị giác rõ, "
               "ánh sáng ấn tượng, màu thương hiệu thống nhất. Mỗi ảnh là 1 biến thể bố cục (dọc, ngang, cận, toàn)."),
    "character": ("Nhân vật / concept",
                  "Bộ ảnh nhân vật nhất quán: chân dung chính diện, 3/4, toàn thân, các biểu cảm và hành động khác nhau, "
                  "cùng trang phục và đặc điểm nhận dạng. Phù hợp làm nhân vật cho video / truyện."),
    "story": ("Minh họa câu chuyện",
              "Mỗi ảnh là 1 khoảnh khắc nối tiếp của câu chuyện (mở – diễn biến – cao trào – kết), cùng nhân vật, "
              "trang phục, bối cảnh nhất quán; bố cục điện ảnh, ánh sáng gợi cảm xúc."),
    "food": ("Ảnh món ăn / menu",
             "Ảnh món ăn hấp dẫn: góc 45° và top-down, ánh sáng tự nhiên mềm, hơi nóng / giọt nước / topping rõ nét, "
             "đạo cụ bàn ăn phù hợp; mỗi ảnh 1 món hoặc 1 góc nhìn khác của món chính."),
}
IMG_TOPIC_ORDER = ["product", "fashion", "social", "thumb", "poster", "character", "story", "food"]

IMG_GENERAL = """Bạn là đạo diễn hình ảnh / nhiếp ảnh gia quảng cáo chuyên nghiệp, viết prompt cho mô hình AI tạo ảnh {model}.
Viết ĐÚNG {n} prompt, mỗi prompt tạo ra 1 ảnh; {n} ảnh tạo thành một bộ ảnh thống nhất.

QUY TẮC BẮT BUỘC
1. Trả về ĐÚNG {n} ảnh – không hơn, không kém.
2. Ảnh đính kèm đã được gắn nhãn (xem BẢNG ẢNH). Chỉ dùng nhãn đó để gọi nhân vật / sản phẩm / bối cảnh.
   Không tự thêm nhân vật chính hoặc sản phẩm không có trong ảnh.
3. BƯỚC A – quan sát kỹ từng ảnh và viết "hồ sơ nhận dạng" ngắn cho mỗi nhãn (nhân vật: giới tính, độ tuổi, khuôn mặt,
   tóc, trang phục; sản phẩm: hình dạng, màu, chất liệu, chữ / logo nhìn thấy; bối cảnh: không gian, màu, ánh sáng).
4. BƯỚC B – mỗi prompt tự đứng được một mình (mô hình không nhớ ảnh trước): lặp lại mô tả nhận dạng NGẮN GỌN, GIỐNG HỆT
   hồ sơ ở Bước A của mọi nhãn xuất hiện trong ảnh, để nhân vật / sản phẩm nhất quán giữa các ảnh.
5. Mỗi prompt ghi rõ: chủ thể + hành động / tư thế, bố cục, cỡ cảnh và góc chụp, ống kính / độ sâu trường ảnh,
   bối cảnh, ánh sáng, bảng màu, chất liệu. Các ảnh trong bộ phải KHÁC NHAU về bố cục / góc chụp, không lặp lại.
6. Tỷ lệ khung hình {ratio}; phong cách hình ảnh: {style}; giữ tông màu và ánh sáng thống nhất cả bộ.
7. Chữ trên ảnh: {text_rule}
8. Không logo / watermark tự bịa. Không nhắc tên thương hiệu thật nếu người dùng không cung cấp.
9. Nội dung an toàn: không bạo lực, không khiêu dâm, không người thật nổi tiếng, không tuyên bố y tế / tài chính sai sự thật."""

IMG_FORMAT = """ĐỊNH DẠNG TRẢ VỀ BẮT BUỘC: chỉ JSON hợp lệ, không viết gì khác:
{{
  "profiles": {{{profile_keys}}},
  "scenes": [
    {{"title": "tên ngắn của ảnh (vd: Hero, Cận chất liệu)", "refs": ["NV1", "SP1"], "prompt": "prompt ảnh hoàn chỉnh"}}
  ]
}}
- "refs": chỉ chứa nhãn có trong BẢNG ẢNH và thật sự xuất hiện trong ảnh đó (có thể rỗng).
- Số phần tử của "scenes" PHẢI = {n}."""

IMG_REF_MAX = {"flow": 10, "gpt": 6, "grok": 4, "muse": 4}


def text_rule(b: Brief) -> str:
    if not b.text_on:
        return "KHÔNG có chữ, phụ đề, logo hay watermark trên ảnh."
    return ("CÓ 1 dòng tiêu đề ngắn (tối đa 6 chữ) bằng tiếng Việt, lấy ý từ Ý TƯỞNG, ghi trong ngoặc kép cong “…” ngay trong prompt, "
            "chỉ rõ vị trí (vd: phía trên, chữ đậm màu trắng), chừa khoảng trống cho chữ; không thêm chữ nào khác.")


def build_image_message(b: Brief) -> tuple[str, str]:
    label, guide = IMG_TOPICS.get(b.topic, IMG_TOPICS["product"])
    n = b.n
    system = IMG_GENERAL.format(model=b.model, n=n, ratio=b.ratio, style=b.style, text_rule=text_rule(b))
    system += f"\n\nHƯỚNG DẪN THEO MỤC ĐÍCH \"{label}\"\n{guide}\n"
    if n == 1:
        system += "Chỉ có 1 ảnh: chọn bố cục mạnh nhất, thể hiện đầy đủ ý tưởng.\n"
    else:
        system += f"Có {n} ảnh: phân bổ hướng dẫn trên cho {n} ảnh, mỗi ảnh 1 góc nhìn / vai trò khác nhau.\n"
    keys = ", ".join(f"\"{r.tag}\": \"…\"" for r in b.refs) or "\"NV1\": \"…\""
    system += "\n" + IMG_FORMAT.format(profile_keys=keys, n=n)
    user = (f"{table(b)}\n\nMỤC ĐÍCH: {label}\nÝ TƯỞNG CỦA NGƯỜI DÙNG: {b.idea.strip() or '(không có – tự đề xuất theo mục đích và ảnh)'}\n"
            f"SỐ ẢNH: {n} · TỶ LỆ: {b.ratio} · PHONG CÁCH: {b.style} · CHỮ TRÊN ẢNH: {'có tiêu đề' if b.text_on else 'không'}")
    return system, user


def generate_images(db, engine, b: Brief, on_status=None, retries: int = 2) -> dict:
    res = _write_parts(db, engine, b, build_image_message, "ảnh", "Phân tích và tạo nội dung", on_status)
    for sc in res["scenes"]:
        sc["time"] = ""
    return res


def rewrite_image(db, engine, b: Brief, script: dict, k: int, on_status=None) -> dict:
    """Viết lại riêng ảnh k (0-based), giữ hồ sơ nhận dạng và sự thống nhất của bộ ảnh."""
    system, user = build_image_message(b)
    files = prepare_images(b.refs) if b.refs else []
    ctx = json.dumps({"profiles": script.get("profiles", {}),
                      "scenes": [{"title": s["title"], "prompt": s["prompt"]} for s in script["scenes"]]},
                     ensure_ascii=False)
    req = (f"{user}\n\nBỘ ẢNH HIỆN TẠI:\n{ctx}\n\nChỉ viết lại ẢNH {k + 1} cho hay hơn và khác các ảnh còn lại, giữ nguyên "
           f"hồ sơ nhận dạng và tông của bộ. Trả về JSON cùng định dạng nhưng \"scenes\" chỉ gồm 1 ảnh.")
    tags = [r.tag for r in b.refs]
    try:
        ans = _ask(db, engine, system, req, files, on_status, check=lambda a_: parse(a_, 1, tags))
        sc = parse(ans, 1, tags)["scenes"][0]
    except (ScriptError, RuntimeError) as e:
        raise RuntimeError(f"AI Agent viết lại ảnh chưa được ({e}) – thử lại.") from e
    sc["time"] = ""
    return sc


def image_tasks(b: Brief, script: dict, refs: list[RefImage]) -> list[dict]:
    """Mỗi ảnh = 1 tác vụ tạo ảnh, đính kèm đúng ảnh tham chiếu ảnh đó cần (nhân vật › sản phẩm › bối cảnh)."""
    by_tag = {r.tag: r for r in refs}
    sid = uuid.uuid4().hex[:10]
    cap = IMG_REF_MAX.get(b.platform, 4)
    out = []
    for i, sc in enumerate(script["scenes"]):
        used = [by_tag[t] for t in sc["refs"] if t in by_tag]
        used.sort(key=lambda r: "NSB".index(r.kind[0]) if r.kind[0] in "NSB" else 9)
        out.append({"prompt": sc["prompt"], "refs": [r.path for r in used][:cap],
                    "params": {"script_id": sid, "scene": i + 1, "ratio": b.ratio, "image": True}, "title": sc.get("title", "")})
    return out
