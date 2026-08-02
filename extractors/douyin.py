"""抖音提取器。

通过解析抖音视频页面的服务端渲染数据来提取视频地址。
不需要 ABogus 签名，因为直接解析 HTML 中的 RENDER_DATA JSON。

参考: DouK-Downloader 的数据提取思路，videodl 的 VideoClient 模式
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from .base import BaseExtractor, ExtractResult, VideoInfo, register

# 抖音域名
DOUYIN_DOMAINS = [
    "douyin.com",
    "www.douyin.com",
    "v.douyin.com",
    "iesdouyin.com",
    "www.iesdouyin.com",
]

# 请求头：模拟真实 Chrome 浏览器
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.douyin.com/",
}


def _extract_video_id(url: str) -> str | None:
    """从抖音 URL 中提取视频 ID。

    支持:
        - https://www.douyin.com/video/7123456789012345678
        - https://v.douyin.com/AbCdEfG/
        - https://www.iesdouyin.com/share/video/7123456789012345678/
    """
    # 短链接: v.douyin.com/xxxx
    if "v.douyin.com" in url:
        return None  # 需要先解析短链接

    # /video/<id> 或 /share/video/<id>
    patterns = [
        r"/video/(\d+)",
        r"/note/(\d+)",
        r"/share/video/(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)

    # 直接从 URL 参数中提取
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "video_id" in qs:
        return qs["video_id"][0]

    return None


def _resolve_short_url(url: str, client: httpx.Client) -> str:
    """解析 v.douyin.com 短链接。"""
    try:
        resp = client.head(url, follow_redirects=False)
        location = resp.headers.get("location", "")
        if location:
            return location
        resp = client.get(url, follow_redirects=True)
        return str(resp.url)
    except Exception:
        return url


def _parse_render_data(html: str) -> dict[str, Any] | None:
    """从 HTML 中提取 RENDER_DATA JSON。

    抖音视频页面在服务端渲染时会把视频数据塞进:
        <script id="RENDER_DATA" type="application/json">...</script>
    """
    # 方式1: RENDER_DATA script 标签
    m = re.search(
        r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if m:
        raw = m.group(1)
        try:
            decoded = unescape(raw)
            return json.loads(decoded)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # 方式2: window._ROUTER_DATA
    m = re.search(
        r"window\._ROUTER_DATA\s*=\s*({.*?});?\s*</script>",
        html,
        re.DOTALL,
    )
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 方式3: __INITIAL_STATE__
    m = re.search(
        r"self\.__pace_f\.push\s*\(\s*\[1,\s*\"s:.*?\"\s*,\s*(.+?)\s*\]\)",
        html,
        re.DOTALL,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            return data
        except json.JSONDecodeError:
            pass

    return None


def _extract_video_from_json(data: dict[str, Any]) -> list[VideoInfo]:
    """从抖音 JSON 数据中提取视频信息。

    遍历 JSON 结构查找视频 URL。
    """
    videos: list[VideoInfo] = []
    data_str = json.dumps(data)

    # 查找无水印视频地址 (play_addr 或 bit_rate)
    # 抖音的 JSON 中，视频 URL 通常在 aweme.detail.video 路径下
    found_urls: set[str] = set()

    def _search(obj: Any, depth: int = 0) -> None:
        if depth > 15 or len(found_urls) >= 5:
            return
        if isinstance(obj, dict):
            # 找 video/play_addr/bit_rate 相关的 URL 列表
            for key in obj:
                if key in ("play_addr", "play_addr_h264", "download_addr", "download_addr_h264"):
                    addr = obj[key]
                    if isinstance(addr, dict):
                        url_list = addr.get("url_list") or addr.get("urlList") or []
                        for u in url_list:
                            if isinstance(u, str) and u not in found_urls:
                                # 替换域名以确保可访问（去掉可能的水印域名）
                                found_urls.add(u)
                if key in ("video", "aweme_detail", "aweme", "item_list"):
                    _search(obj[key], depth + 1)
                if isinstance(obj[key], (dict, list)):
                    _search(obj[key], depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _search(item, depth + 1)

    _search(data)

    # 按优先级: 下载地址 > 播放地址
    download_urls = [u for u in found_urls if "download" in u.lower()]
    play_urls = [u for u in found_urls if "play" in u.lower()]
    other_urls = [u for u in found_urls if u not in download_urls and u not in play_urls]

    all_urls = download_urls + play_urls + other_urls

    for i, url in enumerate(all_urls):
        videos.append(
            VideoInfo(
                url=url,
                title=data.get("desc", "") or data.get("share_info", {}).get("share_title", ""),
                platform="douyin",
                ext="mp4",
                is_watermarked=("watermark" in url.lower() or "play" in url.lower()),
            )
        )

    return videos


@register
class DouyinExtractor(BaseExtractor):
    """抖音视频提取器。

    策略:
        1. 解析短链接 → 获取完整 URL
        2. 请求视频页面 → 解析 HTML 中的 JSON 数据
        3. 从 JSON 中提取 CDN 视频直链
        4. 失败时返回 fallback_url，由上层转 yt-dlp 重试
    """

    platform = "douyin"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers=_HEADERS,
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    def supports(self, url: str) -> bool:
        return any(domain in url for domain in DOUYIN_DOMAINS)

    def extract(self, url: str, cookies: dict | None = None) -> ExtractResult:
        try:
            # 1. 解析短链接
            if "v.douyin.com" in url:
                resolved = _resolve_short_url(url, self.client)
                if resolved and resolved != url:
                    url = resolved
                else:
                    return ExtractResult(
                        success=False,
                        error="短链接解析失败，请使用完整链接（在浏览器中打开短链接后复制地址栏URL）",
                        fallback_url=url,
                    )

            # 2. 获取视频页面
            resp = self.client.get(url)
            if resp.status_code != 200:
                return ExtractResult(
                    success=False,
                    error=f"页面请求失败 (HTTP {resp.status_code})",
                    fallback_url=url,
                )

            html = resp.text

            # 3. 解析 JSON
            data = _parse_render_data(html)
            if data is None:
                return ExtractResult(
                    success=False,
                    error="页面解析失败：未找到视频数据，可能抖音页面结构已更新",
                    fallback_url=url,
                )

            # 4. 提取视频
            videos = _extract_video_from_json(data)
            if not videos:
                return ExtractResult(
                    success=False,
                    error="未找到可下载的视频地址",
                    fallback_url=url,
                )

            return ExtractResult(success=True, videos=videos)

        except httpx.TimeoutException:
            return ExtractResult(
                success=False,
                error="请求超时，请检查网络连接",
                fallback_url=url,
            )
        except Exception as e:
            return ExtractResult(
                success=False,
                error=f"提取失败: {e}",
                fallback_url=url,
            )
