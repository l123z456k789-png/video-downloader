"""安全 HTTP 直链下载器。"""
from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import time as time_module
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpcore
import httpx


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
    *,
    _transport: httpx.BaseTransport | None = None,
) -> DownloadResult:
    """安全下载一个 HTTP/HTTPS 视频文件。"""
    if config is None:
        config = DownloadConfig()

    # 1. URL 校验
    ok, err = _validate_url(url, allowed_domains)
    if not ok:
        return DownloadResult(success=False, output_path="", bytes_downloaded=0, error=err)

    # 2. 文件名校验
    try:
        target_path = _validate_filename(filename, output_dir)
    except ValueError as e:
        return DownloadResult(success=False, output_path="", bytes_downloaded=0, error=str(e))

    # 3. 生成不冲突的目标路径
    final_target = _unique_path(target_path, overwrite=config.overwrite)
    part_path = final_target.with_suffix(final_target.suffix + ".part")

    # 4. 确保输出目录存在
    final_target.parent.mkdir(parents=True, exist_ok=True)

    # 5. 创建安全的 HTTP 客户端
    own_transport = _transport is None
    if own_transport:
        transport = SafeTransport()
    else:
        transport = _transport

    client = httpx.Client(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    )

    bytes_downloaded = 0
    try:
        # 6. 重定向循环
        current_url = url
        current_headers = dict(headers or {})
        visited_urls: set[str] = {url}
        redirect_count = 0

        while redirect_count <= config.max_redirects:
            with client.stream(
                "GET", current_url,
                headers=current_headers,
                timeout=httpx.Timeout(
                    config.connect_timeout,
                    connect=config.connect_timeout,
                    read=config.read_timeout,
                    write=config.read_timeout,
                    pool=config.connect_timeout,
                ),
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirect_count >= config.max_redirects:
                        return DownloadResult(
                            success=False, output_path="", bytes_downloaded=0,
                            error=f"重定向次数超过上限 ({config.max_redirects})",
                        )
                    location = response.headers.get("Location", "")
                    if not location:
                        return DownloadResult(
                            success=False, output_path="", bytes_downloaded=0,
                            error="重定向响应缺少 Location 头",
                        )
                    new_url = urljoin(current_url, location)
                    ok, err = _validate_url(new_url, allowed_domains)
                    if not ok:
                        return DownloadResult(
                            success=False, output_path="", bytes_downloaded=0,
                            error=f"重定向目标被拒绝: {err}",
                        )
                    # 跨域剥离敏感头
                    new_parsed = urlparse(new_url)
                    old_parsed = urlparse(current_url)
                    if (new_parsed.hostname or "").rstrip(".").lower() != \
                       (old_parsed.hostname or "").rstrip(".").lower():
                        current_headers = {
                            k: v for k, v in current_headers.items()
                            if k.lower() not in ("authorization", "cookie", "proxy-authorization")
                        }
                    if new_url in visited_urls:
                        return DownloadResult(
                            success=False, output_path="", bytes_downloaded=0,
                            error="检测到重定向循环",
                        )
                    current_url = new_url
                    visited_urls.add(new_url)
                    redirect_count += 1
                    continue

                break  # 非重定向响应

        # 7. Content-Type 检查
        content_type = response.headers.get("Content-Type", "")
        if not _validate_content_type(content_type, config):
            return DownloadResult(
                success=False, output_path="", bytes_downloaded=0,
                error=f"不支持的 Content-Type: {content_type or '(缺失)'}",
            )

        # 8. Content-Length 检查
        content_length_str = response.headers.get("Content-Length", "")
        content_length: int | None = None
        if content_length_str:
            try:
                content_length = int(content_length_str)
                if content_length > config.max_size_bytes:
                    return DownloadResult(
                        success=False, output_path="", bytes_downloaded=0,
                        error=f"文件大小 ({content_length:,} bytes) 超过限制 ({config.max_size_bytes:,} bytes)",
                    )
            except ValueError:
                pass

        # 9. 磁盘空间预检查
        if content_length:
            ok, err = _check_disk_space(final_target.parent, content_length, config.disk_safety_ratio)
            if not ok:
                return DownloadResult(success=False, output_path="", bytes_downloaded=0, error=err)

        # 10. 流式下载到 .part
        start_time = time_module.monotonic()
        total_timeout = start_time + config.total_timeout
        last_check_bytes = 0
        window_samples: list[tuple[float, int]] = []

        try:
            with open(part_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    now = time_module.monotonic()

                    # 总超时
                    if now > total_timeout:
                        raise TimeoutError("下载总时间超时")

                    f.write(chunk)
                    bytes_downloaded += len(chunk)

                    # 文件大小上限
                    if bytes_downloaded > config.max_size_bytes:
                        raise ValueError(f"实际下载大小超过限制")

                    # 磁盘空间周期检查
                    if not content_length and bytes_downloaded - last_check_bytes >= config.disk_check_interval_bytes:
                        ok, err = _check_disk_space(final_target.parent, bytes_downloaded, 1.1)
                        if not ok:
                            raise OSError(err)
                        last_check_bytes = bytes_downloaded

                    # 低速检测
                    window_samples.append((now, bytes_downloaded))
                    cutoff = now - config.min_speed_window_sec
                    while window_samples and window_samples[0][0] < cutoff:
                        window_samples.pop(0)
                    if len(window_samples) >= 2:
                        window_dur = now - window_samples[0][0]
                        window_bytes = bytes_downloaded - window_samples[0][1]
                        if window_dur >= config.min_speed_window_sec and \
                           window_bytes / window_dur < config.min_speed_bytes_per_sec:
                            raise TimeoutError(
                                f"下载速度过慢: {window_bytes / window_dur:.0f} B/s"
                            )
                # 11. flush + fsync (在 with 块内，文件尚未关闭)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except (TimeoutError, ValueError, OSError) as e:
            _cleanup_part(part_path)
            return DownloadResult(
                success=False, output_path="", bytes_downloaded=bytes_downloaded, error=str(e),
            )

        # 12. 原子改名
        os.replace(part_path, final_target)

        return DownloadResult(
            success=True,
            output_path=str(final_target),
            bytes_downloaded=bytes_downloaded,
        )

    finally:
        if own_transport:
            client.close()


# ---- 网络层 ----

class SafeNetworkBackend(httpcore.SyncBackend):
    """自定义网络后端 — 在 TCP 连接建立前校验 DNS/IP。"""

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: list | None = None,
    ) -> httpcore.NetworkStream:
        public_ips = sorted(_resolve_public_ips(host))
        target_ip = public_ips[0]
        stream = super().connect_tcp(
            target_ip, port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        try:
            peer = stream.get_extra_info("peername")
            if peer and peer[0] not in public_ips:
                stream.close()
                raise OSError(f"连接目标 IP 与预校验不符: {peer[0]}")
        except (AttributeError, KeyError, IndexError, TypeError):
            pass
        return stream


class SafeTransport(httpx.BaseTransport):
    """安全的 httpx 传输层 — 注入自定义 NetworkBackend。"""

    def __init__(self) -> None:
        backend = SafeNetworkBackend()
        self._pool = httpcore.ConnectionPool(network_backend=backend)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=str(request.url),
            headers=list(request.headers.items()),
            content=request.content,
            extensions=request.extensions,
        )
        core_response = self._pool.handle_request(core_request)
        return httpx.Response(
            status_code=core_response.status,
            headers=list(core_response.headers),
            content=core_response.content,
            http_version=core_response.http_version,
            request=request,
        )

    def close(self) -> None:
        self._pool.close()


# ---- 辅助函数 ----

def _check_disk_space(path: Path, needed_bytes: int, ratio: float) -> tuple[bool, str]:
    """检查磁盘剩余空间。"""
    try:
        usage = shutil.disk_usage(path)
        required = int(needed_bytes * ratio)
        if usage.free < required:
            return False, f"磁盘空间不足: 需要 {required:,} bytes, 可用 {usage.free:,} bytes"
        return True, ""
    except OSError as e:
        return False, f"无法检查磁盘空间: {e}"


def _unique_path(target: Path, overwrite: bool = False) -> Path:
    """生成不冲突的文件路径。"""
    if overwrite:
        return target
    stem = target.stem
    ext = target.suffix
    parent = target.parent
    result = target
    counter = 1
    while result.exists():
        result = parent / f"{stem} ({counter}){ext}"
        counter += 1
    return result


def _cleanup_part(part_path: Path) -> None:
    """安全清理 .part 文件。"""
    try:
        if part_path.exists():
            part_path.unlink()
    except OSError:
        pass


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
