# HTTP 直链安全下载器 — 设计规格

**日期**: 2026-08-02
**范围**: `extractors/http_downloader.py`（新增模块）、`downloader.py`（集成）
**状态**: 已确认

---

## 背景

`downloader._download_direct_url()` 目前直接下载 CDN 视频直链，没有域名校验、
私网 IP 过滤、文件大小限制和原子写入。这是攻击链中的 L4 — L5 环节
（URL 伪造 → SSRF → 磁盘写满 → 文件名注入）。

## 架构

```
extractors/http_downloader.py   ← 新增：独立的安全下载器
downloader.py                   ← 修改：删除 _download_direct_url，导入新模块
extractors/base.py              ← 不改动
```

`http_downloader` 不依赖项目的任何其他模块。它是一个独立模块，输入
URL + 安全约束，返回 `DownloadResult`。

## 公开 API

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DownloadConfig:
    max_size_bytes: int = 2 * 1024 * 1024 * 1024   # 单文件最大 2GB
    connect_timeout: float = 30.0                    # 连接超时
    read_timeout: float = 300.0                      # 单次读取超时
    total_timeout: float = 600.0                     # 整体超时（自然时间）
    min_speed_bytes_per_sec: int = 1024              # 最低速度 1KB/s
    min_speed_window_sec: float = 30.0               # 速度检测窗口
    allowed_content_types: tuple[str, ...] = (
        "video/",
        "application/octet-stream",
    )
    max_redirects: int = 3                           # 最大重定向次数
    overwrite: bool = False                          # 是否覆盖已有文件
    disk_safety_ratio: float = 1.2                   # 磁盘余量系数
    disk_check_interval_bytes: int = 64 * 1024 * 1024  # 磁盘检查间隔

@dataclass(frozen=True)
class DownloadResult:
    success: bool              # 是否成功
    output_path: str           # 输出文件路径
    bytes_downloaded: int      # 实际下载字节数
    error: str = ""            # 失败原因
```

## 安全要求

### 1. 协议白名单

只允许 `http`、`https`。拒绝 `file`、`ftp`、`data`、`javascript` 及所有其他协议。

### 2. 禁止 URL 中携带用户信息

拒绝 `https://user:pass@host/path` 格式。

### 3. 域名白名单

当 `allowed_domains` 不为 `None` 时：
- 统一小写、去掉末尾 `.`、IDNA 规范化
- 严格后缀匹配：`cdn.example.com` 通过，`cdn.example.com.evil.com` 拒绝
- 重定向后的每个目标都重新检查

### 4. 私网及特殊 IP 拦截

每次请求前解析 hostname 的全部 A/AAAA 地址：
- 用 `ipaddress.ip_address().is_global` 统一判断
- 拒绝 private、loopback、link-local、multicast、reserved、unspecified
- IPv4: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 0.0.0.0/8, 224.0.0.0/4, 240.0.0.0/4
- IPv6: ::1, fc00::/7, fd00::/8, fe80::/10
- 公网+私网混合解析 → 拒绝
- DNS 解析失败 → 拒绝（失败关闭）

### 5. DNS 重绑定防护

自定义 `httpcore.NetworkBackend`，重写 `connect_tcp()`：
1. 自行调用 `socket.getaddrinfo()` 解析 DNS
2. 校验所有解析出的 IP
3. 用校验通过的 IP 发起 TCP 连接
4. 连接后 `getpeername` 二次确认

httpcore 不再自行解析 DNS，消除 TOCTOU 窗口。

**残余风险**：本机 hosts 文件被篡改、链路上 DNS 未加密。

### 6. 禁用代理

`trust_env=False`，不自动继承 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量。
后续如果需要代理，另外增加显式配置并重新定义安全边界。

### 7. 重定向处理

- `follow_redirects=False`
- 迭代循环（不递归），最多 `max_redirects` 次
- 每次对目标 URL 重新执行协议、域名、DNS/IP 检查
- 跨域重定向时剥离 `Authorization`、`Cookie`、`Proxy-Authorization`
- 检测重定向循环

### 8. Content-Type 校验

