# HTTP Downloader 流式下载修复 — 设计规格

**日期**: 2026-08-03
**状态**: 已确认，进入实现

---

## 根因摘要

| # | 根因 | 影响 |
|---|------|------|
| 1 | `SafeTransport.handle_request` 使用错误的 httpcore API（`content=resp.content` + 不存在的 `http_version`） | 所有流式请求崩溃 |
| 2 | `response.iter_bytes()` 在 `with client.stream()` 退出后调用，流已关闭 | 非重定向响应在重定向循环后会抛 `StreamClosed` |
| 3 | 直链下载失败不回退 yt-dlp | 一个 HTTP 适配器问题导致整个抖音下载失败 |
| 4 | `retries`/`socket_timeout` 未传给安全下载器 | 网络波动时缺乏重试能力 |
| 5 | `str(e)[:200]` 截断尾部关键错误 | yt-dlp 最后几行的错误原因丢失 |

## 修改范围

### 文件 1: `extractors/http_downloader.py`

**SafeTransport.handle_request** — 对齐 httpx 内置传输层契约：
- `request.content` → `request.stream`（httpcore 请求体）
- `core_response.content` → `core_response.stream`（流式 body）
- `core_response.http_version` → `core_response.extensions`（扩展字典）
- 新增 `_ResponseStream` 内联类（避免依赖 httpx 私有 `ResponseStream`），实现 `SyncByteStream` 协议：`__iter__` + `close()`

**download() 流生命周期** — 下载循环移入 with 块：
- 每个重定向迭代独立 `with client.stream()` → 内部处理 redirect → 非重定向时在同一个 with 块内执行 `response.iter_bytes()`
- 不覆盖时的 `_unique_path` 在循环前调用一次

**DownloadConfig** — 新增重试配置：
- 新增字段：`max_retries: int = 3`
- 重试逻辑：只对网络异常（ConnectError、ReadError、ReadTimeout 等）重试

### 文件 2: `downloader.py`

**run_hybrid_download** — 回退链路：
- 提取器成功 → `safe_download(CDN URL)`
  - 成功 → 返回成功
  - 失败 → **新**：用原始 `url` 回退 `run_download()`（yt-dlp）
    - 成功 → 返回成功
    - 失败 → 报告两阶段错误
- 提取器失败 → 回退 `run_download()`（现有逻辑保留）

**配置贯通** — 从 config 读取 retries/socket_timeout 构建 DownloadConfig。

**异常处理**：
- `KeyboardInterrupt` 直接传播
- 预期网络异常（httpx.NetworkError、httpx.TimeoutException）→ 返回 `success=False`
- 意外异常 → 记录但不吞掉

### 文件 3: `main.py`

- `str(e)[:200]` → `str(e)[-1000:]`（保留尾部关键错误，日志系统已做脱敏）

### 文件 4: `logger.py`

- `log_event` 字符串截断阈值从 200 → 1000

### 文件 5: `tests/test_http_downloader.py`

新增回归测试：
1. `TestSafeTransportHandleRequest` — 验证 status/headers/streaming body/extensions/close 传播
2. `TestStreamingLifecycle` — 验证数据在 `with` 块内读取、无 StreamClosed、原子写入
3. `TestStreamReadMidFailure` — 验证中途失败清理 .part、不留损坏文件
4. `TestNetworkErrorHandling` — ConnectError/ReadError 等转换为受控结果
5. `TestHybridFallback` — 直链失败回退 yt-dlp、两阶段都失败保留错误上下文
6. 原有安全测试全部继续通过

## 不改的部分

- SSRF/DNS/IP 校验
- 重定向限制和安全校验
- 文件名校验（路径穿越、Windows 保留名）
- Content-Type 白名单
- 文件大小和磁盘空间检查
- 原子写入（.part → os.replace）
- 敏感信息脱敏
