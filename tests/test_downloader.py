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


class TestHybridFallback:
    """run_hybrid_download 在直链下载失败时回退 yt-dlp。"""

    def test_fallback_when_direct_download_fails(self, monkeypatch):
        """提取器成功但 safe_download 失败 → 必须回退 yt-dlp。"""
        import subprocess
        import tempfile
        from pathlib import Path

        from extractors.base import ExtractResult, VideoInfo

        fake_extractor = type("FakeExt", (), {
            "platform": "douyin",
            "supports": lambda s, u: True,
            "extract": lambda s, u, cookies=None: ExtractResult(
                success=True,
                videos=[VideoInfo(url="https://cdn.example.com/v.mp4",
                                   title="test", platform="douyin", ext="mp4")],
            ),
        })()

        def fake_find(url):
            return fake_extractor

        monkeypatch.setattr("extractors.find_extractor", fake_find)

        from extractors.http_downloader import DownloadResult as SafeResult

        def fake_safe(**kwargs):
            return SafeResult(success=False, output_path="", bytes_downloaded=0,
                              error="Connection refused")

        monkeypatch.setattr("downloader.safe_download", fake_safe)

        def fake_run(config, url):
            return subprocess.CompletedProcess(args=["yt-dlp", url], returncode=0,
                                               stdout="download ok", stderr="")

        monkeypatch.setattr("downloader.run_download", fake_run)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            result = run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")
            assert result is not None
            assert result.returncode == 0

    def test_error_context_when_both_paths_fail(self, monkeypatch):
        """提取器+yt-dlp 都失败 → 必须在异常中保留两阶段错误。"""
        import tempfile
        from extractors.base import ExtractResult, VideoInfo

        fake_extractor = type("FakeExt", (), {
            "platform": "douyin",
            "supports": lambda s, u: True,
            "extract": lambda s, u, cookies=None: ExtractResult(
                success=True,
                videos=[VideoInfo(url="https://cdn.example.com/v.mp4",
                                   title="test", platform="douyin", ext="mp4")],
            ),
        })()

        def fake_find(url):
            return fake_extractor

        monkeypatch.setattr("extractors.find_extractor", fake_find)

        from extractors.http_downloader import DownloadResult as SafeResult

        def fake_safe(**kwargs):
            return SafeResult(success=False, output_path="", bytes_downloaded=0,
                              error="CDN direct download failed")

        monkeypatch.setattr("downloader.safe_download", fake_safe)

        from downloader import DownloadError

        def fake_run_fail(config, url):
            raise DownloadError("yt-dlp also failed: network unreachable", exit_code=3)

        monkeypatch.setattr("downloader.run_download", fake_run_fail)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download

            with pytest.raises(DownloadError) as exc_info:
                run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")

            err_msg = str(exc_info.value)
            assert "CDN direct download failed" in err_msg or \
                   "yt-dlp also failed" in err_msg

    def test_fallback_when_extractor_fails(self, monkeypatch):
        """提取器失败 → 直接回退 yt-dlp（现有逻辑不变）。"""
        import subprocess
        import tempfile

        from extractors.base import ExtractResult

        fake_extractor = type("FakeExt", (), {
            "platform": "douyin",
            "supports": lambda s, u: True,
            "extract": lambda s, u, cookies=None: ExtractResult(
                success=False, error="extraction failed"),
        })()

        def fake_find(url):
            return fake_extractor

        monkeypatch.setattr("extractors.find_extractor", fake_find)

        def fake_run(config, url):
            return subprocess.CompletedProcess(args=["yt-dlp", url], returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader.run_download", fake_run)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            result = run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")
            assert result is not None
            assert result.returncode == 0


class TestConfigPlumbing:
    """配置贯通 — DownloadConfig 接收 retries/socket_timeout。"""

    def test_download_config_accepts_timeout_and_retries(self):
        from extractors.http_downloader import DownloadConfig

        c = DownloadConfig(
            connect_timeout=15.0,
            read_timeout=120.0,
            max_retries=5,
        )
        assert c.connect_timeout == 15.0
        assert c.read_timeout == 120.0
        assert c.max_retries == 5

    def test_run_hybrid_download_passes_config_to_safe_download(self, monkeypatch):
        """run_hybrid_download 必须从 config 读取 socket_timeout/retries 传给 safe_download。"""
        import subprocess
        import tempfile
        from extractors.base import ExtractResult, VideoInfo
        from extractors.http_downloader import DownloadResult as SafeResult, DownloadConfig

        fake_extractor = type("FakeExt", (), {
            "platform": "douyin",
            "supports": lambda s, u: True,
            "extract": lambda s, u, cookies=None: ExtractResult(
                success=True,
                videos=[VideoInfo(url="https://cdn.example.com/v.mp4",
                                   title="test", platform="douyin", ext="mp4")],
            ),
        })()
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        received_config: list[DownloadConfig] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            def capture_safe(**kwargs):
                cfg = kwargs.get("config")
                if cfg is not None:
                    received_config.append(cfg)
                return SafeResult(success=True, output_path=tmpdir + "/v.mp4",
                                  bytes_downloaded=100)

            monkeypatch.setattr("downloader.safe_download", capture_safe)

            def fake_run(config, url):
                return subprocess.CompletedProcess(args=["yt-dlp"], returncode=0,
                                                   stdout="", stderr="")

            monkeypatch.setattr("downloader.run_download", fake_run)

            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["downloader"]["retries"] = 3
            config["downloader"]["socket_timeout"] = 45
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")

            assert len(received_config) >= 1
            cfg = received_config[0]
            assert cfg.connect_timeout == 45.0
            assert cfg.read_timeout == 300.0  # default preserved
            assert cfg.max_retries == 3


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
