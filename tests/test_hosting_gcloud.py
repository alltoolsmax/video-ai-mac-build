"""GCloud Hub: Mac tự cập nhật từ bản GitHub build (gcloud_mac.json), Windows vẫn theo bản đã bấm Phát hành."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("php"), reason="cần php")


def test_gcloud_mac_from_github(tmp_path):
    priv = tmp_path / "priv"
    priv.mkdir()
    shutil.copy(ROOT / "may-chu-chung/gcloud-hub/active_private/gcloudhub/lib.php", priv / "lib.php")
    mj = tmp_path / "gcloud_mac.json"
    mj.write_text(json.dumps({"version": "1.1.9", "apple": {"file": "gcloud_hub_mac_apple.dmg", "sha256": "a" * 64, "size": 1},
                              "intel": {"file": "gcloud_hub_mac_intel.dmg", "sha256": "b" * 64, "size": 2}}))

    def ask(q):
        s = tmp_path / "t.php"
        s.write_text("<?php\nrequire " + json.dumps(str(priv / "lib.php")) + ";\nparse_str(" + json.dumps(q) + ", $_GET); GCloudHub\\api_version();")
        out = subprocess.run(["php", str(s)], capture_output=True, text=True, timeout=60,
                             env={"GCLOUDHUB_PRIVATE": str(priv), "GCLOUDHUB_MAC_JSON": str(mj), "PATH": "/usr/bin:/bin"})
        return json.loads(out.stdout)
    a = ask("os=mac&arch=arm64&iid=abcdefgh123&v=1.1.8")
    assert a["version"] == "1.1.9" and a["url"] == "https://github.com/alltoolsmax/gcloud-hub-build/releases/download/v1.1.9/gcloud_hub_mac_apple.dmg"
    assert ask("os=mac&arch=x64")["sha256"] == "b" * 64
    assert ask("os=win")["version"] == "0.0.0"          # Windows: chỉ bản đã bấm Phát hành
