"""安全 HTTP 直链下载器。"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class DownloadConfig:
    max_size_bytes: int = 2 * 1024 * 1024 * 1024
    connect_timeout: float = 30.0
    read_timeout: float = 300.0
    total_timeout: float = 600.0
    min_speed_bytes_per_sec: int = 1024
    min_speed_window_sec: float = 30.0
    allowed_content_types: tuple[str, ...] = (
        "video/",
        "application/octet-stream",
    )
    max_redirects: int = 3
    overwrite: bool = False
    disk_safety_ratio: float = 1.2
    disk_check_interval_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True)
class DownloadResult:
    success: bool
    output_path: str
    bytes_downloaded: int
    error: str = ""


def download(
    url: str,
    output_dir: Path,
    filename: str,
    allowed_domains: list[str] | None = None,
    headers: dict[str, str] | None = None,
    config: DownloadConfig | None = None,
) -> DownloadResult:
    raise NotImplementedError


# ---- URL 校验 ----

def _validate_url(
    url: str,
    allowed_domains: list[str] | None,
) -> tuple[bool, str]:
    """校验 URL 协议、userinfo 和域名白名单。

    Returns:
        (是否通过, 拒绝原因)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"不支持的协议: {parsed.scheme}，仅允许 http/https"

    if parsed.username is not None or parsed.password is not None:
        return False, "URL 中不允许携带用户名或密码"

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return False, "URL 缺少有效主机名"

    try:
        hostname = hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return False, "主机名编码异常"

    if allowed_domains is not None:
        allowed = [d.lower().rstrip(".") for d in allowed_domains]
        matched = any(
            hostname == d or hostname.endswith("." + d)
            for d in allowed
        )
        if not matched:
            return False, f"域名不在白名单中: {hostname}"

    return True, ""


# ---- IP 安全 ----

def _is_ip_public(ip_str: str) -> bool:
    """判断 IP 地址是否为公网可路由地址。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_multicast:
        return False
    if not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local:
        return False
    return True


def _resolve_public_ips(host: str) -> set[str]:
    """解析 hostname 的所有 A/AAAA 地址。

    要求全部地址均为公网地址。混合解析或全部私网均拒绝。

    Raises:
        OSError: DNS 解析失败、无公网地址、混合公私网地址
    """
    try:
        addrs = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise OSError(f"DNS 解析失败: {host}") from e

    if not addrs:
        raise OSError(f"DNS 解析无结果: {host}")

    ip_set: set[str] = set()
    private_ips: set[str] = set()

    for addr in addrs:
        ip_str = addr[4][0]
        if _is_ip_public(ip_str):
            ip_set.add(ip_str)
        else:
            private_ips.add(ip_str)

    if private_ips and ip_set:
        raise OSError(
            f"DNS 解析包含公网和私网地址，拒绝连接: host={host}"
        )
    if not ip_set:
        raise OSError(f"未找到公网地址: host={host}")

    return ip_set


# ---- 文件名安全 ----

_WINDOWS_RESERVED_NAMES: set[str] = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validate_filename(filename: str, output_dir: Path) -> Path:
    """校验并返回安全的目标文件路径。"""
    if not filename or not filename.strip():
        raise ValueError("文件名不能为空")

    for i, ch in enumerate(filename):
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValueError(f"文件名包含控制字符 (位置 {i}: U+{ord(ch):04X})")

    if "/" in filename or "\\" in filename:
        raise ValueError("文件名不允许包含路径分隔符")

    if os.path.isabs(filename) or filename.startswith(".."):
        raise ValueError("文件名不允许是绝对路径或上级引用")

    if filename.rstrip() != filename:
        raise ValueError("文件名末尾不允许有空格")
    if filename.rstrip(".") != filename:
        raise ValueError("文件名末尾不允许有点")

    name_part = filename.rsplit(".", 1)[0] if "." in filename else filename
    if name_part.upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"文件名 '{filename}' 是 Windows 保留名称")

    resolved_dir = output_dir.resolve()
    target = (resolved_dir / filename).resolve()
    try:
        target.relative_to(resolved_dir)
    except ValueError:
        raise ValueError(f"文件路径逃逸: {target} 不在 {resolved_dir} 内")

    return target


# ---- Content-Type 校验 ----

def _validate_content_type(
    content_type: str,
    config: DownloadConfig | None = None,
) -> bool:
    """校验响应 Content-Type 是否在允许列表中。"""
    if config is None:
        config = DownloadConfig()
    if not content_type:
        return False
    mime = content_type.lower().split(";")[0].strip()
    for allowed in config.allowed_content_types:
        if allowed.endswith("/"):
            # "video/" 匹配所有 video/*
            if mime.startswith(allowed):
                return True
        elif allowed.endswith("/*"):
            prefix = allowed[:-1]
            if mime.startswith(prefix):
                return True
        else:
            if mime == allowed:
                return True
    return False
