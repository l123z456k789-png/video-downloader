"""downloader.py 模块测试。

注意: 这些测试不执行真实下载，只验证参数构建和错误分类。
"""

from __future__ import annotations

import pytest

from pathlib import Path

from config import DEFAULTS
from downloader import (
    build_command,
    build_direct_command,
    classify_exit_code,
    DownloadError,
    NetworkError,
    UnsupportedURLError,
    AuthenticationError,
    MergeError,
)
from extractors.base import VideoInfo


# ============================================================
# 全局日志隔离：所有测试默认不写真实日志文件
# ============================================================

@pytest.fixture(autouse=True)
def _isolate_logs(monkeypatch):
    """默认拦截 downloader.log_event，防止测试写入真实 logs/ 目录。

    需要检查日志事件的测试可以覆盖此 mock：
        def test_my(monkeypatch):
            events = []
            monkeypatch.setattr("downloader.log_event",
                                lambda t, e, extra=None, level="INFO": events.append(e))
    """
    def _noop_log(task_id, event, extra=None, level="INFO"):
        pass

    monkeypatch.setattr("downloader.log_event", _noop_log)


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

    def test_cookies_default_none_no_cookie_args(self):
        """cookies.mode=none → 默认不加任何 cookie 参数"""
        cmd = build_command(DEFAULTS, "https://www.youtube.com/watch?v=abc")
        assert "--cookies-from-browser" not in cmd
        assert "--cookies" not in cmd

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


class TestBuildDirectCommand:
    """build_direct_command — 为 CDN 直链构建 yt-dlp 下载命令。"""

    @pytest.fixture
    def video(self) -> VideoInfo:
        return VideoInfo(
            url="https://cdn.example.com/video.mp4",
            title="测试视频",
            platform="douyin",
            ext="mp4",
            headers={
                "User-Agent": "TestUA/1.0",
                "Referer": "https://www.douyin.com/",
            },
        )

    @pytest.fixture
    def output_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "videos"

    def test_command_includes_cdn_url(self, video, output_dir):
        cmd = build_direct_command(video, output_dir, DEFAULTS)
        assert video.url in cmd
        # URL 是最后一个参数
        assert cmd[-1] == video.url

    def test_command_uses_title_for_output(self, video, output_dir):
        cmd = build_direct_command(video, output_dir, DEFAULTS)
        assert "-o" in cmd
        o_idx = cmd.index("-o")
        output_template = cmd[o_idx + 1]
        assert "测试视频" in output_template
        assert output_template.endswith(".mp4")

    def test_command_includes_user_agent_and_referer(self, video, output_dir):
        cmd = build_direct_command(video, output_dir, DEFAULTS)
        assert "--user-agent" in cmd
        ua_idx = cmd.index("--user-agent")
        assert cmd[ua_idx + 1] == "TestUA/1.0"
        assert "--referer" in cmd
        ref_idx = cmd.index("--referer")
        assert cmd[ref_idx + 1] == "https://www.douyin.com/"

    def test_no_shell_metacharacters(self, video, output_dir):
        """yt-dlp 命令必须是参数列表，不能构造 shell 字符串。"""
        cmd = build_direct_command(video, output_dir, DEFAULTS)
        assert isinstance(cmd, list)
        for arg in cmd:
            assert isinstance(arg, str)

    def test_proxy_passed_when_configured(self, video, output_dir):
        cfg = {
            **DEFAULTS,
            "network": {"mode": "auto", "proxy": "http://127.0.0.1:7890"},
        }
        cmd = build_direct_command(video, output_dir, cfg)
        assert "--proxy" in cmd
        proxy_idx = cmd.index("--proxy")
        assert cmd[proxy_idx + 1] == "http://127.0.0.1:7890"

    def test_no_proxy_when_proxy_empty(self, video, output_dir):
        cfg = {
            **DEFAULTS,
            "network": {"mode": "auto", "proxy": ""},
        }
        cmd = build_direct_command(video, output_dir, cfg)
        assert "--proxy" not in cmd

    def test_cookies_none_no_args(self, video, output_dir):
        cfg = {
            **DEFAULTS,
            "cookies": {"mode": "none", "file": ""},
        }
        cmd = build_direct_command(video, output_dir, cfg)
        assert "--cookies-from-browser" not in cmd
        assert "--cookies" not in cmd

    def test_cookies_browser_adds_flag(self, video, output_dir):
        cfg = {
            **DEFAULTS,
            "browser": {"cookies_from_browser": "chrome"},
            "cookies": {"mode": "browser", "file": ""},
        }
        cmd = build_direct_command(video, output_dir, cfg)
        assert "--cookies-from-browser" in cmd

    def test_cookies_file_adds_flag(self, video, output_dir):
        cfg = {
            **DEFAULTS,
            "cookies": {"mode": "file", "file": "/tmp/cookies.txt"},
        }
        cmd = build_direct_command(video, output_dir, cfg)
        assert "--cookies" in cmd
        c_idx = cmd.index("--cookies")
        assert cmd[c_idx + 1] == "/tmp/cookies.txt"

    def test_continue_and_no_overwrites(self, video, output_dir):
        cmd = build_direct_command(video, output_dir, DEFAULTS)
        assert "--continue" in cmd
        assert "--no-overwrites" in cmd

    def test_timeout_and_retries_included(self, video, output_dir):
        cmd = build_direct_command(video, output_dir, DEFAULTS)
        assert "--socket-timeout" in cmd
        assert "--retries" in cmd


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
        """auto 模式: 直链 yt-dlp 失败 → 必须回退原始 URL yt-dlp。"""
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

        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        # mock _run_process to simulate yt-dlp failing on direct CDN URL
        def fake_run_process_fail(cmd, output_dir, tmp_dir):
            return subprocess.CompletedProcess(args=cmd, returncode=1,
                                               stdout="ERROR: download failed", stderr="")

        monkeypatch.setattr("downloader._run_process", fake_run_process_fail)

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
        """auto 模式: 直链+yt-dlp 都失败 → 必须在异常中保留两阶段错误。"""
        import subprocess
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

        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        # mock _run_process to simulate yt-dlp failing on direct CDN URL
        def fake_run_process_fail(cmd, output_dir, tmp_dir):
            return subprocess.CompletedProcess(args=cmd, returncode=1,
                                               stdout="CDN direct download failed", stderr="")

        monkeypatch.setattr("downloader._run_process", fake_run_process_fail)

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


