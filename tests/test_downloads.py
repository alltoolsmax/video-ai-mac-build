"""Trang tải mrhuynh.net/downloads/: tên cố định, .htaccess chống lưu đệm + HTTPS, trang hướng dẫn có phiên bản."""
import zipfile

import pytest


def test_make_downloads(tmp_path, monkeypatch):
    import tools.make_downloads as M
    from videoai.core.paths import APP_VERSION
    monkeypatch.setattr(M, "ROOT", M.ROOT)
    setup = tmp_path / "VideoAI-MrHuynh-Setup-x.exe"
    setup.write_bytes(b"MZ" + b"\0" * 1000 + b"Inno Setup Setup Data" + b"\0" * 5000)
    out = M.main(setup)
    assert (out / "video_ai_mrhuynh_win.exe").read_bytes() == setup.read_bytes()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert APP_VERSION in html and 'href="video_ai_mrhuynh_win.zip"' in html and "Vẫn chạy" in html
    # khách tải zip (bên trong đúng 1 tệp exe); tự cập nhật vẫn dùng video_ai_mrhuynh_win.exe
    z = zipfile.ZipFile(out / "video_ai_mrhuynh_win.zip")
    assert z.namelist() == ["video_ai_mrhuynh_win.exe"] and z.read("video_ai_mrhuynh_win.exe") == setup.read_bytes()
    ht = (out / ".htaccess").read_text(encoding="utf-8")
    assert "no-store" in ht and "attachment" in ht and "RewriteRule" in ht
    names = zipfile.ZipFile(out.parent / "downloads-upload.zip").namelist()
    assert sorted(names) == [".htaccess", "index.html", "video_ai_mrhuynh_win.exe", "video_ai_mrhuynh_win.zip"]
    assert "filename=video_ai_mrhuynh_win.zip" in ht and "filename=video_ai_mrhuynh_mac.zip" in ht
    bad = tmp_path / "app.exe"
    bad.write_bytes(b"MZ not an installer")
    with pytest.raises(SystemExit):
        M.main(bad)
