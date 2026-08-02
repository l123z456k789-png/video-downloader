"""downloader.py 模块测试。

注意: 这些测试不执行真实下载，只验证参数构建和错误分类。
"""

from __future__ import annotations

import pytest

from config import DEFAULTS
from downloader import (
    build_command,
    classify_exit_code,
    DownloadError,
    NetworkError,
    UnsupportedURLError,
    AuthenticationError,
    MergeError,
)


class TestBuildCommand:
    def test_basic_command_structure(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        # yt-dlp 路径
        assert cmd[0] == "yt-dlp"
        # 必须有 -f
        assert "-f" in cmd
        # 必须有 URL
        assert cmd[-1] == "https://www.youtube.com/watch?v=abc"
        # 使用了参数列表，不是 shell 字符串
        assert isinstance(cmd, list)
        for arg in cmd:
            assert isinstance(arg, str)

    def test_no_playlist(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "--no-playlist" in cmd

    def test_no_overwrites(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "--no-overwrites" in cmd

    def test_output_template_present(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "-o" in cmd
        o_idx = cmd.index("-o")
        assert "%(title)s.%(ext)s" in cmd[o_idx + 1]

    def test_timeout_and_retries(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "--socket-timeout" in cmd
        timeout_idx = cmd.index("--socket-timeout")
        assert cmd[timeout_idx + 1] == "30"

        assert "--retries" in cmd
        retries_idx = cmd.index("--retries")
        assert cmd[retries_idx + 1] == "5"

    def test_cookies_from_browser_default(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "--cookies-from-browser" in cmd

    def test_ffmpeg_postprocessor_args(self):
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "--postprocessor-args" in cmd
        pp_idx = cmd.index("--postprocessor-args")
        assert "aac" in cmd[pp_idx + 1]

    def test_no_shell_injection(self):
        """确保 URL 不会被 shell 解释。"""
        malicious_url = "https://youtube.com/watch?v=abc&rm -rf /"
        cmd = build_command(DEFAULTS, malicious_url)
        # shell 元字符不应该被拆分成多个参数
        assert "&rm" not in cmd
        # 整个 URL 应该是一个参数
        assert malicious_url in cmd


class TestExitCodeClassification:
    def test_success(self):
        error_type, user_msg = classify_exit_code(0)
        assert error_type == "成功"

    def test_network_error(self):
        error_type, user_msg = classify_exit_code(3)
        assert "网络" in error_type

    def test_unsupported_url(self):
        error_type, user_msg = classify_exit_code(5)
        assert "不支持的链接" in error_type

    def test_authentication_error(self):
        error_type, user_msg = classify_exit_code(4)
        assert "访问被拒绝" in error_type

    def test_unknown_exit_code(self):
        error_type, user_msg = classify_exit_code(99)
        assert "未知" in error_type
        assert "99" in user_msg


class TestDownloadErrorHierarchy:
    def test_network_error_is_download_error(self):
        err = NetworkError("test")
        assert isinstance(err, DownloadError)

    def test_auth_error_is_download_error(self):
        err = AuthenticationError("test")
        assert isinstance(err, DownloadError)

    def test_error_carries_exit_code(self):
        err = NetworkError("test", exit_code=3)
        assert err.exit_code == 3
