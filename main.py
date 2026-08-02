#!/usr/bin/env python3
"""视频下载工具 — 入口脚本。

基于 yt-dlp 的视频下载工具，支持 YouTube、Bilibili、TikTok 等平台。

用法:
    python main.py                # 交互模式，提示输入 URL
    python main.py <URL>          # 直接下载
    python main.py --check        # 仅检查环境
"""

from __future__ import annotations

import sys
from pathlib import Path

from config import load_config, reload_config, validate_config
from downloader import (
    DownloadError,
    check_environment,
    format_env_report,
    run_download,
    run_hybrid_download,
)
from logger import get_logger, log_event, new_task_id, setup_logging
from platforms import detect_platform, extract_url


def _print_banner() -> None:
    """打印横幅。"""
    print()
    print("=" * 48)
    print("  Video Downloader (yt-dlp + FFmpeg)")
    print("  支持: YouTube · Bilibili · TikTok · 抖音 · 更多")
    print("=" * 48)
    print()


def _validate_input(url_text: str) -> tuple[str | None, str | None]:
    """校验用户输入。

    Returns:
        (标准化URL, 错误提示)。成功时错误提示为 None。
    """
    url_text = url_text.strip()

    if not url_text:
        return None, "链接为空，请输入视频链接"

    # 从混合文本中提取 URL
    url = extract_url(url_text)
    if not url:
        return None, "未检测到有效链接，请粘贴包含 http:// 或 https:// 的视频链接"

    # 检查协议
    if not url.startswith(("http://", "https://")):
        return None, f"不支持的协议，仅支持 http/https 链接: {url[:50]}"

    # 基本格式检查: 必须有域名部分
    if "://" in url:
        domain_part = url.split("://")[1].split("/")[0]
        if not domain_part or "." not in domain_part:
            return None, f"链接格式异常，缺少有效域名: {url[:80]}"
    else:
        return None, f"链接格式异常: {url[:80]}"

    return url, None


def main() -> int:
    """主入口。返回 exit code。"""
    # 1. 加载配置
    try:
        config = load_config()
    except Exception as e:
        print(f"[ERROR] 配置文件加载失败: {e}")
        return 1

    # 2. 初始化日志
    log_cfg = config["logging"]
    log_dir = str(Path(__file__).resolve().parent / log_cfg["directory"])
    setup_logging(level=log_cfg["level"], log_directory=log_dir)
    logger = get_logger()

    # 3. 处理命令行参数
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--check", "-c"):
            return cmd_check(config)
        if arg in ("--help", "-h"):
            print("用法: python main.py [URL]")
            print("      python main.py --check  检查运行环境")
            return 0
        url_text = arg
    else:
        _print_banner()
        try:
            url_text = input("请输入视频链接: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 1

    # 4. 校验 URL
    url, error = _validate_input(url_text)
    if error:
        print(f"\n[ERROR] {error}")
        logger.warning(f"invalid_input error=\"{error}\"")
        return 2

    assert url is not None

    # 5. 配置校验
    errors = validate_config(config)
    if errors:
        for e in errors:
            print(f"[WARN] 配置问题: {e}")
            logger.warning(f"config_warning detail=\"{e}\"")

    # 6. 环境检查（首次下载时）
    env_ok, env_detail = _ensure_env_checked(config)
    print(f"\n{env_detail}")

    # 7. 识别平台
    platform = detect_platform(url)
    task_id = new_task_id()

    # 8. 执行下载
    print(f"\n[INFO] 平台: {platform}  |  任务: {task_id}")
    print(f"[INFO] 开始下载...\n")

    log_event(task_id, "download_start", {
        "platform": platform,
        "url": url,
    })

    try:
        run_hybrid_download(config, url, platform=platform)
    except KeyboardInterrupt:
        print("\n[INFO] 用户取消")
        log_event(task_id, "download_cancelled", {"platform": platform}, level="WARNING")
        return 7
    except DownloadError as e:
        print(f"\n[ERROR] {e}")
        log_event(task_id, "download_failed", {
            "platform": platform,
            "exit_code": str(e.exit_code),
            "error": str(e)[:200],
        }, level="ERROR")
        return e.exit_code if e.exit_code > 0 else 1
    except Exception as e:
        print(f"\n[ERROR] 未知错误: {e}")
        log_event(task_id, "download_failed", {
            "platform": platform,
            "error": str(e)[:200],
        }, level="ERROR")
        logger.exception("unexpected_error")
        return 1

    # 9. 成功
    print(f"\n[OK] 下载完成! 文件保存在: {config['downloader']['output_dir']}/")
    log_event(task_id, "download_complete", {"platform": platform})
    return 0


def cmd_check(config: dict) -> int:
    """仅检查环境并退出。"""
    print("Video Downloader — 环境检查")
    print(f"Python: {sys.version}")
    print()

    # 重新加载配置（绕过缓存）
    reload_config()

    env = check_environment(config)
    print(format_env_report(env))

    errors = validate_config(config)
    if errors:
        print(f"\n配置问题 ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    else:
        print("\n配置: 正常")

    all_ok = all(ok for ok, _ in env.values())
    return 0 if all_ok else 1


# ---- 环境检查缓存 ----
_env_checked: bool = False
_env_result: tuple[bool, str] = (False, "")


def _ensure_env_checked(config: dict) -> tuple[bool, str]:
    """首次调用时执行环境检查，后续调用返回缓存结果。"""
    global _env_checked, _env_result
    if _env_checked:
        return _env_result

    env = check_environment(config)
    detail = format_env_report(env)
    all_ok = all(ok for ok, _ in env.values())

    if not all_ok:
        logger = get_logger()
        for tool, (ok, detail_item) in env.items():
            if not ok:
                logger.warning(f"tool_missing tool={tool} detail=\"{detail_item}\"")

    _env_checked = True
    _env_result = (all_ok, detail)
    return _env_result


if __name__ == "__main__":
    sys.exit(main())
