"""配置加载模块。

加载顺序: config.yaml → config.local.yaml（覆盖默认值）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml


# ---- 默认值 ----
DEFAULTS: dict[str, Any] = {
    "downloader": {
        "output_dir": "videos",
        "format": "bestvideo+bestaudio/best",
        "merge_format": "mp4",
        "playlist": False,
        "continue_download": True,
        "retries": 5,
        "socket_timeout": 30,
    },
    "tools": {
        "yt_dlp_path": "yt-dlp",
        "ffmpeg_path": "ffmpeg",
        "deno_path": "",
    },
    "browser": {
        "cookies_from_browser": "chrome",
    },
    "audio": {
        "codec": "aac",
        "bitrate": "192k",
    },
    "logging": {
        "level": "INFO",
        "directory": "logs",
    },
    "platforms": {},
}

_config_cache: dict[str, Any] | None = None


def _project_root() -> Path:
    """返回 main.py 所在目录。打包后也能正确定位。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个字典，override 的值覆盖 base。"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    """加载配置（带缓存）。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    root = _project_root()
    config = dict(DEFAULTS)

    # 1. 加载默认配置
    default_path = root / "config.yaml"
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            config = _merge_dicts(config, data)

    # 2. 加载本地覆盖
    local_path = root / "config.local.yaml"
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            config = _merge_dicts(config, data)

    # 3. 环境变量覆盖（最高优先级）
    env_map = {
        "VIDEO_DL_OUTPUT_DIR": ("downloader", "output_dir"),
        "VIDEO_DL_FORMAT": ("downloader", "format"),
        "VIDEO_DL_YT_DLP": ("tools", "yt_dlp_path"),
        "VIDEO_DL_FFMPEG": ("tools", "ffmpeg_path"),
        "VIDEO_DL_DENO": ("tools", "deno_path"),
        "VIDEO_DL_BROWSER": ("browser", "cookies_from_browser"),
        "VIDEO_DL_LOG_LEVEL": ("logging", "level"),
    }
    for env_var, (section, key) in env_map.items():
        value = os.environ.get(env_var)
        if value:
            config[section][key] = value

    _config_cache = config
    return config


def reload_config() -> dict[str, Any]:
    """强制重新加载配置（测试用）。"""
    global _config_cache
    _config_cache = None
    return load_config()


def validate_config(config: dict[str, Any]) -> list[str]:
    """校验配置合法性，返回问题列表。空列表 = 通过。"""
    errors: list[str] = []

    # tools 为可选（用户可能只传部分配置用于测试）
    tools = config.get("tools", {})
    if tools:
        yt_path = tools.get("yt_dlp_path", "")
        # 仅记录，不做强制校验

    output_dir = config["downloader"]["output_dir"]
    if not output_dir:
        errors.append("downloader.output_dir 不能为空")

    retries = config["downloader"]["retries"]
    if not isinstance(retries, int) or retries < 0 or retries > 20:
        errors.append(f"downloader.retries 应在 0-20 之间，当前值: {retries}")

    timeout = config["downloader"]["socket_timeout"]
    if not isinstance(timeout, int) or timeout < 5 or timeout > 300:
        errors.append(f"downloader.socket_timeout 应在 5-300 之间，当前值: {timeout}")

    log_level = config["logging"]["level"]
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        errors.append(f"logging.level 无效: {log_level}")

    return errors
