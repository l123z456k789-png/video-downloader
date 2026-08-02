"""抖音提取器 — Playwright 浏览器渲染版。

抖音视频页面 100% JS 渲染，HTTPX 拿到的只是一个 JS 验证壳。
必须用真实浏览器执行 JS 后才能获取视频数据。

策略:
    1. 用系统 Chrome 打开视频页面（headless）
    2. 拦截页面发出的 API 请求 (aweme/detail)
    3. 从 API 响应 JSON 中提取视频直链
    4. 直链下载（HTTPX）
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .base import BaseExtractor, ExtractResult, VideoInfo, register

DOUYIN_DOMAINS = [
    "douyin.com",
    "www.douyin.com",
    "v.douyin.com",
    "iesdouyin.com",
    "www.iesdouyin.com",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _extract_video_id(url: str) -> str | None:
    """从抖音 URL 提取视频 ID。"""
    patterns = [
        r"/video/(\d+)",
        r"/note/(\d+)",
        r"/share/video/(\d+)",
        r"video_id=(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _extract_from_api_json(data: dict) -> list[VideoInfo]:
    """从抖音 API 响应 JSON 中提取视频地址。"""
    videos: list[VideoInfo] = []
    found_urls: set[str] = set()

    def _search(obj: Any, depth: int = 0) -> None:
        if depth > 20 or len(found_urls) >= 10:
            return
        if isinstance(obj, dict):
            for key in obj:
                if key in (
                    "play_addr", "play_addr_h264",
                    "download_addr", "download_addr_h264",
                    "playApi", "downloadApi",
                ):
                    addr = obj[key]
                    if isinstance(addr, dict):
                        url_list = (
                            addr.get("url_list")
                            or addr.get("urlList")
                            or addr.get("UrlList")
                            or []
                        )
                        for u in url_list:
                            if isinstance(u, str) and u not in found_urls:
                                found_urls.add(u)
                if isinstance(obj.get(key), (dict, list)):
                    _search(obj[key], depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _search(item, depth + 1)

    _search(data)

    download_urls = [u for u in found_urls if "download" in u.lower()]
    play_urls = [u for u in found_urls if "play" in u.lower()]
    other_urls = [u for u in found_urls if u not in download_urls and u not in play_urls]

    for url in download_urls + play_urls + other_urls:
        videos.append(
            VideoInfo(
                url=url,
                title=str(data.get("desc", "") or data.get("share_info", {}).get("share_title", "")),
                platform="douyin",
                ext="mp4",
                is_watermarked=("play" in url.lower() and "download" not in url.lower()),
            )
        )

    return videos


@register
class DouyinExtractor(BaseExtractor):
    """抖音视频提取器 — Playwright 浏览器渲染。"""

    platform = "douyin"

    def supports(self, url: str) -> bool:
        return any(domain in url for domain in DOUYIN_DOMAINS)

    def extract(self, url: str, cookies: dict | None = None) -> ExtractResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return ExtractResult(
                success=False,
                error="缺少 playwright 依赖: pip install playwright",
                fallback_url=url,
            )

        captured_responses: list[dict] = []

        def _on_response(response) -> None:
            """拦截 API 响应，捕获视频数据。"""
            try:
                if "aweme/detail" in response.url or "web/aweme" in response.url:
                    body = response.json()
                    if body:
                        captured_responses.append(body)
            except Exception:
                pass

        pw = None
        browser = None
        try:
            pw = sync_playwright().start()

            # 使用系统 Chrome（不需要额外下载 Chromium）
            browser = pw.chromium.launch(
                channel="chrome",
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )

            page = context.new_page()
            page.on("response", _on_response)

            print("  [浏览器] 正在渲染页面...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待视频数据加载
            try:
                page.wait_for_function(
                    """
                    () => {
                        return document.querySelector('video') ||
                               document.querySelector('[data-e2e="feed-active-video"]') ||
                               window._ROUTER_DATA;
                    }
                    """,
                    timeout=15000,
                )
            except Exception:
                pass

            # 额外等待网络请求完成
            page.wait_for_timeout(3000)

            # 尝试从 DOM 提取 video src
            video_src = page.evaluate(
                """
                () => {
                    const v = document.querySelector('video');
                    if (v) return v.currentSrc || v.src || '';
                    return '';
                }
                """
            ).strip()

            if video_src and video_src.startswith("http"):
                captured_responses.append(
                    {"_video_src": video_src, "desc": page.title()}
                )

        except Exception as e:
            return ExtractResult(
                success=False,
                error=f"浏览器渲染失败: {e}",
                fallback_url=url,
            )
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    pw.stop()
                except Exception:
                    pass

        # 分析捕获的数据
        if not captured_responses:
            return ExtractResult(
                success=False,
                error=(
                    "未捕获到视频数据。\n"
                    "可能原因: 1) 链接无效 2) 需要登录 3) 触发了验证码\n"
                    "建议: 在浏览器中打开视频确认可以播放后重试"
                ),
                fallback_url=url,
            )

        # 从捕获的响应中提取视频
        all_videos: list[VideoInfo] = []
        for data in captured_responses:
            if "_video_src" in data:
                all_videos.append(
                    VideoInfo(
                        url=data["_video_src"],
                        title=data.get("desc", ""),
                        platform="douyin",
                        ext="mp4",
                    )
                )
            else:
                all_videos.extend(_extract_from_api_json(data))

        if not all_videos:
            return ExtractResult(
                success=False,
                error="未找到可下载的视频地址",
                fallback_url=url,
            )

        return ExtractResult(success=True, videos=all_videos)

    def close(self) -> None:
        """清理资源。"""
        if self._client is not None:
            self._client.close()
            self._client = None
