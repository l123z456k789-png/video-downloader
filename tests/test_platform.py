"""platform.py 模块测试。"""

from __future__ import annotations

import pytest

from platforms import detect_platform, extract_url


class TestDetectPlatform:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
            ("https://youtube.com/shorts/abc123", "youtube"),
            ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
            ("https://m.youtube.com/watch?v=abc", "youtube"),
            ("https://music.youtube.com/watch?v=abc", "youtube"),
            ("https://www.youtube-nocookie.com/embed/abc", "youtube"),
            ("https://www.bilibili.com/video/BV1GJ411x7h7", "bilibili"),
            ("https://b23.tv/xxxxx", "bilibili"),
            ("https://www.tiktok.com/@user/video/123456", "tiktok"),
            ("https://vm.tiktok.com/xxxxx/", "tiktok"),
            ("https://m.tiktok.com/v/123456", "tiktok"),
            ("https://www.douyin.com/video/123456", "douyin"),
            ("https://v.douyin.com/xxxxx/", "douyin"),
            ("https://www.iesdouyin.com/share/video/123/", "douyin"),
            ("https://twitter.com/user/status/123", "twitter"),
            ("https://x.com/user/status/123", "twitter"),
            ("https://www.instagram.com/p/abc123/", "instagram"),
            ("https://www.reddit.com/r/videos/comments/abc", "reddit"),
            ("https://www.twitch.tv/somechannel", "twitch"),
        ],
    )
    def test_known_platforms(self, url: str, expected: str):
        assert detect_platform(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.example.com/video/123",
            "https://some-random-site.org/watch?v=123",
        ],
    )
    def test_unknown_platform(self, url: str):
        assert detect_platform(url) == "unknown"

    def test_empty_string(self):
        assert detect_platform("") == "unknown"

    def test_non_url_text(self):
        assert detect_platform("hello world") == "unknown"

    def test_url_with_trailing_spaces(self):
        assert detect_platform("  https://www.youtube.com/watch?v=abc  ") == "youtube"

    def test_url_with_tracking_params(self):
        assert detect_platform(
            "https://www.youtube.com/watch?v=abc&utm_source=twitter&t=123"
        ) == "youtube"


class TestExtractUrl:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
            (
                "Check this out: https://youtu.be/abc123 cool video!",
                "https://youtu.be/abc123",
            ),
            (
                "link：https://www.bilibili.com/video/BVxxx 来看看",
                "https://www.bilibili.com/video/BVxxx",
            ),
        ],
    )
    def test_extract_url(self, text: str, expected: str):
        assert extract_url(text) == expected

    def test_no_url(self):
        assert extract_url("hello world 你好") is None

    def test_empty(self):
        assert extract_url("") is None
