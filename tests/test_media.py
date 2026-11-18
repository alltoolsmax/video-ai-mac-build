"""Kiểm thử công cụ video bằng ffmpeg thật."""
import json
from pathlib import Path

from videoai.media import capcut, ffmpeg


def test_cut_and_frames(tmp_path, clip):
    parts = ffmpeg.cut_segments(clip, str(tmp_path / "cut"), 1.0)
    assert len(parts) == 3 and all(p.exists() for p in parts)
    assert abs(ffmpeg.duration(parts[0]) - 1.0) < 0.2
    last = ffmpeg.extract_frame(clip, str(tmp_path / "last.png"), "last")
    first = ffmpeg.extract_frame(clip, str(tmp_path / "first.png"), "first")
    assert last.stat().st_size > 1000 and first.stat().st_size > 1000
    frames = ffmpeg.extract_every(clip, str(tmp_path / "fr"), 1)
    assert len(frames) >= 3


def test_concat_music_subs(tmp_path, clip):
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nXin chào Việt Nam\n", encoding="utf-8")
    music = tmp_path / "m.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=220:duration=2", str(music)])
    out = ffmpeg.concat([clip, clip], str(tmp_path / "out.mp4"), (640, 360), 30, str(music), 0.3, True, str(srt), 0.3)
    assert 5.5 < ffmpeg.duration(out) < 6.5
    assert ffmpeg.has_audio(out)


def test_convert_ops(tmp_path, clip):
    v = ffmpeg.reframe(clip, str(tmp_path / "v.mp4"), "9:16", "blur")
    s = next(x for x in ffmpeg.probe(v)["streams"] if x["codec_type"] == "video")
    assert (s["width"], s["height"]) == (1080, 1920)
    ffmpeg.reframe(clip, str(tmp_path / "c.mp4"), "9:16", "crop")
    sp = ffmpeg.speed(clip, str(tmp_path / "sp.mp4"), 1.5)
    assert abs(ffmpeg.duration(sp) - 2.0) < 0.2
    m = ffmpeg.remove_audio(clip, str(tmp_path / "m.mp4"))
    assert not ffmpeg.has_audio(m)
    logo = tmp_path / "logo.png"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=red:s=200x100", "-frames:v", "1", str(logo)])
    assert ffmpeg.add_logo(clip, str(logo), str(tmp_path / "l.mp4")).exists()


def test_slideshow(tmp_path):
    ims = []
    for i, c in enumerate(("red", "blue")):
        p = tmp_path / f"{i}.png"
        ffmpeg.run(["-f", "lavfi", "-i", f"color=c={c}:s=800x600", "-frames:v", "1", str(p)])
        ims.append(str(p))
    out = ffmpeg.images_to_video(ims, str(tmp_path / "s.mp4"), 1.0, (640, 360), 25)
    assert 1.8 < ffmpeg.duration(out) < 2.3


def test_capcut_draft(tmp_path, clip):
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nA\n", encoding="utf-8")
    d = capcut.export_draft("Thử nghiệm", [clip, clip], str(srt), None, root=str(tmp_path / "drafts"))
    c = json.loads((d / "draft_content.json").read_text(encoding="utf-8"))
    assert len(c["tracks"][0]["segments"]) == 2
    seg2 = c["tracks"][0]["segments"][1]
    assert seg2["target_timerange"]["start"] == c["tracks"][0]["segments"][0]["target_timerange"]["duration"]
    assert any(t["type"] == "text" for t in c["tracks"])
    assert (d / "draft_meta_info.json").exists() and len(list((d / "media").iterdir())) == 1
    f = capcut.export_folder([clip, clip], str(tmp_path / "fold"), str(srt))
    assert sorted(p.name for p in f.iterdir())[0].startswith("001_")


def test_upscale_fallback(tmp_path):
    from videoai.media import upscale
    p = tmp_path / "a.png"
    ffmpeg.run(["-f", "lavfi", "-i", "color=c=green:s=100x80", "-frames:v", "1", str(p)])
    o = upscale.upscale_ffmpeg(str(p), str(tmp_path / "b.png"), 2)
    s = ffmpeg.probe(o)["streams"][0]
    assert (s["width"], s["height"]) == (200, 160)
