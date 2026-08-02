"""extractors/http_downloader.py 安全测试。

所有测试禁止真实网络访问，使用 httpx.MockTransport、monkeypatch、
临时目录、伪造 DNS。
"""
from __future__ import annotations

import pytest


class TestDownloadConfig:
    """DownloadConfig frozen dataclass 行为测试。"""

    def test_default_values(self):
        from extractors.http_downloader import DownloadConfig
        c = DownloadConfig()
        assert c.max_size_bytes == 2 * 1024 * 1024 * 1024
        assert c.connect_timeout == 30.0
        assert c.read_timeout == 300.0
        assert c.total_timeout == 600.0
        assert c.min_speed_bytes_per_sec == 1024
        assert c.min_speed_window_sec == 30.0
        assert c.max_redirects == 3
        assert c.overwrite is False
        assert c.disk_safety_ratio == 1.2
        assert c.disk_check_interval_bytes == 64 * 1024 * 1024
        assert "video/" in c.allowed_content_types
        assert "application/octet-stream" in c.allowed_content_types

    def test_custom_values(self):
        from extractors.http_downloader import DownloadConfig
        c = DownloadConfig(max_size_bytes=100, connect_timeout=5.0)
        assert c.max_size_bytes == 100
        assert c.connect_timeout == 5.0
        assert c.read_timeout == 300.0

    def test_frozen(self):
        from extractors.http_downloader import DownloadConfig
        c = DownloadConfig()
        with pytest.raises(Exception):
            c.max_size_bytes = 999


class TestDownloadResult:
    """DownloadResult frozen dataclass 行为测试。"""

    def test_success_result(self):
        from extractors.http_downloader import DownloadResult
        r = DownloadResult(success=True, output_path="/tmp/v.mp4", bytes_downloaded=1024)
        assert r.success is True
        assert r.output_path == "/tmp/v.mp4"
        assert r.bytes_downloaded == 1024
        assert r.error == ""

    def test_failure_result(self):
        from extractors.http_downloader import DownloadResult
        r = DownloadResult(
            success=False, output_path="", bytes_downloaded=0,
            error="Connection refused"
        )
        assert r.success is False
        assert r.error == "Connection refused"

    def test_frozen(self):
        from extractors.http_downloader import DownloadResult
        r = DownloadResult(success=True, output_path="x", bytes_downloaded=0)
        with pytest.raises(Exception):
            r.success = False
