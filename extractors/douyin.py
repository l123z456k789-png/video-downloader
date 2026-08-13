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
from urllib.parse import urlparse

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
    """从抖音 API 响应 JSON 中提取视频地址。

    优先选择:
        1. download_addr — 无水印，最高画质
        2. play_addr — 有水印，画质稍低
    只返回 1 个最佳视频，不要一股脑把所有 URL 都列出来。
    """
    # 找到 aweme_detail（视频主体数据）
    aweme = data.get("aweme_detail") or data
    if isinstance(aweme, list):
        aweme = aweme[0] if aweme else {}

    video = aweme.get("video", {}) if isinstance(aweme, dict) else {}

    title = str(
        aweme.get("desc", "")
        or aweme.get("share_info", {}).get("share_title", "")
        or data.get("desc", "")
    ) if isinstance(aweme, dict) else ""

    def _best_url(addr_dict: dict) -> str:
        """从 addr 字典中选最高画质的 URL。"""
        url_list = addr_dict.get("url_list") or addr_dict.get("urlList") or []
        # url_list 通常是 [低画质, ..., 最高画质]，取最后一个
        if url_list:
            return str(url_list[-1])
        return ""

    # 优先 download_addr（无水印）
    download = video.get("download_addr") or video.get("download_addr_h264") or {}
    best_url = _best_url(download) if isinstance(download, dict) else ""

    # 回退 play_addr（有水印）
    if not best_url:
        play = video.get("play_addr") or video.get("play_addr_h264") or {}
        best_url = _best_url(play) if isinstance(play, dict) else ""

    if not best_url:
        # 最坏情况：递归搜索（兜底）
        found_urls: list[str] = []

        def _search(obj: Any, depth: int = 0) -> None:
            if depth > 15 or len(found_urls) >= 1:
                return
            if isinstance(obj, dict):
                for key in ("download_addr", "download_addr_h264", "play_addr", "play_addr_h264"):
                    addr = obj.get(key)
                    if isinstance(addr, dict):
                        u = _best_url(addr)
                        if u:
                            found_urls.append(u)
                            return
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        _search(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj[:3]:
                    _search(item, depth + 1)

        if isinstance(aweme, dict):
            _search(aweme)
        if not found_urls:
            _search(data)
        best_url = found_urls[0] if found_urls else ""

    if not best_url:
        return []

    return [
        VideoInfo(
            url=best_url,
            title=title,
            platform="douyin",
            ext="mp4",
            headers={
                "User-Agent": _HEADERS["User-Agent"],
                "Referer": "https://www.douyin.com/",
            },
            is_watermarked=("download" not in best_url.lower()),
        )
    ]


@register
class DouyinExtractor(BaseExtractor):
    """抖音视频提取器 — Playwright 浏览器渲染。"""

    platform = "douyin"

    def __init__(self) -> None:
        # 持久化浏览器 profile，避免每次运行都创建新的临时 profile
        root = Path(__file__).resolve().parent.parent
        self._profile_dir = str(root / "douyin_profile")

    def supports(self, url: str) -> bool:
        try:
            hostname = (urlparse(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        return any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in DOUYIN_DOMAINS
        )

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
            if "aweme/detail" in response.url:
                try:
                    body = response.json()
                    if body:
                        captured_responses.append(body)
                except Exception:
                    pass

        context = None
        try:
            pw = sync_playwright().start()

            context = pw.chromium.launch_persistent_context(
                user_data_dir=self._profile_dir,
                channel="chrome",
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                user_agent=_HEADERS["User-Agent"],
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", _on_response)

            print("  [浏览器] 正在渲染页面...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待 API 响应（视频数据）
            page.wait_for_timeout(8000)

            # 尝试从 DOM 提取 video src 作为备用
            try:
                video_src = page.evaluate(
                    """() => {
                        const v = document.querySelector('video');
                        if (v) return v.currentSrc || v.src || '';
                        return '';
                    }"""
                ).strip()
                if video_src and video_src.startswith("http"):
                    captured_responses.append(
                        {"_video_src": video_src, "desc": page.title()}
                    )
            except Exception:
                pass

        except Exception as e:
            return ExtractResult(
                success=False,
                error=f"浏览器渲染失败: {e}",
                fallback_url=url,
            )
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if 'pw' in dir():
                try:
                    pw.stop()
                except Exception:
                    pass

        # 分析捕获的响应
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

        all_videos: list[VideoInfo] = []
        seen_urls: set[str] = set()
        for data in captured_responses:
            if "_video_src" in data:
                url = data["_video_src"]
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_videos.append(
                        VideoInfo(
                            url=url,
                            title=data.get("desc", ""),
                            platform="douyin",
                            ext="mp4",
                            headers={
                                "User-Agent": _HEADERS["User-Agent"],
                                "Referer": "https://www.douyin.com/",
                            },
                        )
                    )
            else:
                for v in _extract_from_api_json(data):
                    if v.url not in seen_urls:
                        seen_urls.add(v.url)
                        all_videos.append(v)

        if not all_videos:
            return ExtractResult(
                success=False,
                error="未找到可下载的视频地址",
                fallback_url=url,
            )

        return ExtractResult(success=True, videos=all_videos)

    def close(self) -> None:
        """清理资源（持久化 profile 保留以便下次复用）。"""
        pass
