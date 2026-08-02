"""extractors/http_downloader.py 安全测试。

所有测试禁止真实网络访问，使用 httpx.MockTransport、monkeypatch、
临时目录、伪造 DNS。
"""
from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path

import httpx
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


# ============================================================
# URL 校验测试
# ============================================================

class TestValidateUrl:
    """_validate_url() 协议、userinfo、域名白名单测试。"""

    def test_accepts_https_url(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("https://example.com/video.mp4", None)
        assert ok is True
        assert err == ""

    def test_accepts_http_url(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("http://example.com/video.mp4", None)
        assert ok is True

    def test_rejects_file_protocol(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("file:///etc/passwd", None)
        assert ok is False
        assert "协议" in err or "protocol" in err.lower()

    def test_rejects_ftp_protocol(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("ftp://example.com/file", None)
        assert ok is False

    def test_rejects_data_protocol(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("data:text/html,<script>alert(1)</script>", None)
        assert ok is False

    def test_rejects_javascript_protocol(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("javascript:alert(1)", None)
        assert ok is False

    def test_rejects_userinfo_in_url(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("https://user:password@example.com/video", None)
        assert ok is False
        assert "用户" in err or "user" in err.lower() or "密码" in err.lower() or "credential" in err.lower()

    def test_rejects_empty_hostname(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("https:///path", None)
        assert ok is False

    def test_allowed_domains_exact_match(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url(
            "https://cdn.example.com/video.mp4",
            ["cdn.example.com"],
        )
        assert ok is True

    def test_allowed_domains_subdomain_match(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url(
            "https://a.b.cdn.example.com/video.mp4",
            ["cdn.example.com"],
        )
        assert ok is True

    def test_allowed_domains_rejects_lookalike_suffix(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url(
            "https://cdn.example.com.evil.com/video.mp4",
            ["cdn.example.com"],
        )
        assert ok is False

    def test_allowed_domains_rejects_partial_match(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url(
            "https://evilcdn.example.com/video.mp4",
            ["cdn.example.com"],
        )
        assert ok is False

    def test_allowed_domains_case_insensitive(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url(
            "https://CDN.Example.COM/video.mp4",
            ["cdn.example.com"],
        )
        assert ok is True

    def test_none_allowed_domains_accepts_any(self):
        from extractors.http_downloader import _validate_url
        ok, err = _validate_url("https://any-random-domain.io/video.mp4", None)
        assert ok is True


# ============================================================
# IP 安全检查测试
# ============================================================

class TestIsIpPublic:
    """_is_ip_public() 测试。"""

    def test_public_ipv4(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("8.8.8.8") is True
        assert _is_ip_public("1.1.1.1") is True

    def test_private_ipv4_10(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("10.0.0.1") is False
        assert _is_ip_public("10.255.255.255") is False

    def test_private_ipv4_172_16(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("172.16.0.1") is False
        assert _is_ip_public("172.31.255.255") is False

    def test_private_ipv4_192_168(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("192.168.1.1") is False

    def test_loopback_ipv4(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("127.0.0.1") is False
        assert _is_ip_public("127.255.255.255") is False

    def test_link_local_ipv4(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("169.254.1.1") is False

    def test_multicast_ipv4(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("224.0.0.1") is False

    def test_reserved_ipv4(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("240.0.0.1") is False

    def test_unspecified_ipv4(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("0.0.0.0") is False

    def test_loopback_ipv6(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("::1") is False

    def test_link_local_ipv6(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("fe80::1") is False

    def test_private_ipv6(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("fd00::1") is False
        assert _is_ip_public("fc00::1") is False

    def test_public_ipv6(self):
        from extractors.http_downloader import _is_ip_public
        assert _is_ip_public("2001:4860:4860::8888") is True


class TestResolvePublicIps:
    """_resolve_public_ips() 测试。"""

    def test_returns_public_ips(self, monkeypatch):
        from extractors.http_downloader import _resolve_public_ips

        def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
        ips = _resolve_public_ips("cdn.example.com")
        assert "8.8.8.8" in ips
        assert "1.1.1.1" in ips

    def test_rejects_all_private(self, monkeypatch):
        from extractors.http_downloader import _resolve_public_ips

        def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
        with pytest.raises(OSError):
            _resolve_public_ips("evil.internal")

    def test_rejects_mixed_public_private(self, monkeypatch):
        from extractors.http_downloader import _resolve_public_ips

        def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
        with pytest.raises(OSError):
            _resolve_public_ips("mixed.internal")

    def test_dns_failure(self, monkeypatch):
        from extractors.http_downloader import _resolve_public_ips

        def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
        with pytest.raises(OSError):
            _resolve_public_ips("nonexistent.example")


# ============================================================
# 文件名安全检查测试
# ============================================================

class TestValidateFilename:
    """_validate_filename() 测试。"""

    def test_accepts_clean_filename(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        result = _validate_filename("video.mp4", tmp_path)
        assert result.name == "video.mp4"
        assert result.parent == tmp_path.resolve()

    def test_rejects_absolute_path(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("/etc/passwd", tmp_path)

    def test_rejects_parent_traversal(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("../../../etc/passwd", tmp_path)

    def test_rejects_backslash_traversal(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("..\\..\\windows\\system32", tmp_path)

    def test_rejects_null_byte(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("video\x00.mp4", tmp_path)

    def test_rejects_control_characters(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("video\x01\x02.mp4", tmp_path)

    def test_rejects_windows_reserved_con(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("CON", tmp_path)
        with pytest.raises(ValueError):
            _validate_filename("con.mp4", tmp_path)

    def test_rejects_windows_reserved_prn(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("PRN", tmp_path)

    def test_rejects_windows_reserved_nul(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("NUL", tmp_path)

    def test_rejects_windows_reserved_aux(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("AUX", tmp_path)

    def test_rejects_windows_reserved_com1_through_com9(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        for name in ["COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9"]:
            with pytest.raises(ValueError):
                _validate_filename(name, tmp_path)

    def test_rejects_windows_reserved_lpt1_through_lpt9(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        for name in ["LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]:
            with pytest.raises(ValueError):
                _validate_filename(name, tmp_path)

    def test_rejects_trailing_space(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("video.mp4 ", tmp_path)

    def test_rejects_trailing_dot(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("video.", tmp_path)

    def test_rejects_empty_filename(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("", tmp_path)

    def test_rejects_path_separator_in_name(self, tmp_path):
        from extractors.http_downloader import _validate_filename
        with pytest.raises(ValueError):
            _validate_filename("subdir/video.mp4", tmp_path)


# ============================================================
# Content-Type 校验测试
# ============================================================

class TestValidateContentType:
    """Content-Type 校验测试。"""

    def test_accepts_video_mp4(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("video/mp4")
        assert ok is True

    def test_accepts_video_any(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("video/webm")
        assert ok is True
        ok = _validate_content_type("video/ogg")
        assert ok is True

    def test_accepts_octet_stream(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("application/octet-stream")
        assert ok is True

    def test_rejects_text_html(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("text/html")
        assert ok is False

    def test_rejects_application_json(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("application/json")
        assert ok is False

    def test_rejects_text_plain(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("text/plain")
        assert ok is False

    def test_rejects_application_xml(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("application/xml")
        assert ok is False

    def test_strips_charset_parameter(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("video/mp4; charset=utf-8")
        assert ok is True

    def test_rejects_missing_content_type(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("")
        assert ok is False

    def test_case_insensitive(self):
        from extractors.http_downloader import _validate_content_type
        ok = _validate_content_type("VIDEO/MP4")
        assert ok is True

    def test_custom_allowed_types(self):
        from extractors.http_downloader import (
            _validate_content_type,
            DownloadConfig,
        )
        cfg = DownloadConfig(allowed_content_types=("image/",))
        ok = _validate_content_type("image/png", cfg)
        assert ok is True
        ok = _validate_content_type("video/mp4", cfg)
        assert ok is False
