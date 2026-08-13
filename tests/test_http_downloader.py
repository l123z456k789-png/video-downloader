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

    def test_rejects_404_octet_stream_without_creating_output(self):
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404, content=b"not-a-video",
                headers={"Content-Type": "application/octet-stream", "Content-Length": "11"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/missing.mp4",
                output_dir=Path(tmpdir), filename="missing.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "404" in result.error
            assert list(Path(tmpdir).iterdir()) == []

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

    def test_total_timeout_is_not_retried(self):
        from extractors.http_downloader import download, DownloadConfig

        attempts = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            attempts[0] += 1
            return httpx.Response(
                200, content=b"x",
                headers={"Content-Type": "video/mp4", "Content-Length": "1"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(total_timeout=-1.0, max_retries=3)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/slow.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )

        assert result.success is False
        assert attempts[0] == 1


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

# ============================================================
# SafeTransport handle_request 契约测试
# ============================================================

class TestSafeTransportHandleRequest:
    """验证 SafeTransport.handle_request 正确适配 httpcore → httpx。"""

    def test_streaming_body_readable(self):
        """流式响应 body 必须可读取，不会触发 RuntimeError 或 StreamClosed。"""
        import httpcore
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        # 用 mock 替换内部 pool，返回流式 httpcore.Response
        fake_stream = iter([b"chunk1", b"chunk2"])
        fake_core = httpcore.Response(
            200,
            headers=[(b"content-type", b"video/mp4")],
            content=fake_stream,
        )

        def fake_handle(core_req):
            return fake_core

        transport._pool.handle_request = fake_handle  # type: ignore[assignment]

        httpx_req = httpx.Request("GET", "https://cdn.example.com/video.mp4")
        httpx_resp = transport.handle_request(httpx_req)

        assert httpx_resp.status_code == 200
        assert httpx_resp.headers["content-type"] == "video/mp4"
        # 必须能正常读取 body
        body = httpx_resp.read()
        assert body == b"chunk1chunk2"

    def test_status_and_headers_converted(self):
        """status code 和所有 headers 正确传递。"""
        import httpcore
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        fake_core = httpcore.Response(
            404,
            headers=[
                (b"content-type", b"text/plain"),
                (b"x-custom", b"value1"),
            ],
            content=b"not found",
        )

        def fake_handle(core_req):
            return fake_core

        transport._pool.handle_request = fake_handle  # type: ignore[assignment]

        httpx_req = httpx.Request("GET", "https://cdn.example.com/missing")
        httpx_resp = transport.handle_request(httpx_req)

        assert httpx_resp.status_code == 404
        assert httpx_resp.headers["content-type"] == "text/plain"
        assert httpx_resp.headers["x-custom"] == "value1"

    def test_close_propagates_to_pool(self):
        """transport.close() 必须关闭底层连接池。"""
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        close_called = []

        def fake_close():
            close_called.append(True)

        transport._pool.close = fake_close  # type: ignore[assignment]
        transport.close()
        assert len(close_called) == 1

    def test_extensions_preserved_from_httpcore(self):
        """httpcore 响应的 extensions 字典必须传递到 httpx.Response。"""
        import httpcore
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        fake_core = httpcore.Response(
            200,
            headers=[(b"content-type", b"video/mp4")],
            content=b"ok",
            extensions={"http_version": b"HTTP/1.1", "reason_phrase": b"OK"},
        )

        def fake_handle(core_req):
            return fake_core

        transport._pool.handle_request = fake_handle  # type: ignore[assignment]

        httpx_req = httpx.Request("GET", "https://cdn.example.com/video.mp4")
        httpx_resp = transport.handle_request(httpx_req)

        assert httpx_resp.extensions["http_version"] == b"HTTP/1.1"
        assert httpx_resp.extensions["reason_phrase"] == b"OK"


# ============================================================
# 流式下载生命周期测试
# ============================================================

class TestStreamingLifecycle:
    """验证 download() 正确处理流式响应 — 数据在 with 块内读取。"""

    def test_download_completes_with_streaming_response(self):
        """使用真正的流式 transport 下载必须成功，不能抛出 StreamClosed。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig
        from extractors.http_downloader import _StreamWrapper

        class StreamingTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                core_req = httpcore.Request(
                    method=request.method,
                    url=str(request.url),
                    headers=list(request.headers.items()),
                    content=request.stream,
                    extensions=request.extensions,
                )
                core_resp = httpcore.Response(
                    200,
                    headers=[
                        (b"content-type", b"video/mp4"),
                        (b"content-length", b"18"),
                    ],
                    content=iter([b"chunk-a-", b"chunk-b-", b"chunk-c"]),
                )
                return httpx.Response(
                    status_code=core_resp.status,
                    headers=list(core_resp.headers),
                    stream=_StreamWrapper(core_resp.stream),
                    extensions=core_resp.extensions,
                    request=request,
                )

        transport = StreamingTransport()
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True, f"download failed: {result.error}"
            expected_body = b"chunk-a-chunk-b-chunk-c"
            assert result.bytes_downloaded == len(expected_body)
            assert os.path.exists(result.output_path)
            with open(result.output_path, "rb") as f:
                assert f.read() == expected_body

    def test_streaming_body_correctly_written(self):
        """流式数据完整写入文件，无截断。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig
        from extractors.http_downloader import _StreamWrapper

        chunks = [b"AAAA", b"BBBB", b"CCCC", b"DDDD"]

        class StreamingTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                core_req = httpcore.Request(
                    method=request.method,
                    url=str(request.url),
                    headers=list(request.headers.items()),
                    content=request.stream,
                    extensions=request.extensions,
                )
                core_resp = httpcore.Response(
                    200,
                    headers=[
                        (b"content-type", b"video/mp4"),
                        (b"content-length", b"16"),
                    ],
                    content=iter(chunks),
                )
                return httpx.Response(
                    status_code=core_resp.status,
                    headers=list(core_resp.headers),
                    stream=_StreamWrapper(core_resp.stream),
                    extensions=core_resp.extensions,
                    request=request,
                )

        transport = StreamingTransport()
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            with open(result.output_path, "rb") as f:
                assert f.read() == b"AAAABBBBCCCCDDDD"


class TestStreamReadMidFailure:
    """流读取中途失败的清理行为。"""

    def test_part_file_cleaned_on_stream_read_failure(self):
        """流中途失败必须清理 .part，不留下损坏的最终文件。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig
        from extractors.http_downloader import _StreamWrapper

        class FaultyTransport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                def faulty_stream():
                    yield b"good"
                    yield b"data"
                    raise ConnectionError("模拟连接中断")

                core_req = httpcore.Request(
                    method=request.method,
                    url=str(request.url),
                    headers=list(request.headers.items()),
                    content=request.stream,
                    extensions=request.extensions,
                )
                core_resp = httpcore.Response(
                    200,
                    headers=[
                        (b"content-type", b"video/mp4"),
                        (b"content-length", b"999"),
                    ],
                    content=faulty_stream(),
                )
                return httpx.Response(
                    status_code=core_resp.status,
                    headers=list(core_resp.headers),
                    stream=_StreamWrapper(core_resp.stream),
                    extensions=core_resp.extensions,
                    request=request,
                )

        transport = FaultyTransport()
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            # .part 必须被清理
            part_files = list(Path(tmpdir).glob("*.part"))
            assert len(part_files) == 0
            # 最终文件不能存在（原子写入没执行）
            final = Path(tmpdir) / "video.mp4"
            assert not final.exists()


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


# ============================================================
# 重试逻辑测试
# ============================================================

class TestRetryLogic:
    """max_retries 正确执行：网络瞬时异常重试，确定性错误不重试。"""

    def test_retries_on_connect_error(self):
        """max_retries=3 → ConnectError 应尝试 4 次（首次 + 3 次重试）。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig
        from extractors.http_downloader import _StreamWrapper

        attempts = [0]

        class RetryTransport(httpx.BaseTransport):
            def handle_request(self, request):
                attempts[0] += 1
                raise httpx.ConnectError("connection refused")

        transport = RetryTransport()
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=30.0,
            max_retries=3,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert attempts[0] == 4, f"expected 4 attempts (1 initial + 3 retries), got {attempts[0]}"

    def test_succeeds_on_second_attempt(self):
        """第一次 ConnectError，第二次成功。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig
        from extractors.http_downloader import _StreamWrapper

        attempts = [0]

        class RetryOnceTransport(httpx.BaseTransport):
            def handle_request(self, request):
                attempts[0] += 1
                if attempts[0] == 1:
                    raise httpx.ConnectError("connection refused")
                core_req = httpcore.Request(
                    method=request.method, url=str(request.url),
                    headers=list(request.headers.items()),
                    content=request.stream, extensions=request.extensions,
                )
                core_resp = httpcore.Response(
                    200,
                    headers=[(b"content-type", b"video/mp4"), (b"content-length", b"4")],
                    content=iter([b"data"]),
                )
                return httpx.Response(
                    status_code=core_resp.status,
                    headers=list(core_resp.headers),
                    stream=_StreamWrapper(core_resp.stream),
                    extensions=core_resp.extensions,
                    request=request,
                )

        transport = RetryOnceTransport()
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=30.0,
            max_retries=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is True
            assert attempts[0] == 2

    def test_exhausts_retries_then_fails(self):
        """耗尽所有重试后返回失败。"""
        from extractors.http_downloader import download, DownloadConfig

        attempts = [0]

        class AlwaysFailTransport(httpx.BaseTransport):
            def handle_request(self, request):
                attempts[0] += 1
                raise httpx.ReadError("read timeout")

        transport = AlwaysFailTransport()
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=1.0, total_timeout=30.0,
            max_retries=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert attempts[0] == 3  # 1 initial + 2 retries

    def test_does_not_retry_content_type_error(self):
        """Content-Type 错误不重试（确定性错误）。"""
        from extractors.http_downloader import download, DownloadConfig

        attempts = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            attempts[0] += 1
            return httpx.Response(
                200, content=b"<html>",
                headers={"Content-Type": "text/html", "Content-Length": "6"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(
            connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0,
            max_retries=3,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert attempts[0] == 1  # 不重试

    def test_does_not_retry_url_error(self):
        """URL 校验失败不重试（确定性错误）。"""
        from extractors.http_downloader import download, DownloadConfig

        config = DownloadConfig(max_retries=5)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="file:///etc/passwd",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config,
            )
            assert result.success is False
            assert "协议" in result.error


# ============================================================
# Stream close 传播测试
# ============================================================

class TestStreamClosePropagation:
    """_StreamWrapper.close() 必须传播到底层 httpcore stream。"""

    def test_close_propagates_to_underlying_stream(self):
        """response.close() 必须关闭底层 httpcore stream。"""
        import httpcore
        from extractors.http_downloader import _StreamWrapper

        close_calls = []

        class CloseTrackedStream:
            def __init__(self, data):
                self._data = iter(data)
            def __iter__(self):
                return self
            def __next__(self):
                return next(self._data)
            def close(self):
                close_calls.append(True)

        tracked = CloseTrackedStream([b"a", b"b"])
        wrapper = _StreamWrapper(tracked)
        wrapper.close()
        assert len(close_calls) == 1, f"close() not propagated, calls={len(close_calls)}"
        # 幂等
        wrapper.close()
        assert len(close_calls) == 1, "close() should be idempotent"

    def test_redirect_response_closes_underlying_stream(self):
        """重定向响应被丢弃时必须关闭底层流。"""
        import httpcore
        import httpx
        from extractors.http_downloader import _StreamWrapper

        close_calls = []

        class CloseTrackedIter:
            def __init__(self):
                self._chunks = iter([b"ignore"])
            def __iter__(self):
                return self
            def __next__(self):
                return next(self._chunks)
            def close(self):
                close_calls.append(True)

        stream = CloseTrackedIter()
        wrapper = _StreamWrapper(stream)
        resp = httpx.Response(
            status_code=302,
            headers={"Location": "https://other.example.com/v.mp4"},
            stream=wrapper,
        )
        # 模拟重定向处理：不读取 body 直接关闭
        resp.close()
        assert len(close_calls) == 1, f"redirect response did not close stream, calls={len(close_calls)}"


# ============================================================
# 异常处理测试
# ============================================================

class TestExceptionHandling:
    """预期网络异常→可控失败；程序缺陷→继续抛出。"""

    def test_connect_error_becomes_controlled_failure(self):
        """ConnectError 变成 DownloadResult(success=False)，不抛异常。"""
        from extractors.http_downloader import download, DownloadConfig

        class FailingTransport(httpx.BaseTransport):
            def handle_request(self, request):
                raise httpx.ConnectError("connection refused")

        transport = FailingTransport()
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=10.0,
            max_retries=0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "connection refused" in result.error.lower() or \
                   "connecterror" in result.error.lower()

    def test_attribute_error_not_swallowed(self, monkeypatch):
        """程序缺陷（AttributeError）不能被伪装成下载失败。"""
        from extractors.http_downloader import download, DownloadConfig

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"data",
                headers={"Content-Type": "video/mp4", "Content-Length": "4"},
            )

        transport = httpx.MockTransport(handler)
        config = DownloadConfig(connect_timeout=5.0, read_timeout=5.0, total_timeout=10.0)

        # 让 response.iter_bytes 抛 AttributeError
        import extractors.http_downloader as mod
        original = mod.DownloadResult
        called = []

        def fake_result(*args, **kwargs):
            called.append(1)
            if len(called) == 1:
                raise AttributeError("simulated bug: NoneType has no attribute 'xyz'")
            return original(*args, **kwargs)

        monkeypatch.setattr(mod, "DownloadResult", fake_result)

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(AttributeError, match="simulated bug"):
                download(
                    url="https://cdn.example.com/video.mp4",
                    output_dir=Path(tmpdir), filename="video.mp4",
                    config=config, _transport=transport,
                )


# ============================================================
# httpcore → httpx 异常映射测试
# ============================================================

class FakePool:
    """模拟 httpcore ConnectionPool，可控抛异常。"""
    def __init__(self, exc_to_raise):
        self._exc = exc_to_raise
        self.attempts = 0
    def handle_request(self, request):
        self.attempts += 1
        if isinstance(self._exc, type):
            raise self._exc("fake")
        raise self._exc
    def close(self):
        pass


class TestSafeTransportExceptionMapping:
    """SafeTransport.handle_request 必须将 httpcore 异常映射为 httpx 异常。"""

    def test_maps_httpcore_connect_error_to_httpx(self):
        """httpcore.ConnectError → httpx.ConnectError。"""
        import httpcore
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        transport._pool = FakePool(httpcore.ConnectError)
        httpx_req = httpx.Request("GET", "https://cdn.example.com/v.mp4")

        with pytest.raises(httpx.ConnectError, match="fake"):
            transport.handle_request(httpx_req)
        assert transport._pool.attempts == 1

    def test_maps_httpcore_remote_protocol_error_to_httpx(self):
        """httpcore.RemoteProtocolError → httpx.RemoteProtocolError。"""
        import httpcore
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        transport._pool = FakePool(httpcore.RemoteProtocolError)
        httpx_req = httpx.Request("GET", "https://cdn.example.com/v.mp4")

        with pytest.raises(httpx.RemoteProtocolError, match="fake"):
            transport.handle_request(httpx_req)
        assert transport._pool.attempts == 1

    def test_maps_httpcore_read_timeout_to_httpx(self):
        """httpcore.ReadTimeout → httpx.ReadTimeout。"""
        import httpcore
        from extractors.http_downloader import SafeTransport

        transport = SafeTransport()
        transport._pool = FakePool(httpcore.ReadTimeout)
        httpx_req = httpx.Request("GET", "https://cdn.example.com/v.mp4")

        with pytest.raises(httpx.ReadTimeout, match="fake"):
            transport.handle_request(httpx_req)


class TestHttpcoreRetry:
    """真实 SafeTransport 路径下 httpcore 异常触发正确重试次数。"""

    def test_httpcore_connect_error_retries_4_times(self):
        """max_retries=3 → httpcore.ConnectError 映射后重试 4 次。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig, SafeTransport

        transport = SafeTransport()
        transport._pool = FakePool(httpcore.ConnectError)
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=30.0,
            max_retries=3,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert "fake" in result.error.lower()
            assert transport._pool.attempts == 4, \
                f"expected 4 attempts, got {transport._pool.attempts}"

    def test_httpcore_remote_protocol_error_triggers_retry(self):
        """httpcore.RemoteProtocolError 映射后进入重试。"""
        import httpcore
        from extractors.http_downloader import download, DownloadConfig, SafeTransport

        transport = SafeTransport()
        transport._pool = FakePool(httpcore.RemoteProtocolError)
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=30.0,
            max_retries=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert transport._pool.attempts == 3  # 1 + 2 retries


class TestNonRetryableExceptions:
    """StreamClosed/StreamConsumed 等代码缺陷不重试，原样传播。"""

    def test_stream_closed_not_retried_and_propagates(self):
        """httpx.StreamClosed 不重试，attempts=1，原样向上传播。"""
        from extractors.http_downloader import download, DownloadConfig

        attempts = [0]

        class StreamClosedTransport(httpx.BaseTransport):
            def handle_request(self, request):
                attempts[0] += 1
                raise httpx.StreamClosed()

        transport = StreamClosedTransport()
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=10.0,
            max_retries=3,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(httpx.StreamClosed):
                download(
                    url="https://cdn.example.com/video.mp4",
                    output_dir=Path(tmpdir), filename="video.mp4",
                    config=config, _transport=transport,
                )
        assert attempts[0] == 1, f"StreamClosed should NOT be retried, got {attempts[0]} attempts"

    def test_remote_protocol_error_is_retried(self):
        """httpx.RemoteProtocolError 按配置进入重试。"""
        from extractors.http_downloader import download, DownloadConfig

        attempts = [0]

        class RPETransport(httpx.BaseTransport):
            def handle_request(self, request):
                attempts[0] += 1
                raise httpx.RemoteProtocolError("server sent invalid response")

        transport = RPETransport()
        config = DownloadConfig(
            connect_timeout=1.0, read_timeout=5.0, total_timeout=30.0,
            max_retries=2,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = download(
                url="https://cdn.example.com/video.mp4",
                output_dir=Path(tmpdir), filename="video.mp4",
                config=config, _transport=transport,
            )
            assert result.success is False
            assert attempts[0] == 3  # 1 initial + 2 retries
