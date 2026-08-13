"""下载器模块。

封装 yt-dlp 调用，集成自定义提取器。

下载策略（按优先级）:
    1. 自定义提取器 (extractors/) → 直接获取 CDN 视频链接
    2. yt-dlp → 覆盖大部分平台
    3. 自定义提取器提取出的直链也交给 yt-dlp 下载
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from extractors.http_downloader import DownloadResult, download as safe_download
from logger import get_logger, log_event, new_task_id


class DownloadError(Exception):
    """下载失败异常。"""

    def __init__(self, message: str, exit_code: int = -1):
        super().__init__(message)
        self.exit_code = exit_code


class ToolNotFoundError(DownloadError):
    """依赖工具未找到。"""


class NetworkError(DownloadError):
    """网络错误。"""


class UnsupportedURLError(DownloadError):
    """不支持的 URL。"""


class AuthenticationError(DownloadError):
    """需要登录或权限不足。"""


class MergeError(DownloadError):
    """音视频合并失败。"""


# yt-dlp exit code → 异常类型和用户消息
_EXIT_CODE_MAP: dict[int, tuple[type[DownloadError], str, str]] = {
    0: (DownloadError, "下载成功", ""),  # 成功，不会触发异常
    1: (DownloadError, "下载失败", "一般错误，请检查 URL 和网络"),
    2: (DownloadError, "参数错误", "下载参数配置有误"),
    3: (NetworkError, "网络错误", "请检查网络连接或代理设置"),
    4: (AuthenticationError, "访问被拒绝", "该视频可能需要登录或已设置地区限制"),
    5: (UnsupportedURLError, "不支持的链接", "当前不支持该平台或链接格式"),
    6: (DownloadError, "解析失败", "无法提取视频信息，页面可能已变更"),
    7: (DownloadError, "下载被禁止", "该视频可能因版权等原因禁止下载"),
}


def classify_exit_code(exit_code: int) -> tuple[str, str]:
    """根据 yt-dlp exit code 返回 (错误类型, 用户提示)。"""
    if exit_code == 0:
        return ("成功", "")
    info = _EXIT_CODE_MAP.get(exit_code)
    if info:
        return (info[1], info[2])
    return ("未知错误", f"yt-dlp 退出码: {exit_code}，请尝试使用 --verbose 查看详情")


def build_command(config: dict[str, Any], url: str) -> list[str]:
    """根据配置构建 yt-dlp 命令行参数列表。

    Args:
        config: 完整配置字典
        url: 视频 URL

    Returns:
        参数列表，可直接传给 subprocess.run()
    """
    dl = config["downloader"]
    tools = config["tools"]
    browser = config["browser"]
    audio = config["audio"]

    root = Path(__file__).resolve().parent
    output_dir = root / dl["output_dir"]

    cmd = [
        tools["yt_dlp_path"],
        "-f", dl["format"],
        "--merge-output-format", dl["merge_format"],
        "--no-overwrites",
    ]

    # 断点续传
    if dl.get("continue_download", True):
        cmd.append("--continue")

    # 下载列表
    if not dl.get("playlist", False):
        cmd.append("--no-playlist")

    # 超时
    timeout = dl.get("socket_timeout", 30)
    cmd.extend(["--socket-timeout", str(timeout)])

    # 重试
    retries = dl.get("retries", 5)
    cmd.extend(["--retries", str(retries)])

    # Cookie
    cookie_mode = config.get("cookies", {}).get("mode", "none")
    if cookie_mode == "browser":
        cmd.extend(["--cookies-from-browser", browser.get("cookies_from_browser", "chrome")])
    elif cookie_mode == "file":
        cookie_file = config.get("cookies", {}).get("file", "")
        if cookie_file:
            cmd.extend(["--cookies", cookie_file])
    # mode=none: 不传任何 cookie 参数

    # 浏览器伪装（curl_cffi 提供 TLS 指纹模拟，抖音等平台需要）
    impersonate = config.get("impersonate", {}).get("target", "")
    if impersonate:
        cmd.extend(["--impersonate", impersonate])

    # JS 运行时（部分网站需要）
    deno_path = tools.get("deno_path", "")
    if deno_path:
        cmd.extend(["--js-runtimes", f"deno:{deno_path}"])

    # FFmpeg 路径
    ffmpeg_path = tools.get("ffmpeg_path", "")
    if ffmpeg_path:
        cmd.extend(["--ffmpeg-location", ffmpeg_path])

    # 音频后处理参数
    codec = audio.get("codec", "aac")
    bitrate = audio.get("bitrate", "192k")
    cmd.extend(["--postprocessor-args", f"ffmpeg:-c:a {codec} -b:a {bitrate}"])

    # 平台特定配置覆盖
    platforms_cfg = config.get("platforms", {})
    if platforms_cfg:
        from platforms import detect_platform
        plat = detect_platform(url)
        plat_override = platforms_cfg.get(plat, {})
        if plat_override:
            if "format" in plat_override:
                # 替换 format 参数
                fmt_idx = cmd.index("-f")
                if fmt_idx >= 0:
                    cmd[fmt_idx + 1] = plat_override["format"]
            if "user_agent" in plat_override:
                cmd.extend(["--user-agent", plat_override["user_agent"]])
            if "referer" in plat_override:
                cmd.extend(["--referer", plat_override["referer"]])
            # 注意: 如果平台配置带了 proxy，不要在这里加
            # proxy 由 network.proxy 统一控制

    # 代理
    proxy = config.get("network", {}).get("proxy", "")
    if proxy:
        cmd.extend(["--proxy", proxy])

    # 输出路径
    cmd.extend(["-o", str(output_dir / "%(title)s.%(ext)s")])

    # 中间文件放到临时目录，避免污染输出目录
    cmd.extend(["--paths", f"temp:{output_dir / '.tmp'}"])

    # URL 最后传入
    cmd.append(url)

    return cmd


def check_tool(path: str, name: str) -> tuple[bool, str]:
    """检查工具是否可用。返回 (可用, 版本信息)。"""
    try:
        resolved_path = str(Path(path))
        version_args: dict[str, list[str]] = {
            "yt-dlp": ["--version"],
            "ffmpeg": ["-version"],
            "deno": ["--version"],
        }
        args = version_args.get(name, ["--version"])
        result = subprocess.run(
            [resolved_path, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # FFmpeg 将版本信息输出到 stderr
            version = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
            return True, version
        return False, f"exit code: {result.returncode}"
    except FileNotFoundError:
        return False, f"文件未找到: {path}"
    except subprocess.TimeoutExpired:
        return False, "检查超时"
    except PermissionError:
        return False, "没有执行权限"
    except OSError as e:
        return False, str(e)


def check_environment(config: dict[str, Any]) -> dict[str, tuple[bool, str]]:
    """检查运行环境。返回 {工具名: (可用, 详情)}。"""
    tools = config["tools"]
    results: dict[str, tuple[bool, str]] = {}

    results["yt-dlp"] = check_tool(tools["yt_dlp_path"], "yt-dlp")
    results["ffmpeg"] = check_tool(tools["ffmpeg_path"], "ffmpeg")

    deno_path = tools.get("deno_path", "")
    if deno_path and Path(deno_path).exists():
        results["deno"] = check_tool(deno_path, "deno")

    return results


def format_env_report(env_check: dict[str, tuple[bool, str]]) -> str:
    """格式化环境检查报告。"""
    lines = ["环境检查:"]
    all_ok = True
    for tool, (ok, detail) in env_check.items():
        status = "[OK]" if ok else "[FAIL]"
        lines.append(f"  {status} {tool}: {detail}")
        if not ok:
            all_ok = False
    if all_ok:
        lines.append("所有工具就绪")
    else:
        lines.append("部分工具不可用，下载可能受限")
    return "\n".join(lines)


def _cleanup_temp(output_dir: Path, tmp_dir: Path) -> None:
    """删除临时文件和临时目录。

    兼容两种场景：
    - yt-dlp 的 --paths temp:（.tmp 目录）
    - 旧的 .temp. 前缀文件（如 .temp.mp4）

    删除失败时仅静默跳过，不影响主流程。
    """
    # 清理 .tmp 目录
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 清理旧版残留：.temp.* 文件
    try:
        for f in output_dir.glob(".temp.*"):
            f.unlink(missing_ok=True)
    except OSError:
        pass


def build_direct_command(
    video: Any,
    output_dir: Path,
    config: dict[str, Any],
) -> list[str]:
    """为 CDN 直链构建 yt-dlp 下载命令。

    Args:
        video: VideoInfo — 提取器返回的视频信息（url, title, ext, headers）
        output_dir: 下载输出目录
        config: 完整配置

    Returns:
        yt-dlp 参数列表（可传给 subprocess）
    """
    dl = config["downloader"]
    tools = config["tools"]

    # 安全文件名
    safe_title = "".join(c for c in video.title if c not in r'<>:"/\|?*')[:100]
    if not safe_title.strip():
        safe_title = f"{video.platform}_video"
    filename = f"{safe_title}.{video.ext}"

    cmd = [
        tools["yt_dlp_path"],
        "-f", dl["format"],
        "--merge-output-format", dl["merge_format"],
        "--no-overwrites",
    ]

    if dl.get("continue_download", True):
        cmd.append("--continue")

    # 超时 & 重试
    timeout = dl.get("socket_timeout", 30)
    cmd.extend(["--socket-timeout", str(timeout)])
    retries = dl.get("retries", 5)
    cmd.extend(["--retries", str(retries)])

    # 输出路径
    cmd.extend(["-o", str(output_dir / filename)])

    # Referer + User-Agent（从 VideoInfo.headers）
    for key, flag in [("User-Agent", "--user-agent"), ("Referer", "--referer")]:
        value = video.headers.get(key, "")
        if value:
            cmd.extend([flag, value])

    # 代理
    proxy = config.get("network", {}).get("proxy", "")
    if proxy:
        cmd.extend(["--proxy", proxy])

    # Cookie
    cookie_mode = config.get("cookies", {}).get("mode", "none")
    if cookie_mode == "browser":
        browser_name = config.get("browser", {}).get("cookies_from_browser", "chrome")
        cmd.extend(["--cookies-from-browser", browser_name])
    elif cookie_mode == "file":
        cookie_file = config.get("cookies", {}).get("file", "")
        if cookie_file:
            cmd.extend(["--cookies", cookie_file])

    # URL
    cmd.append(video.url)

    return cmd


def run_download(config: dict[str, Any], url: str) -> subprocess.CompletedProcess[str]:
    """执行下载，Chrome Cookie 锁定自动回退。

    Args:
        config: 完整配置
        url: 视频 URL

    Returns:
        subprocess.CompletedProcess 对象

    Raises:
        DownloadError: 下载、合并、环境等问题
    """
    cmd = build_command(config, url)

    root = Path(__file__).resolve().parent
    output_dir = root / config["downloader"]["output_dir"]
    tmp_dir = output_dir / ".tmp"

    # 下载前清理残留的临时文件
    _cleanup_temp(output_dir, tmp_dir)

    result = _run_process(cmd, output_dir, tmp_dir)

    # Chrome Cookie 锁定 → 自动回退无 Cookie 模式
    if result.returncode != 0 and "Could not copy Chrome cookie database" in result.stdout:
        print("\n[WARN] Chrome Cookie 读取失败 (Chrome 正在运行)")
        print("[INFO] 自动切换为无 Cookie 模式重试...\n")

        # 重建不带 cookie 参数的命令（同时跳过参数名和参数值）
        cmd_no_cookie: list[str] = []
        skip_next = False
        for arg in cmd:
            if skip_next:
                skip_next = False
                continue
            if arg.startswith("--cookies"):
                # 如果是 "--cookies-from-browser chrome" 这种带值的参数，跳过下一个参数
                if "=" not in arg:
                    skip_next = True
                continue
            cmd_no_cookie.append(arg)
        result = _run_process(cmd_no_cookie, output_dir, tmp_dir)

    if result.returncode != 0:
        error_type, user_msg = classify_exit_code(result.returncode)
        error_cls = _EXIT_CODE_MAP.get(result.returncode, (DownloadError, "未知错误", ""))[0]

        full_output = result.stdout
        if "ffmpeg" in full_output.lower() and "error" in full_output.lower():
            error_cls = MergeError
            user_msg = "音视频合并失败，请检查 FFmpeg 是否正确安装"

        _cleanup_temp(output_dir, tmp_dir)

        raise error_cls(
            f"{error_type}: {user_msg}\n详情: {full_output[-500:]}",
            exit_code=result.returncode,
        )

    _cleanup_temp(output_dir, tmp_dir)
    return result


def _run_process(
    cmd: list[str],
    output_dir: Path,
    tmp_dir: Path,
) -> subprocess.CompletedProcess[str]:
    """执行子进程，实时输出并收集结果。"""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    collected_output: list[str] = []
    try:
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip()
                if len(line) < 300:
                    print(line, flush=True)
                collected_output.append(line)
        exit_code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=exit_code,
        stdout="\n".join(collected_output),
        stderr="",
    )


def run_hybrid_download(
    config: dict[str, Any],
    url: str,
    platform: str = "unknown",
    task_id: str | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """混合下载：根据 network.mode 选择下载引擎。

    auto 模式 (默认):
        1. 提取器 → yt-dlp 下载直链（通过 build_direct_command）
        2. 失败 → 原始 URL yt-dlp 回退
        3. 无提取器 → 原始 URL yt-dlp

    strict 模式:
        1. 提取器 → SafeTransport/safe_download 安全下载
        2. 失败 → 原始 URL yt-dlp 回退
        3. 无提取器 → 原始 URL yt-dlp
    """
    network_mode = config.get("network", {}).get("mode", "auto")

    if network_mode == "auto":
        return _download_auto(config, url, platform, task_id)
    elif network_mode == "strict":
        return _download_strict(config, url, platform, task_id)
    else:
        raise DownloadError(
            f"network.mode 无效: {network_mode}，应为 auto 或 strict",
            exit_code=2,
        )


def _download_auto(
    config: dict[str, Any],
    url: str,
    platform: str = "unknown",
    task_id: str | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """auto 模式：提取器直链 → yt-dlp 下载。"""
    from extractors import find_extractor

    if task_id is None:
        task_id = new_task_id()
    log_event(task_id, "hybrid_download_start", {"platform": platform, "url": url, "mode": "auto"})

    ext = find_extractor(url)
    if ext is None:
        log_event(task_id, "no_extractor_found", {"platform": platform})
        return run_download(config, url)

    log_event(task_id, "extractor_start", {"platform": ext.platform})
    print(f"\n[INFO] 检测到 {ext.platform} 链接，尝试专用提取器...")

    # --- 提取器阶段 ---
    try:
        result = ext.extract(url)
    except Exception as extractor_exc:
        log_event(task_id, "extractor_failed", {
            "platform": ext.platform, "error_type": type(extractor_exc).__name__,
            "error": str(extractor_exc)[:200],
        }, level="WARNING")
        print(f"[WARN] 提取器异常: {extractor_exc}，回退到 yt-dlp")
        log_event(task_id, "fallback_start", {"platform": platform, "reason": "extractor_exception"})
        try:
            fb_result = run_download(config, url)
            log_event(task_id, "fallback_complete", {"platform": platform})
            return fb_result
        except DownloadError as yt_error:
            log_event(task_id, "fallback_failed", {
                "platform": platform,
                "error_type": type(yt_error).__name__,
                "error": str(yt_error)[:300],
            }, level="ERROR")
            raise DownloadError(
                f"提取器异常: {extractor_exc}\n"
                f"yt-dlp 回退也失败: {yt_error}",
                exit_code=yt_error.exit_code if yt_error.exit_code > 0 else -1,
            )

    if not result.success:
        log_event(task_id, "extractor_failed", {
            "platform": ext.platform, "error": (result.error or "")[:200],
        }, level="WARNING")
        print(f"[WARN] 提取器失败: {result.error}")
        print("[INFO] 回退到 yt-dlp 下载...")
        log_event(task_id, "fallback_start", {"platform": platform, "reason": "extractor_no_result"})
        try:
            fb_result = run_download(config, url)
            log_event(task_id, "fallback_complete", {"platform": platform})
            return fb_result
        except DownloadError as yt_error:
            log_event(task_id, "fallback_failed", {
                "platform": platform,
                "error_type": type(yt_error).__name__,
                "error": str(yt_error)[:300],
            }, level="ERROR")
            raise DownloadError(
                f"{result.error}\n\n"
                "专用提取器和 yt-dlp 均失败。\n"
                f"yt-dlp 错误: {yt_error}",
                exit_code=yt_error.exit_code if yt_error.exit_code > 0 else -1,
            )

    # --- 提取成功 → yt-dlp 下载直链 ---
    videos = result.videos
    print(f"[OK] 提取器获取到 {len(videos)} 个视频地址")

    root = Path(__file__).resolve().parent
    output_dir = root / config["downloader"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    log_event(task_id, "extractor_success", {
        "platform": ext.platform, "video_count": str(len(videos)),
    })
    log_event(task_id, "direct_download_start", {
        "video_count": str(len(videos)), "engine": "yt-dlp",
    })

    direct_errors: list[str] = []
    success_count = 0
    for i, video in enumerate(videos):
        print(f"\n[{i + 1}/{len(videos)}] {video.title or video.url[:60]}")

        cmd = build_direct_command(video, output_dir, config)
        tmp_dir = output_dir / ".tmp"

        try:
            proc_result = _run_process(cmd, output_dir, tmp_dir)
        except (httpx.TransportError, ConnectionError, OSError) as e:
            direct_errors.append(f"[{video.title}] {e}")
            continue

        if proc_result.returncode == 0:
            print(f"  [OK] yt-dlp 下载成功")
            success_count += 1
        else:
            err = f"yt-dlp exit code {proc_result.returncode}"
            print(f"  [FAIL] {err}")
            direct_errors.append(f"[{video.title}] {err}")

        _cleanup_temp(output_dir, tmp_dir)

    if success_count > 0:
        print(f"\n[OK] 成功下载 {success_count}/{len(videos)} 个视频")
        log_event(task_id, "direct_download_complete", {
            "platform": platform, "success_count": str(success_count),
            "total_videos": str(len(videos)),
        })
        return subprocess.CompletedProcess(args=["yt-dlp"], returncode=0, stdout="", stderr="")

    # --- 全部直链失败 → 回退 yt-dlp（原始页面 URL）---
    fallback_reason = "; ".join(direct_errors[:3])
    log_event(task_id, "direct_download_failed", {
        "platform": platform, "reason": fallback_reason[:300],
    }, level="WARNING")
    print(f"\n[WARN] 直链下载全部失败，回退到 yt-dlp（原始 URL）...")

    log_event(task_id, "fallback_start", {
        "platform": platform, "reason": "direct_ytdlp_failed",
    })
    try:
        fb_result = run_download(config, url)
        log_event(task_id, "fallback_complete", {"platform": platform})
        return fb_result
    except DownloadError as yt_error:
        log_event(task_id, "fallback_failed", {
            "platform": platform,
            "error_type": type(yt_error).__name__,
            "error": str(yt_error)[:300],
        }, level="ERROR")
        raise DownloadError(
            f"直链下载失败: {fallback_reason}\n"
            f"yt-dlp 回退也失败: {yt_error}",
            exit_code=yt_error.exit_code if yt_error.exit_code > 0 else -1,
        )


def _download_strict(
    config: dict[str, Any],
    url: str,
    platform: str = "unknown",
    task_id: str | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """strict 模式：提取器直链 → SafeTransport/safe_download 安全下载。"""
    from extractors import find_extractor

    if task_id is None:
        task_id = new_task_id()
    log_event(task_id, "hybrid_download_start", {"platform": platform, "url": url, "mode": "strict"})

    ext = find_extractor(url)
    if ext is None:
        log_event(task_id, "no_extractor_found", {"platform": platform})
        _warn_strict_fallback()
        return run_download(config, url)

    log_event(task_id, "extractor_start", {"platform": ext.platform})
    print(f"\n[INFO] 检测到 {ext.platform} 链接，尝试专用提取器（strict 模式）...")

    # --- 提取器阶段 ---
    try:
        result = ext.extract(url)
    except Exception as extractor_exc:
        log_event(task_id, "extractor_failed", {
            "platform": ext.platform, "error_type": type(extractor_exc).__name__,
            "error": str(extractor_exc)[:200],
        }, level="WARNING")
        print(f"[WARN] 提取器异常: {extractor_exc}，回退到 yt-dlp")
        _warn_strict_fallback()
        log_event(task_id, "fallback_start", {"platform": platform, "reason": "extractor_exception"})
        try:
            fb_result = run_download(config, url)
            log_event(task_id, "fallback_complete", {"platform": platform})
            return fb_result
        except DownloadError as yt_error:
            log_event(task_id, "fallback_failed", {
                "platform": platform,
                "error_type": type(yt_error).__name__,
                "error": str(yt_error)[:300],
            }, level="ERROR")
            raise DownloadError(
                f"提取器异常: {extractor_exc}\n"
                f"yt-dlp 回退也失败: {yt_error}",
                exit_code=yt_error.exit_code if yt_error.exit_code > 0 else -1,
            )

    if not result.success:
        log_event(task_id, "extractor_failed", {
            "platform": ext.platform, "error": (result.error or "")[:200],
        }, level="WARNING")
        print(f"[WARN] 提取器失败: {result.error}")
        print("[INFO] 回退到 yt-dlp 下载...")
        _warn_strict_fallback()
        log_event(task_id, "fallback_start", {"platform": platform, "reason": "extractor_no_result"})
        try:
            fb_result = run_download(config, url)
            log_event(task_id, "fallback_complete", {"platform": platform})
            return fb_result
        except DownloadError as yt_error:
            log_event(task_id, "fallback_failed", {
                "platform": platform,
                "error_type": type(yt_error).__name__,
                "error": str(yt_error)[:300],
            }, level="ERROR")
            raise DownloadError(
                f"{result.error}\n\n"
                "专用提取器和 yt-dlp 均失败。\n"
                f"yt-dlp 错误: {yt_error}",
                exit_code=yt_error.exit_code if yt_error.exit_code > 0 else -1,
            )

    # --- 提取成功 → safe_download（strict 安全下载）---
    videos = result.videos
    print(f"[OK] 提取器获取到 {len(videos)} 个视频地址")

    root = Path(__file__).resolve().parent
    output_dir = root / config["downloader"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    dl_cfg = config["downloader"]
    from extractors.http_downloader import DownloadConfig
    safe_config = DownloadConfig(
        connect_timeout=float(dl_cfg.get("socket_timeout", 30)),
        read_timeout=300.0,
        max_retries=dl_cfg.get("retries", 3),
    )

    log_event(task_id, "extractor_success", {
        "platform": ext.platform, "video_count": str(len(videos)),
    })
    log_event(task_id, "direct_download_start", {
        "video_count": str(len(videos)), "engine": "safe_download",
    })

    direct_errors: list[str] = []
    success_count = 0
    total_bytes = 0
    for i, video in enumerate(videos):
        title = video.title or f"{ext.platform}_{i}"
        safe_title = "".join(c for c in title if c not in r'<>:"/\|?*')[:100]
        if not safe_title.strip():
            safe_title = f"{ext.platform}_video_{i}"
        filename = f"{safe_title}.{video.ext}"

        print(f"\n[{i + 1}/{len(videos)}] {safe_title}")
        print(f"  地址: {video.url[:80]}...")

        try:
            dl_result = safe_download(
                url=video.url,
                output_dir=output_dir,
                filename=filename,
                headers={
                    "User-Agent": video.headers.get("User-Agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"),
                    "Referer": video.headers.get("Referer", "https://www.douyin.com/"),
                },
                config=safe_config,
            )
        except (httpx.TransportError, ConnectionError) as e:
            dl_result = DownloadResult(success=False, output_path="", bytes_downloaded=0, error=str(e))

        if dl_result.success:
            print(f"  [OK] 已保存: {dl_result.output_path}")
            success_count += 1
            total_bytes += getattr(dl_result, "bytes_downloaded", 0)
        else:
            err = getattr(dl_result, "error", "未知错误") or "未知错误"
            print(f"  [FAIL] 下载失败: {err}")
            direct_errors.append(f"[{safe_title}] {err}")

    if success_count > 0:
        print(f"\n[OK] 成功下载 {success_count}/{len(videos)} 个视频")
        log_event(task_id, "direct_download_complete", {
            "platform": platform, "success_count": str(success_count),
            "total_videos": str(len(videos)), "bytes_downloaded": str(total_bytes),
        })
        return subprocess.CompletedProcess(args=["extractor"], returncode=0, stdout="", stderr="")

    # --- 全部直链失败 → 回退 yt-dlp ---
    fallback_reason = "; ".join(direct_errors[:3])
    log_event(task_id, "direct_download_failed", {
        "platform": platform, "reason": fallback_reason[:300],
    }, level="WARNING")
    print(f"\n[WARN] 直链下载全部失败，回退到 yt-dlp...")
    _warn_strict_fallback()

    log_event(task_id, "fallback_start", {
        "platform": platform, "reason": "direct_download_failed",
    })
    try:
        fb_result = run_download(config, url)
        log_event(task_id, "fallback_complete", {"platform": platform})
        return fb_result
    except DownloadError as yt_error:
        log_event(task_id, "fallback_failed", {
            "platform": platform,
            "error_type": type(yt_error).__name__,
            "error": str(yt_error)[:300],
        }, level="ERROR")
        raise DownloadError(
            f"直链下载失败: {fallback_reason}\n"
            f"yt-dlp 回退也失败: {yt_error}",
            exit_code=yt_error.exit_code if yt_error.exit_code > 0 else -1,
        )


def _warn_strict_fallback() -> None:
    """说明 strict 模式回退 yt-dlp 时的安全边界。"""
    print("[WARN] 已回退 yt-dlp，此阶段不受 strict IP 校验保护")
