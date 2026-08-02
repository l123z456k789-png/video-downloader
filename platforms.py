"""简单平台识别模块。

根据 URL 域名匹配平台。不会请求网络。
仅供日志标记和未来按平台加载配置使用。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ---- 平台域名规则 ----
# key: 平台名, value: 域名正则列表
_PLATFORM_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "youtube",
        [
            r"(www\.)?youtube\.com$",
            r"youtu\.be$",
            r"(www\.)?youtube-nocookie\.com$",
            r"m\.youtube\.com$",
            r"music\.youtube\.com$",
        ],
    ),
    (
        "bilibili",
        [
            r"(www\.)?bilibili\.com$",
            r"b23\.tv$",
            r"bili2233\.cn$",
        ],
    ),
    (
        "tiktok",
        [
            r"(www\.)?tiktok\.com$",
            r"vm\.tiktok\.com$",
            r"m\.tiktok\.com$",
            r"vt\.tiktok\.com$",
        ],
    ),
    (
        "douyin",
        [
            r"(www\.)?douyin\.com$",
            r"v\.douyin\.com$",
            r"(www\.)?iesdouyin\.com$",
        ],
    ),
    (
        "twitter",
        [
            r"(www\.)?twitter\.com$",
            r"(www\.)?x\.com$",
            r"t\.co$",
        ],
    ),
    (
        "instagram",
        [
            r"(www\.)?instagram\.com$",
        ],
    ),
    (
        "reddit",
        [
            r"(www\.)?reddit\.com$",
            r"redd\.it$",
        ],
    ),
    (
        "twitch",
        [
            r"(www\.)?twitch\.tv$",
            r"clips\.twitch\.tv$",
        ],
    ),
]


def _normalize_hostname(hostname: str) -> str:
    """去前导点，转为小写。"""
    return hostname.lstrip(".").lower()


def detect_platform(url_text: str) -> str:
    """根据 URL 检测平台。

    Args:
        url_text: 用户输入的文本（可能包含多余空白）

    Returns:
        平台名，如 "youtube"、"bilibili"、"tiktok"、"douyin"
        无法识别返回 "unknown"
    """
    url_text = url_text.strip()

    # 尝试从混合文本中提取 URL
    extracted = _extract_url(url_text)
    if extracted:
        url_text = extracted

    try:
        parsed = urlparse(url_text)
    except (ValueError, AttributeError):
        return "unknown"

    hostname = _normalize_hostname(parsed.hostname or "")

    if not hostname:
        return "unknown"

    for platform, patterns in _PLATFORM_PATTERNS:
        for pattern in patterns:
            if re.fullmatch(pattern, hostname):
                return platform

    return "unknown"


def _extract_url(text: str) -> str | None:
    """尝试从混合文本中提取第一个 http(s) URL。"""
    match = re.search(r"https?://\S+", text)
    if match:
        # 去掉末尾可能的标点
        url = match.group(0)
        url = url.rstrip(".,;:!?）)】」")
        return url
    return None


def extract_url(text: str) -> str | None:
    """从用户输入中提取 URL。返回 None 表示未找到。"""
    return _extract_url(text)
