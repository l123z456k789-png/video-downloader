"""日志模块。

同时输出到控制台和文件。
文件按日期轮转，保留最近 30 天。
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


# ---- 敏感信息脱敏 ----
_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    # Cookie 值
    (r"(SAPISID|HSID|SID|SSID|APISID|__Secure-\w+PSID\w*)=[^;&\s]+",
     r"\1=***"),
    # Authorization / Bearer token
    (r"(Authorization|authorization):\s*Bearer\s+\S+", r"\1: Bearer ***"),
    (r"(token|Token|access_token)=[^;&\s]+", r"\1=***"),
    # 签名 URL 中的 signature 参数
    (r"(sign|signature|sig|auth_key|expires)=[^;&\s]+", r"\1=***"),
    # Cookie 文件内容（不以行首 # 开头的内容）
    # 不处理 — 日志中不应出现 Cookie 文件内容
]


def _sanitize(message: str) -> str:
    """脱敏处理。"""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
    return message


class SanitizingFormatter(logging.Formatter):
    """带脱敏功能的日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return _sanitize(msg)


# ---- 全局 logger ----
_logger: logging.Logger | None = None
_log_dir: Path | None = None


def _cleanup_old_logs(log_dir: Path, keep_days: int = 30) -> None:
    """删除超过 keep_days 天的旧日志文件。"""
    cutoff = datetime.now().timestamp() - keep_days * 86400
    try:
        for f in log_dir.glob("*.log"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass  # 清理失败不影响主流程


def setup_logging(
    level: str = "INFO",
    log_directory: str = "logs",
    keep_days: int = 30,
) -> logging.Logger:
    """初始化日志系统。同时输出到控制台和每日文件。"""
    global _logger, _log_dir

    root = Path(__file__).resolve().parent
    log_dir = root / log_directory
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_dir = log_dir

    _cleanup_old_logs(log_dir, keep_days)

    _logger = logging.getLogger("video_downloader")
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    _logger.handlers.clear()

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    console_fmt = SanitizingFormatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    _logger.addHandler(console_handler)

    # 文件 handler（按日期）
    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = logging.FileHandler(
        log_dir / f"{today}.log", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = SanitizingFormatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    _logger.addHandler(file_handler)

    return _logger


def get_logger() -> logging.Logger:
    """获取已初始化的 logger。未初始化则使用默认配置。"""
    global _logger
    if _logger is None:
        return setup_logging()
    return _logger


def new_task_id() -> str:
    """生成简短的任务 ID。"""
    return uuid.uuid4().hex[:12]


def log_event(
    task_id: str,
    event: str,
    extra: dict[str, Any] | None = None,
    *,
    level: str = "INFO",
) -> None:
    """记录一次结构化事件。

    Args:
        task_id: 任务 ID
        event: 事件名，如 download_start, download_complete
        extra: 附加字段
        level: 日志等级
    """
    logger = get_logger()
    parts = [f"task={task_id}", f"event={event}"]
    if extra:
        # 对 URL 做简单脱敏：去掉 query string 中的敏感部分
        for key, value in extra.items():
            if isinstance(value, str) and len(value) > 200:
                value = value[:200] + "..."
            parts.append(f"{key}={value}")

    msg = " ".join(parts)
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(msg)


def get_log_dir() -> Path | None:
    """返回当前日志目录路径。"""
    return _log_dir
