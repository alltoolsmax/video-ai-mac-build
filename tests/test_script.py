"""Tạo kịch bản: tin nhắn gửi AI, đọc / kiểm tra kết quả, cảnh → tác vụ."""
import json

import pytest

from videoai.services import script as S


def brief(**kw):
    b = dict(topic="review", idea="Review serum", total_secs=40, clip_secs=8, ratio="9:16",
             refs=[S.RefImage("NV1", "/a.jpg", "Leda"), S.RefImage("SP1", "/b.jpg"), S.RefImage("BC1", "/c.jpg")])
    b.update(kw)
    return S.Brief(**b)


def test_scene_count_and_message():
    b = brief()
    assert b.n == 5 and S.scene_count(41, 8) == 6 and S.scene_count(1, 8) == 1
    system, user = S.build_message(b)
    assert "ĐÚNG 5 cảnh" in system and "Review sản phẩm" in system and "Móc câu" in system
    assert "Ảnh 1 = NV1 – Nhân vật 1" in user and "Ảnh 2 = SP1" in user and "Ảnh 3 = BC1 – Bối cảnh 1" in user
    assert "SỐ CẢNH: 5" in user and "NV1 = giọng nữ, trẻ trung" in system
    assert '"NV1": "…"' in system and "tối đa 20 chữ" in system
    s2, _ = S.build_message(brief(lang="Không thoại (nhạc nền)", topic="film", total_secs=8))
    assert "KHÔNG có lời thoại" in s2 and "Chỉ có 1 cảnh" in s2 and "3 hồi" in s2
    assert "NHỊP NHANH + NHẠC NỀN" in s2 and "BPM" in s2 and "Muse (Meta)" not in s2      # không thoại → nhịp nhanh + nhạc


def test_muse_script_silent_fast_with_music():
    """Muse + Không thoại: nhịp nhanh, mỗi cảnh ghi nhạc nền; không gửi giọng nói vào tác vụ.
    Muse + Có thoại: viết thoại như bình thường."""
    m, _ = S.build_message(brief(platform="muse", lang="Tiếng Việt"))
    assert "lời thoại trong ngoặc kép và ai nói" in m and "NHỊP NHANH" not in m
    b = brief(platform="muse", lang="Không thoại (nhạc nền)", clip_secs=10, total_secs=30)
    assert b.silent
    system, user = S.build_message(b)
    assert "KHÔNG có lời thoại" in system and "NHỊP NHANH + NHẠC NỀN" in system and "Muse (Meta)" in system
    assert "BPM" in system and "lời thoại trong ngoặc kép và ai nói" not in system and "giọng nữ" not in system
    assert "LỜI THOẠI: Không thoại – nhịp nhanh, có nhạc nền" in user
    sc = [{"time": "", "title": "a", "refs": ["NV1", "SP1"], "frame": "f", "prompt": "p"}] * 3
    refs = [S.RefImage("NV1", "/a.jpg", "Nữ trẻ"), S.RefImage("SP1", "/b.jpg")]
    assert all("voices" not in t["params"] for t in S.to_tasks(b, {"scenes": sc}, refs, chain=False, flow=False))
    f, _ = S.build_message(brief(platform="flow"))                       # Flow vẫn có thoại như cũ
    assert "lời thoại trong ngoặc kép và ai nói" in f and "NHỊP NHANH" not in f


def test_parse_checks():
    good = {"profiles": {"NV1": "x"}, "scenes": [{"title": "a", "refs": ["nv1"], "frame": "f", "prompt": "p  1"},
                                                 {"title": "b", "refs": [], "prompt": "p2"}]}
    r = S.parse("```json\n" + json.dumps(good) + "\n```", 2, ["NV1", "SP1"])
    assert r["scenes"][0]["refs"] == ["NV1"] and r["scenes"][0]["prompt"] == "p 1"
    with pytest.raises(S.ScriptError, match="cần đúng 3"):
        S.parse(json.dumps(good), 3, ["NV1"])
    bad = dict(good, scenes=[dict(good["scenes"][0], refs=["NV9"]), good["scenes"][1]])
    with pytest.raises(S.ScriptError, match="NV9"):
        S.parse(json.dumps(bad), 2, ["NV1"])
    with pytest.raises(S.ScriptError):
        S.parse('{"scenes": [', 2, [])


def test_to_tasks_flow_and_other():
    b = brief(total_secs=16)
    refs = b.refs
    sc = {"scenes": [{"title": "a", "refs": ["NV1", "SP1", "BC1"], "frame": "khung 1", "prompt": "p1"},
                     {"title": "b", "refs": ["SP1"], "frame": "", "prompt": "p2"}]}
    t = S.to_tasks(b, sc, refs, chain=True, flow=True)
    assert t[0]["refs"] == ["/a.jpg", "/b.jpg", "/c.jpg"] and t[0]["params"]["keyframe"] and t[0]["params"]["voices"] == ["Leda"]
    assert t[0]["params"]["frame_prompt"] == "khung 1" and "chain" not in t[0]["params"]
    assert t[1]["params"]["chain"] and t[1]["params"]["scene"] == 2 and "voices" not in t[1]["params"]
    assert t[0]["params"]["script_id"] == t[1]["params"]["script_id"]
    o = S.to_tasks(b, sc, refs, chain=True, flow=False)          # Grok / Muse: khung đầu từ tối đa 4 ảnh, có nối cảnh
    assert o[0]["refs"] == ["/a.jpg", "/b.jpg", "/c.jpg"] and o[0]["params"]["keyframe"] and o[1]["params"]["chain"]
    assert "voices" not in o[0]["params"]
    o2 = S.to_tasks(brief(keyframe=False), sc, refs, chain=False, flow=False)
    assert o2[0]["refs"] == ["/a.jpg"] and "keyframe" not in o2[0]["params"]
    s2, _ = S.build_message(brief(refs=[S.RefImage("NV1", "/a.jpg", "Nam trầm")]))
    assert "NV1 = giọng nam, trưởng thành, trầm ấm" in s2
    q = S.to_tasks(brief(keyframe=False), sc, refs, chain=False, flow=True)
    assert "keyframe" not in q[0]["params"] and len(q[0]["refs"]) == 3


def test_voice_info():
    assert len(S.VOICES) == 29 and S.voice_gender("Leda") == "Nữ" and S.voice_gender("Puck") == "Nam"
    assert S.voice_desc("Leda") == "Nữ, trẻ trung, trung cao"
