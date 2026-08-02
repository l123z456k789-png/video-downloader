"""自定义视频提取器包。

对于 yt-dlp 经常失效的平台，这里提供独立于 yt-dlp 的直接提取器。

使用方式:
    from extractors import find_extractor, get_extractor

    ext = find_extractor(url)
    if ext:
        result = ext.extract(url)
        if result.success:
            for v in result.videos:
                print(f"Download: {v.url}")

添加新平台:
    1. 创建 extractors/xxx.py
    2. 继承 BaseExtractor，实现 extract() 和 supports()
    3. 用 @register 装饰器注册
    4. 在本文件 import 即可
"""

from __future__ import annotations

from .base import (
    BaseExtractor,
    ExtractResult,
    VideoInfo,
    find_extractor,
    get_extractor,
    list_platforms,
    register,
)

# 注册所有提取器（import 即注册）
from . import douyin  # noqa: F401

__all__ = [
    "BaseExtractor",
    "ExtractResult",
    "VideoInfo",
    "find_extractor",
    "get_extractor",
    "list_platforms",
    "register",
]
