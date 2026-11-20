"""Kiểm thử công cụ video bằng ffmpeg thật."""
import os
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


def _serve_clip(tmp_path):
    import functools, threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from videoai.media import ffmpeg
    clip = tmp_path / "srv" / "clip.mp4"
    clip.parent.mkdir()
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc=size=160x120:rate=25", "-f", "lavfi", "-i", "sine=f=440",
                "-t", "1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(clip)])

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(clip.parent)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/clip.mp4"


def test_downloader_args_links_and_errors():
    from videoai.media import downloader as dl
    assert dl.split_links("a https://youtu.be/x, b\nhttps://www.tiktok.com/@u/video/1 https://youtu.be/x") == \
        ["https://youtu.be/x", "https://www.tiktok.com/@u/video/1"]
    assert dl.platform_of("https://vt.tiktok.com/abc") == "TikTok"
    assert dl.platform_of("https://fb.watch/xyz") == "Facebook"
    assert dl.platform_of("https://youtu.be/x") == "YouTube"
    a = dl.build_args("https://www.tiktok.com/@u/video/1", "/tmp/o", "720p (MP4)", "firefox")
    f = a[a.index("-f") + 1]
    assert f.startswith("bv*[format_note!*=?watermark]")            # TikTok: luồng không logo trước
    assert a[a.index("-S") + 1].startswith("res:720") and a[-2:] == ["--", "https://www.tiktok.com/@u/video/1"]
    assert "--cookies-from-browser" in a
    assert "-x" in dl.build_args("u", "/tmp/o", "Chỉ âm thanh (MP3)")
    k, v = dl.parse_line("PRG| 45.5%|3.20MiB/s|00:04\n")
    assert k == "progress" and v.percent == 45.5 and v.eta == "00:04"
    assert dl.parse_line("PRG|100.0%|Unknown B/s|NA")[1].eta == ""
    assert "riêng tư" in dl.friendly_error("ERROR: [youtube] x: Private video. Sign in")
    assert "đăng nhập" in dl.friendly_error("ERROR: Sign in to confirm you're not a bot")


def test_downloader_real_http(tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("yt_dlp")
    from videoai.media import downloader as dl
    monkeypatch.setenv("VIDEOAI_HOME", str(tmp_path / "home"))
    srv, url = _serve_clip(tmp_path)
    try:
        ev = []
        f = dl.download(url, str(tmp_path / "out"), on_event=lambda k, v: ev.append(k))
        assert f.endswith(".mp4") and os.path.getsize(f) > 1000
        assert "title" in ev and "progress" in ev
        mp3 = dl.download(url, str(tmp_path / "out"), "Chỉ âm thanh (MP3)")
        assert mp3.endswith(".mp3")
    finally:
        srv.shutdown()
