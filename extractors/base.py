"""自定义提取器基类。

yt-dlp 在某些平台（抖音/TikTok）经常失效。
本模块提供独立于 yt-dlp 的直接提取器，作为后备方案。

每个提取器只做一件事：从 URL 拿到真实视频下载地址。
下载本身仍由 yt-dlp 或直接 HTTP 完成。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class VideoInfo:
    """提取到的视频信息。"""

    url: str
    """可直接下载的视频地址（CDN 直链）"""

    title: str = ""
    """视频标题"""

    platform: str = ""
    """平台名，如 douyin, tiktok"""

    ext: str = "mp4"
    """文件扩展名"""

    metadata: dict = field(default_factory=dict)
    """额外元数据（作者、分辨率等）"""

    is_watermarked: bool = True
    """是否带水印"""


@dataclass
class ExtractResult:
    """提取结果。"""

    success: bool
    """是否成功"""

    videos: list[VideoInfo] = field(default_factory=list)
    """提取到的视频列表（通常 1 个）"""

    error: str = ""
    """失败原因"""

    fallback_url: str = ""
    """如果提取失败，可以丢给 yt-dlp 重试的原始 URL"""


class BaseExtractor(ABC):
    """提取器基类。

    子类需要实现:
        extract(url: str) -> ExtractResult
        supports(url: str) -> bool
    """

    platform: str = "unknown"
    """平台标识"""

    @abstractmethod
    def extract(self, url: str, cookies: dict | None = None) -> ExtractResult:
        """从 URL 提取视频信息。

        Args:
            url: 视频页面 URL
            cookies: 可选的 cookie 字典

        Returns:
            ExtractResult
        """
        ...

    @abstractmethod
    def supports(self, url: str) -> bool:
        """判断是否支持该 URL。"""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} platform={self.platform}>"


# 全局提取器注册表
_registry: dict[str, type[BaseExtractor] | BaseExtractor] = {}
_instances: dict[str, BaseExtractor] = {}


def register(extractor_cls):
    """注册提取器类（用 @register 装饰器）。"""
    # 先实例化以获取 platform 属性
    instance = extractor_cls()
    _registry[instance.platform] = extractor_cls
    return extractor_cls


def _ensure_instance(key: str) -> BaseExtractor | None:
    """获取提取器实例（懒实例化）。"""
    entry = _registry.get(key)
    if entry is None:
        return None
    if key not in _instances:
        if isinstance(entry, type):
            _instances[key] = entry()
        else:
            _instances[key] = entry
    return _instances[key]


def get_extractor(platform: str) -> BaseExtractor | None:
    """按平台名获取提取器实例。"""
    return _ensure_instance(platform)


def list_platforms() -> list[str]:
    """列出所有已注册的平台。"""
    return list(_registry.keys())


def find_extractor(url: str) -> BaseExtractor | None:
    """遍历所有提取器，找到第一个支持该 URL 的。"""
    for key in _registry:
        ext = _ensure_instance(key)
        if ext and ext.supports(url):
            return ext
    return None
