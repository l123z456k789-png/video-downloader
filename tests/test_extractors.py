"""extractors/ 模块测试。"""

from __future__ import annotations


class TestDouyinApiJsonExtraction:
    """抖音 API JSON → VideoInfo 转换（不依赖 Playwright）。"""

    def test_extracted_video_includes_headers(self):
        """_extract_from_api_json 返回的 VideoInfo 应包含 User-Agent 和 Referer。"""
        from extractors.douyin import _extract_from_api_json

        data = {
            "aweme_detail": {
                "desc": "测试视频",
                "video": {
                    "download_addr": {
                        "url_list": [
                            "http://example.com/low.mp4",
                            "http://example.com/high.mp4",
                        ]
                    }
                },
            }
        }
        videos = _extract_from_api_json(data)
        assert len(videos) == 1
        v = videos[0]
        assert v.headers.get("User-Agent") is not None
        assert v.headers.get("Referer") is not None
        assert "douyin.com" in v.headers["Referer"]


class TestVideoInfo:
    """VideoInfo dataclass — 视频直链信息容器。"""

    def test_default_headers_is_empty_dict(self):
        from extractors.base import VideoInfo
        v = VideoInfo(url="https://example.com/v.mp4")
        assert v.headers == {}

    def test_headers_field_is_writable(self):
        from extractors.base import VideoInfo
        v = VideoInfo(
            url="https://example.com/v.mp4",
            headers={"User-Agent": "TestUA", "Referer": "https://test.com/"},
        )
        assert v.headers["User-Agent"] == "TestUA"
        assert v.headers["Referer"] == "https://test.com/"

    def test_backward_compatible_without_headers(self):
        """无 headers 参数时 VideoInfo 正常构造（向后兼容）。"""
        from extractors.base import VideoInfo
        v = VideoInfo(
            url="https://example.com/v.mp4",
            title="test",
            platform="douyin",
        )
        assert v.url == "https://example.com/v.mp4"
        assert v.title == "test"
        assert v.platform == "douyin"
        assert v.ext == "mp4"
        assert v.headers == {}
        assert v.is_watermarked is True
        assert v.metadata == {}