- 转小写、去掉 `; charset=...` 等参数
- 允许 `video/*`、`application/octet-stream`
- 拒绝 `text/html`、`application/json`、`text/plain`、`application/xml`
- 缺少 Content-Type → 拒绝

### 9. 文件大小限制

- 响应头 `Content-Length` > 上限 → 立即拒绝
- 下载过程中累计字节 > 上限 → 中断
- 不信任服务器声明的长度

### 10. 超时及低速检测

- 连接超时 30s、单次读取超时 300s、整体超时 600s（用 `time.monotonic()`）
- 低速检测用滑动窗口（`min_speed_window_sec` 内平均速度 < `min_speed_bytes_per_sec`）
- 0 字节长时间不返回由 read timeout 覆盖

### 11. 文件名安全（纵深防御）

即使调用方已清洗文件名，本模块仍做二次防御：
- 拒绝绝对路径、`..`、`/`、`\`、NUL、控制字符
- 拒绝 Windows 保留名称（CON、PRN、AUX、NUL、COM1-9、LPT1-9）
- 去掉末尾空格和点
- 确保解析后的路径在 `output_dir.resolve()` 之内

### 12. 不覆盖已有文件

- `overwrite=False` → 自动加序号：`video (1).mp4`、`video (2).mp4`...
- `.part` 文件也使用不冲突的名称

### 13. 磁盘空间检查

- 有 `Content-Length`：`剩余空间 >= Content-Length × disk_safety_ratio`
- 无 `Content-Length`：下载前检查一次，之后每 `disk_check_interval_bytes` 检查一次
- 空间不足 → 中断并删除 `.part`

### 14. 原子写入

```
{文件名}.part → 流式下载 → flush → os.replace → 最终文件
```

- 任何失败、取消或超时 → 删除 `.part`
- 最终文件在下载完整以前绝不出现在磁盘上

### 15. 资源释放

- 必须 `with httpx.Client(...) as client:` 管理连接
- 响应也通过上下文管理器关闭
- 所有退出路径均清理 `.part`

### 16. 输出隐私

控制台只显示：下载百分比、已下载大小、总大小、当前速度。
不打印：原始 URL、重定向 URL、CDN 签名参数、Authorization、Cookie、完整请求头。
错误信息最多显示脱敏后的域名。

## 集成方案

### `downloader.py` 改动

1. 删除 `_download_direct_url()` 函数
2. 从 `extractors.http_downloader` 导入 `download`
3. `run_hybrid_download()` 中调用新下载器
4. 删除 `video.url[:80]` 打印
5. 区分全部成功 / 部分成功 / 全部失败
6. 保持现有公开函数不变（`build_command`、`run_download`、`check_environment`）

### `extractors/base.py`

不改动。`VideoInfo.url` 已携带 CDN 链接，提取器域名白名单通过参数传入。

## 测试计划

新增 `tests/test_http_downloader.py`，使用 `httpx.MockTransport`、monkeypatch、
临时目录、伪造 DNS、伪造磁盘空间、可控时间源。禁止真实网络。

### 覆盖矩阵

| 分类 | 测试项 |
|------|--------|
| 协议 | 拒绝非 http/https、拒绝 URL 用户信息 |
| DNS/IP | 拒绝 IPv4 私网、IPv6 私网、混合解析、DNS 失败 |
| 域名白名单 | 严格匹配、子域名通过、拒绝仿冒域名 |
| 重定向 | 重新检查域名和IP、相对路径、循环、超次数、跨域剥离敏感头 |
| Content-Type | 拒绝 HTML/JSON、接受 video/* 和 octet-stream |
| 文件大小 | Content-Length 超限、实际字节超限 |
| 超时 | 整体超时、极慢下载滑动窗口检测 |
| 磁盘 | 开始前空间不足、中途空间不足 |
| 文件系统 | 路径穿越、Windows 保留名、不覆盖、自动序号、原子改名 |
| 资源 | .part 失败清理、client 关闭、response 关闭 |
| 隐私 | 不泄露 URL |
| 集成 | downloader.py 混合流程 mock |

## 提交顺序

1. `test: add security tests for direct HTTP downloads`
2. `feat: add SSRF-safe HTTP downloader module`
3. `refactor: integrate safe downloader into hybrid download flow`
4. `docs: document direct download security model and limitations`
