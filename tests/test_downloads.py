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
    import json
    info = json.loads((out / "video_win.json").read_text(encoding="utf-8"))
    import hashlib
    assert info["version"] == APP_VERSION and info["sha256"] == hashlib.sha256(setup.read_bytes()).hexdigest()
    # khách tải zip (bên trong đúng 1 tệp exe); tự cập nhật vẫn dùng video_ai_mrhuynh_win.exe
    z = zipfile.ZipFile(out / "video_ai_mrhuynh_win.zip")
    assert z.namelist() == ["video_ai_mrhuynh_win.exe"] and z.read("video_ai_mrhuynh_win.exe") == setup.read_bytes()
    # gói tải lên CHỈ có file cần thiết (không đè trang tải index.html / .htaccess)
    names = zipfile.ZipFile(out.parent / "downloads-upload.zip").namelist()
    assert sorted(names) == ["video_ai_mrhuynh_win.exe", "video_ai_mrhuynh_win.zip", "video_win.json"]
    page = (M.ROOT / "hosting/downloads/index.html").read_text(encoding="utf-8")
    assert "releases/latest/download/video_ai_mrhuynh_win.zip" in page and "releases/latest/download/video_ai_mrhuynh_mac.zip" in page
    bad = tmp_path / "app.exe"
    bad.write_bytes(b"MZ not an installer")
    with pytest.raises(SystemExit):
        M.main(bad)
