"""extractors/http_downloader.py 安全测试。

所有测试禁止真实网络访问，使用 httpx.MockTransport、monkeypatch、
临时目录、伪造 DNS。
"""
from __future__ import annotations

import os
import shutil
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


# ============================================================
# DNS 重绑定 / 安全传输测试
# ============================================================

class TestSafeNetworkBackend:
    """SafeNetworkBackend 测试。"""

    def test_refuses_private_ip_at_connection_time(self, monkeypatch):
        from extractors.http_downloader import SafeNetworkBackend

        def mock_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", port or 443)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

        backend = SafeNetworkBackend()
        with pytest.raises(OSError):
            backend.connect_tcp("evil.local", 443)


class TestSafeTransport:
    """SafeTransport 测试。"""

    def test_creates_httpx_client(self):
        from extractors.http_downloader import SafeTransport
        transport = SafeTransport()
        client = httpx.Client(transport=transport)
        assert client is not None
        client.close()


# ============================================================
# 重定向处理测试
# ============================================================

class TestRedirectHandling:
    """重定向处理测试。"""

    def test_follows_allowed_redirect(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "final" in url:
                return httpx.Response(
                    200, content=b"video data",
                    headers={"Content-Type": "video/mp4", "Content-Length": "10"},
                )
            return httpx.Response(
                302, headers={"Location": "https://cdn.example.com/final.mp4"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/start",
                output_dir=Path(tmpdir), filename="video.mp4",
                allowed_domains=["cdn.example.com"],
                config=config, _transport=transport,
            )
            assert result.success is True

    def test_rejects_redirect_to_other_domain(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "https://evil.com/video.mp4"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/start",
                output_dir=Path(tmpdir), filename="video.mp4",
                allowed_domains=["cdn.example.com"],
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "域名" in result.error or "白名单" in result.error

    def test_handles_relative_redirect(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "final" in url:
                return httpx.Response(
                    200, content=b"video data",
                    headers={"Content-Type": "video/mp4", "Content-Length": "10"},
                )
            return httpx.Response(302, headers={"Location": "/final.mp4"})

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/start",
                output_dir=Path(tmpdir), filename="video.mp4",
                allowed_domains=["cdn.example.com"],
                config=config, _transport=transport,
            )
            assert result.success is True

    def test_rejects_redirect_loop(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "https://cdn.example.com/start"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(
            connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0, max_redirects=3,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/start",
                output_dir=Path(tmpdir), filename="video.mp4",
                allowed_domains=["cdn.example.com"],
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "循环" in result.error or "重定向" in result.error

    def test_rejects_too_many_redirects(self):
        from extractors.http_downloader import download, DownloadConfig

        locations = [
            "https://cdn.example.com/step1",
            "https://cdn.example.com/step2",
            "https://cdn.example.com/step3",
            "https://cdn.example.com/step4",
        ]
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            i = call_count["n"]
            call_count["n"] += 1
            if i >= len(locations):
                return httpx.Response(
                    200, content=b"ok",
                    headers={"Content-Type": "video/mp4", "Content-Length": "2"},
                )
            return httpx.Response(302, headers={"Location": locations[i]})

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(
            connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0, max_redirects=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/start",
                output_dir=Path(tmpdir), filename="video.mp4",
                allowed_domains=["cdn.example.com"],
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "重定向" in result.error

    def test_cross_origin_strips_auth_headers(self):
        """无域名白名单时跨域重定向剥离敏感头。"""
        from extractors.http_downloader import download, DownloadConfig

        second_req_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "other-cdn.com" in url:
                second_req_headers.update(dict(request.headers))
                return httpx.Response(
                    200, content=b"data",
                    headers={"Content-Type": "video/mp4", "Content-Length": "4"},
                )
            return httpx.Response(
                302, headers={"Location": "https://other-cdn.com/video.mp4"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/start",
                output_dir=Path(tmpdir), filename="video.mp4",
                headers={"Authorization": "Bearer secret", "Cookie": "s=abc"},
                config=config, _transport=transport,
            )
            assert result.success is True
            assert "authorization" not in {k.lower() for k in second_req_headers}
            assert "cookie" not in {k.lower() for k in second_req_headers}


# ============================================================
# 文件大小 & Content-Type 拒绝测试
# ============================================================

class TestSizeAndContentTypeRejection:
    """在 download() 中拒绝超限文件和非法 Content-Type。"""

    def test_rejects_content_length_exceeds_max(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": "video/mp4", "Content-Length": str(3 * 1024 * 1024 * 1024)},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/huge.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "大小" in result.error or "超过" in result.error or "size" in result.error.lower()

    def test_rejects_html_content_type(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"<html>not a video</html>",
                headers={"Content-Type": "text/html", "Content-Length": "20"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/fake.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "Content-Type" in result.error or "内容类型" in result.error

    def test_rejects_json_content_type(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b'{"error": "not found"}',
                headers={"Content-Type": "application/json", "Content-Length": "22"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/json.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False

    def test_accepts_octet_stream_type(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"\x00\x00\x00\x18ftyp",
                headers={"Content-Type": "application/octet-stream", "Content-Length": "8"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/binary.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            assert result.bytes_downloaded == 8

    def test_rejects_missing_content_type(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"some data", headers={"Content-Length": "9"})

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/no-type",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False


# ============================================================
# 超时 & 低速检测测试
# ============================================================

class TestTimeoutAndSpeed:
    """超时和低速检测测试。"""

    def test_total_timeout(self, monkeypatch):
        from extractors.http_downloader import download, DownloadConfig
        import extractors.http_downloader as mod

        # 模拟时间流逝: 每次调用 monotonic() 前进 0.1s, 确保 total_timeout 触发
        fake_time = [0.0]
        def mock_monotonic():
            t = fake_time[0]
            fake_time[0] += 0.1
            return t

        monkeypatch.setattr(mod.time_module, "monotonic", mock_monotonic)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"x" * 50000,
                headers={"Content-Type": "video/mp4", "Content-Length": "50000"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(
            connect_timeout=5.0, read_timeout=5.0, total_timeout=0.001,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/slow.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "超时" in result.error or "timeout" in result.error.lower()


# ============================================================
# 磁盘检查测试
# ============================================================

class TestDiskSpace:
    """磁盘空间检查测试。"""

    def test_rejects_insufficient_disk_before_download(self, monkeypatch):
        from extractors.http_downloader import download, DownloadConfig

        def mock_disk_usage(path):
            return shutil._ntuple_diskusage(100, 1000, 100)

        monkeypatch.setattr(shutil, "disk_usage", mock_disk_usage)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": "video/mp4", "Content-Length": "1000"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "磁盘" in result.error or "空间" in result.error or "disk" in result.error.lower()


# ============================================================
# 原子写入 & 不覆盖测试
# ============================================================

class TestAtomicWriteAndNoOverwrite:
    """原子写入和不覆盖已有文件测试。"""

    def test_download_creates_output_file(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"video content here",
                headers={"Content-Type": "video/mp4", "Content-Length": "18"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            assert os.path.exists(result.output_path)
            with open(result.output_path, "rb") as f:
                assert f.read() == b"video content here"

    def test_no_part_file_left_after_success(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"data",
                headers={"Content-Type": "video/mp4", "Content-Length": "4"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            part_files = list(Path(tmpdir).glob("*.part"))
            assert len(part_files) == 0

    def test_part_file_cleaned_on_failure(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html", "Content-Length": "100"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            part_files = list(Path(tmpdir).glob("*.part"))
            assert len(part_files) == 0

    def test_does_not_overwrite_existing_file(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"new data",
                headers={"Content-Type": "video/mp4", "Content-Length": "8"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(
            connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0, overwrite=False,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "video.mp4"
            existing.write_text("existing content")

            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            assert existing.read_text() == "existing content"
            assert result.output_path != str(existing)
            assert os.path.exists(result.output_path)

    def test_overwrite_flag_allows_replacement(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"new data",
                headers={"Content-Type": "video/mp4", "Content-Length": "8"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(
            connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0, overwrite=True,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "video.mp4"
            existing.write_text("existing content")

            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            with open(existing, "rb") as f:
                assert f.read() == b"new data"

    def test_auto_generates_sequential_filename(self):
        from extractors.http_downloader import _unique_path

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "video.mp4"
            base.write_text("original")

            path1 = _unique_path(base, overwrite=False)
            assert path1 != base
            assert "video" in path1.name and path1.name.endswith(".mp4")

            path1.write_text("copy1")
            path2 = _unique_path(base, overwrite=False)
            assert path2 != base
            assert path2 != path1


# ============================================================
# 输出隐私测试
# ============================================================

class TestOutputPrivacy:
    """控制台不泄露敏感信息测试。"""

    def test_error_message_does_not_contain_url(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"Content-Type": "text/html", "Content-Length": "100"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            url = "https://cdn.example.com/video.mp4?sign=secret123&token=abc"
            result = download(
                url=url, output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "secret123" not in result.error
            assert "token=abc" not in result.error

    def test_does_not_print_url_during_download(self, capsys):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"video data here!",
                headers={"Content-Type": "video/mp4", "Content-Length": "15"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            url = "https://cdn.example.com/video.mp4?token=super-secret"
            result = download(
                url=url, output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            captured = capsys.readouterr()
            assert "token=super-secret" not in captured.out


# ============================================================
# 资源关闭测试
# ============================================================

class TestResourceCleanup:
    """Client 正确关闭测试。"""

    def test_successful_download_returns_result(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"data",
                headers={"Content-Type": "video/mp4", "Content-Length": "4"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True

    def test_failed_download_returns_error(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, headers={"Content-Type": "text/html", "Content-Length": "100"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