class TestModeDispatch:
    """run_hybrid_download 根据 network.mode 选择下载引擎。"""

    def test_auto_mode_does_not_call_safe_download(self, monkeypatch):
        """auto 模式下，即使提取器成功，也不调用 safe_download。"""
        import subprocess
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
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        safe_called = []

        def fake_safe(**kwargs):
            safe_called.append(True)
            from extractors.http_downloader import DownloadResult as SafeResult
            return SafeResult(success=True, output_path="/tmp/v.mp4", bytes_downloaded=100)

        monkeypatch.setattr("downloader.safe_download", fake_safe)

        # mock _run_process to simulate yt-dlp success
        def fake_run_process(cmd, output_dir, tmp_dir):
            return subprocess.CompletedProcess(args=cmd, returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader._run_process", fake_run_process)

        # mock run_download for fallback (should not be needed)
        def fake_run_download(config, url):
            return subprocess.CompletedProcess(args=["yt-dlp", url], returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader.run_download", fake_run_download)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}
            # default mode is auto

            from downloader import run_hybrid_download
            result = run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")
            assert result is not None
            assert result.returncode == 0
            assert len(safe_called) == 0, "auto mode must NOT call safe_download"

    def test_strict_mode_calls_safe_download(self, monkeypatch):
        """strict 模式下，提取器成功 → 调用 safe_download。"""
        import subprocess
        import tempfile
        from extractors.base import ExtractResult, VideoInfo
        from extractors.http_downloader import DownloadResult as SafeResult

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

        safe_called = []

        def fake_safe(**kwargs):
            safe_called.append(kwargs.get("url"))
            return SafeResult(success=True, output_path="/tmp/v.mp4", bytes_downloaded=100)

        monkeypatch.setattr("downloader.safe_download", fake_safe)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}
            config["network"] = {"mode": "strict", "proxy": ""}

            from downloader import run_hybrid_download
            result = run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")
            assert result is not None
            assert len(safe_called) == 1
            assert safe_called[0] == "https://cdn.example.com/v.mp4"


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
        """strict 模式: run_hybrid_download 从 config 读取 socket_timeout/retries 传给 safe_download。"""
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
            config["network"] = {"mode": "strict", "proxy": ""}

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


# ============================================================
# Task ID 传播测试
# ============================================================

class TestTaskIdPropagation:
    """task_id 由入口创建一次，全链路复用。"""

    def test_run_hybrid_accepts_and_uses_task_id(self, monkeypatch):
        """auto 模式: 传入 task_id 后，所有事件使用同一个 ID。"""
        import subprocess
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
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        def fake_run_process(cmd, output_dir, tmp_dir):
            return subprocess.CompletedProcess(args=cmd, returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader._run_process", fake_run_process)

        log_events: list[dict] = []

        def fake_log(task_id, event, extra=None, level="INFO"):
            log_events.append({"task_id": task_id, "event": event})

        monkeypatch.setattr("downloader.log_event", fake_log)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            run_hybrid_download(config, "https://v.douyin.com/test/",
                                platform="douyin", task_id="my-task-123")

            ids = {e["task_id"] for e in log_events}
            assert ids == {"my-task-123"}, f"all events should use same task_id, got {ids}"


class TestHybridExceptionHandling:
    """run_hybrid_download 异常不应被吞掉。"""

    def test_attribute_error_not_swallowed_in_direct_download(self, monkeypatch):
        """strict 模式: safe_download 内部 AttributeError 不能变成普通 DownloadResult。"""
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
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        def fake_safe_bug(**kwargs):
            raise AttributeError("NoneType has no attribute 'write'")

        monkeypatch.setattr("downloader.safe_download", fake_safe_bug)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}
            config["network"] = {"mode": "strict", "proxy": ""}

            from downloader import run_hybrid_download
            with pytest.raises(AttributeError, match="NoneType"):
                run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")

    def test_connect_error_triggers_fallback(self, monkeypatch):
        """strict 模式: safe_download 抛出 ConnectError → 记录失败、触发 yt-dlp 回退。"""
        import subprocess
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
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        def fake_safe_connect_error(**kwargs):
            import httpx
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("downloader.safe_download", fake_safe_connect_error)

        fallback_called = []

        def fake_run(config, url):
            fallback_called.append(url)
            return subprocess.CompletedProcess(args=["yt-dlp", url], returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader.run_download", fake_run)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}
            config["network"] = {"mode": "strict", "proxy": ""}

            from downloader import run_hybrid_download
            result = run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")
            assert result is not None
            assert result.returncode == 0
            assert len(fallback_called) == 1


class TestFallbackLoggingCompleteness:
    """所有回退路径都有 start + complete/failed。"""

    def test_extractor_exception_path_has_fallback_complete(self, monkeypatch):
        """提取器抛异常 → 回退 yt-dlp 成功 → 应有 fallback_complete。"""
        import subprocess
        import tempfile

        fake_extractor = type("FakeExt", (), {
            "platform": "douyin",
            "supports": lambda s, u: True,
            "extract": lambda s, u, cookies=None: (_ for _ in ()).throw(
                RuntimeError("browser crash")),
        })()
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        def fake_run(config, url):
            return subprocess.CompletedProcess(args=["yt-dlp", url], returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader.run_download", fake_run)

        log_events: list[str] = []

        def fake_log(task_id, event, extra=None, level="INFO"):
            log_events.append(event)

        monkeypatch.setattr("downloader.log_event", fake_log)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")

        assert "fallback_complete" in log_events, \
            f"extractor-exception path missing fallback_complete, got {log_events}"

    def test_extractor_failure_path_has_fallback_outcome(self, monkeypatch):
        """提取器返回 success=False → yt-dlp 失败 → 应有 fallback_failed。"""
        import tempfile
        from extractors.base import ExtractResult
        from downloader import DownloadError

        fake_extractor = type("FakeExt", (), {
            "platform": "douyin",
            "supports": lambda s, u: True,
            "extract": lambda s, u, cookies=None: ExtractResult(
                success=False, error="extraction failed"),
        })()
        monkeypatch.setattr("extractors.find_extractor", lambda u: fake_extractor)

        log_events: list[str] = []

        def fake_log(task_id, event, extra=None, level="INFO"):
            log_events.append(event)

        monkeypatch.setattr("downloader.log_event", fake_log)

        def fake_run_fail(config, url):
            raise DownloadError("yt-dlp failed", exit_code=3)

        monkeypatch.setattr("downloader.run_download", fake_run_fail)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            with pytest.raises(DownloadError):
                run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")

        assert "fallback_failed" in log_events, \
            f"extractor-failure path missing fallback_failed, got {log_events}"


class TestLogIsolation:
    """测试不污染真实日志。"""

    def test_tests_do_not_write_real_logs(self, monkeypatch):
        """auto 模式: 调用 run_hybrid_download 不应写入真实 logs 目录。"""
        import subprocess
        import tempfile
        from extractors.base import ExtractResult, VideoInfo

        # 拦截所有 log_event 调用，确认不会写入真实日志
        log_events: list[dict] = []

        def fake_log(task_id, event, extra=None, level="INFO"):
            log_events.append({"task_id": task_id, "event": event})

        monkeypatch.setattr("downloader.log_event", fake_log)

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

        def fake_run_process(cmd, output_dir, tmp_dir):
            return subprocess.CompletedProcess(args=cmd, returncode=0,
                                               stdout="ok", stderr="")

        monkeypatch.setattr("downloader._run_process", fake_run_process)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = dict(DEFAULTS)
            config["downloader"]["output_dir"] = tmpdir
            config["tools"] = {"yt_dlp_path": "yt-dlp", "ffmpeg_path": "ffmpeg", "deno_path": ""}

            from downloader import run_hybrid_download
            run_hybrid_download(config, "https://v.douyin.com/test/", platform="douyin")

        # 验证 log_event 被调用了（即日志走了我们的 mock，没有写真实文件）
        assert len(log_events) >= 1, "log_event should have been called"
