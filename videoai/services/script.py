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

    @property
    def n(self) -> int:
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
      "prompt": "prompt video hoàn chỉnh của cảnh, gồm cả lời thoại trong ngoặc kép và ai nói"}}
  ]
}}
- "refs": chỉ chứa nhãn có trong BẢNG ẢNH và thật sự xuất hiện trong cảnh (có thể rỗng).
- Số phần tử của "scenes" PHẢI = {n}."""


def lang_rule(b: Brief) -> str:
    if b.lang.startswith("Không"):
        return "KHÔNG có lời nói. Chỉ mô tả âm thanh môi trường / nhạc nền."
    w = words_per_scene(b.clip_secs)
    lang = "tiếng Việt" if b.lang == "Tiếng Việt" else "tiếng Anh"
    rule = (f"{lang}. Mỗi cảnh tối đa {w} chữ (≈ 2,5 chữ / giây), đặt trong ngoặc kép, ghi rõ ai nói "
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
    if n == 1:
        system += "Chỉ có 1 cảnh: gộp móc câu + nội dung chính + kết / kêu gọi vào cùng 1 clip.\n"
    elif n < 5:
        system += f"Chỉ có {n} cảnh: rút gọn cấu trúc trên cho vừa {n} cảnh, giữ phần mở đầu và kết.\n"
    else:
        system += f"Có {n} cảnh: phân bổ cấu trúc trên đều cho {n} cảnh.\n"
    keys = ", ".join(f"\"{r.tag}\": \"…\"" for r in b.refs) or "\"NV1\": \"…\""
    system += "\n" + FORMAT.format(profile_keys=keys, secs=secs, n=n)
    user = (f"{table(b)}\n\nCHỦ ĐỀ: {label}\nÝ TƯỞNG CỦA NGƯỜI DÙNG: {b.idea.strip() or '(không có – tự đề xuất theo chủ đề và ảnh)'}\n"
            f"SỐ CẢNH: {n} · MỖI CẢNH: {secs} giây · TỔNG: {n * secs} giây\n"
            f"TỶ LỆ: {b.ratio} · LỜI THOẠI: {b.lang} · PHONG CÁCH: {b.style}")
    return system, user


# ------------------------------------------------------------------ đọc & kiểm tra kết quả
class ScriptError(ValueError):
    pass


def _json_part(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, z = t.find("{"), t.rfind("}")
    if a < 0 or z <= a:
        raise ScriptError("không có JSON trong câu trả lời")
    return t[a:z + 1]


def parse(text: str, n: int, tags: list[str]) -> dict:
    try:
        data = json.loads(_json_part(text))
    except ScriptError:
        raise
    except Exception as e:
        raise ScriptError(f"JSON không hợp lệ ({e})") from e
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ScriptError("thiếu danh sách \"scenes\"")
    if len(scenes) != n:
        raise ScriptError(f"trả về {len(scenes)} cảnh, cần đúng {n} cảnh")
    out = []
    allowed = set(tags)
    for i, sc in enumerate(scenes, 1):
        if not isinstance(sc, dict) or not str(sc.get("prompt", "")).strip():
            raise ScriptError(f"cảnh {i} thiếu \"prompt\"")
        refs = [str(r).strip().upper() for r in (sc.get("refs") or []) if str(r).strip()]
        bad = [r for r in refs if allowed and r not in allowed]
        if bad:
            raise ScriptError(f"cảnh {i} dùng nhãn không có trong bảng ảnh: {', '.join(bad)}")
        if not allowed:
            refs = []
        out.append({"time": str(sc.get("time") or ""), "title": str(sc.get("title") or "").strip(),
                    "refs": refs, "frame": " ".join(str(sc.get("frame") or "").split()),
                    "prompt": " ".join(str(sc["prompt"]).split())})
    prof = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
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
def _ask(db, engine, system: str, user: str, files: list[str], on_status) -> str:
    from . import llm
    return llm.ask(db, engine, system, user, files=files or None, timeout_s=420, on_status=on_status)


def generate(db, engine, b: Brief, on_status=None, retries: int = 2) -> dict:
    say = on_status or (lambda m: None)
    system, user = build_message(b)
    files = prepare_images(b.refs) if b.refs else []
    tags = [r.tag for r in b.refs]
    say("AI Agent đang xem ảnh và viết kịch bản…")
    ans = _ask(db, engine, system, user, files, say)
    for attempt in range(retries + 1):
        try:
            res = parse(ans, b.n, tags)
            fix_times(res["scenes"], b.clip_secs)
            return res
        except ScriptError as e:
            if attempt >= retries:
                raise RuntimeError(f"AI Agent trả kết quả chưa đúng ({e}). Bấm Tạo kịch bản để thử lại.") from e
            say(f"Kết quả chưa đúng ({e}) – yêu cầu AI sửa lại…")
            fix = (f"{user}\n\nCÂU TRẢ LỜI TRƯỚC CỦA BẠN BỊ LỖI: {e}.\nCâu trả lời trước:\n{ans[:6000]}\n\n"
                   f"Hãy sửa lại: trả về đúng {b.n} cảnh, đúng định dạng JSON đã quy định.")
            ans = _ask(db, engine, system, fix, files, say)
    raise RuntimeError("AI Agent không trả kết quả")


def rewrite_scene(db, engine, b: Brief, script: dict, k: int, on_status=None) -> dict:
    """Viết lại riêng cảnh k (0-based), giữ hồ sơ nhận dạng và mạch truyện."""
    system, user = build_message(b)
    files = prepare_images(b.refs) if b.refs else []
    ctx = json.dumps({"profiles": script.get("profiles", {}),
                      "scenes": [{"title": s["title"], "prompt": s["prompt"]} for s in script["scenes"]]},
                     ensure_ascii=False)
    req = (f"{user}\n\nKỊCH BẢN HIỆN TẠI:\n{ctx}\n\nChỉ viết lại CẢNH {k + 1} cho hay hơn, giữ nguyên hồ sơ nhận dạng, "
           f"mạch truyện và độ dài {b.clip_secs} giây. Trả về JSON cùng định dạng nhưng \"scenes\" chỉ gồm 1 cảnh.")
    for attempt in range(3):
        ans = _ask(db, engine, system, req, files, on_status)
        try:
            sc = parse(ans, 1, [r.tag for r in b.refs])["scenes"][0]
            sc["time"] = f"{k * b.clip_secs}-{(k + 1) * b.clip_secs}s"
            return sc
        except ScriptError:
            if attempt == 2:
                raise RuntimeError("AI Agent viết lại cảnh chưa đúng định dạng – thử lại.")
    raise RuntimeError("AI Agent không trả kết quả")


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
            voices = [] if b.lang.startswith("Không") else [r.voice for r in used if r.kind == "NV" and r.voice]
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
