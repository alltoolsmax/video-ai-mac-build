"""Flow: giãn nhịp 10–20 giây giữa 2 tác vụ cùng tài khoản (các nền tảng khác giữ nguyên cài đặt)."""
import os

from videoai.core.engine import FLOW_MIN_REST, rest_bounds


def test_flow_forces_min_rest(monkeypatch):
    monkeypatch.delenv("VIDEOAI_HEADLESS", raising=False)       # giả lập máy thật
    assert rest_bounds("flow", (0, 0)) == FLOW_MIN_REST         # dù người dùng tắt giãn nhịp
    assert rest_bounds("flow", (5, 8)) == (10, 20)              # nâng lên mức tối thiểu của Flow
    assert rest_bounds("flow", (30, 60)) == (30, 60)            # người dùng đặt cao hơn thì giữ nguyên


def test_other_platforms_unchanged(monkeypatch):
    monkeypatch.delenv("VIDEOAI_HEADLESS", raising=False)
    assert rest_bounds("muse", (0, 0)) == (0, 0)
    assert rest_bounds("grok", (3, 5)) == (3, 5)


def test_disabled_during_tests(monkeypatch):
    monkeypatch.setenv("VIDEOAI_HEADLESS", "1")
    assert rest_bounds("flow", (0, 0)) == (0, 0)                # kiểm thử không chờ 10–20 giây
