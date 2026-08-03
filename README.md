# 视频下载器

从视频网站下载视频到本地。支持 B站、抖音、YouTube、TikTok 等几乎所有视频网站。

**普通直连就能用，不需要配置代理。** 如果你已经开了透明代理（Clash、Surge 等），也是直接可用。

---

## 怎么用

**日常使用就三步：**

1. 双击 `下载视频.bat`
2. 粘贴视频链接
3. 回车

下载完的视频在 `videos` 文件夹里。

---

## 第一次安装

### Windows

下面每一步都写了怎么做，跟着来就行。

#### 1. 下载这个项目

点本页面顶部绿色 **<> Code** 按钮 → **Download ZIP** → 解压到桌面。

#### 2. 安装 Python

1. 打开 https://www.python.org/downloads/
2. 点黄色大按钮下载
3. 双击安装
4. ⚠️ 安装窗口底部 **Add Python to PATH** 必须勾上！
5. 点 Install Now

检查：按 `Win + R`，输入 `cmd` 回车，输入 `python --version` 回车。出现 Python 3.x.x 就对了。

#### 3. 安装依赖

打开解压出的项目文件夹 → 空白处 Shift + 右键 → **在此处打开 PowerShell**：

```
pip install -r requirements.txt
```

#### 4. 检查环境

```
python main.py --check
```

三个都 `[OK]` 就行了。

> yt-dlp、FFmpeg、Deno 会被 `pip install -r requirements.txt` 自动安装。如果自动安装失败，也可以手动安装：
> - yt-dlp: `pip install yt-dlp`
> - FFmpeg: `winget install ffmpeg` (或 https://www.gyan.dev/ffmpeg/builds/)
> - Deno: `winget install deno` (可选，部分网站 JS 渲染需要)

### macOS

```bash
# 安装 Python 3.12+
brew install python

# 安装依赖
pip install -r requirements.txt

# 可选：手动安装 FFmpeg
brew install ffmpeg
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install python3 python3-pip ffmpeg
pip install -r requirements.txt
```

---

## 常见问题

**抖音下不了？**

- 试试在抖音 APP 里点"分享" → "复制链接"，用短链接
- 在浏览器打开链接确认视频能播放
- 需要登录的视频：关掉 Chrome 再下载（程序需要读浏览器 Cookie）
- 首次使用需要安装 Playwright 浏览器：`playwright install chromium`

**B站只能下 480P，怎么下高清？**

关掉 Chrome 再下载。Chrome 开着的时候程序读不了登录状态。

**YouTube 下不了？**

如果直连不通，可以在 `config.local.yaml` 里配置代理：

```yaml
network:
  proxy: "http://127.0.0.1:7890"
```

**Chrome Cookie 报错？**

不用管。程序会自动切换模式。只有需要登录的视频才需要关 Chrome。

**支持哪些网站？**

B站、抖音、YouTube、TikTok、小红书、微博、Twitter、Instagram、优酷、腾讯视频、爱奇艺……底层是 yt-dlp，覆盖 1800+ 个网站。

---

## 配置

不要直接改 `config.yaml`。复制一份叫 `config.local.yaml` 再改：

```yaml
# 下载引擎
network:
  mode: auto          # auto = yt-dlp（推荐，直连/透明代理都能用）
                      # strict = 安全直链下载（对网络环境要求高，仅服务器场景推荐）
  proxy: ""           # 可选 HTTP/SOCKS5 代理

# Cookie 来源
cookies:
  mode: none          # none = 不使用 Cookie
                      # browser = 从浏览器读取（需关掉浏览器）
                      # file = 从 cookies.txt 文件读取
  file: ""            # cookies.txt 路径（仅 mode=file 时有效）

downloader:
  output_dir: videos
  format: bestvideo+bestaudio/best
```

### strict 模式的限制

strict 模式使用内置的 DNS/IP 安全校验，会拒绝透明代理（TUN）返回的非公网地址。桌面环境请使用 auto 模式。strict 仅适用于：
- 服务器直连环境（真实 DNS 解析）
- 需要对下载目标做 IP 白名单校验的安全场景

---

## 高级用法

```bash
python main.py "链接"    # 一行命令直接下载
python main.py --check   # 检查环境
```

---

## 技术细节

**下载架构：**

```
auto 模式（默认）：
  原始 URL → 专用提取器（如有）
           → yt-dlp 下载提取出的 CDN 直链
           → 失败则用原始 URL 回退 yt-dlp
  无提取器 → 直接用 yt-dlp

strict 模式：
  原始 URL → 专用提取器（如有）
           → SafeTransport 安全 HTTP 下载
           → 失败则用原始 URL 回退 yt-dlp
```

**抖音下载流程 (auto 模式)：**

```
URL → Playwright 启动 Chrome (headless)
    → 拦截 aweme/detail API 响应
    → 提取 download_addr (无水印 CDN 地址)
    → yt-dlp 下载 CDN 直链（带 User-Agent 和 Referer）
    → 失败则用原始 URL 回退 yt-dlp
```

**文件结构：**

```
main.py           入口
downloader.py     yt-dlp 调用 + 混合下载策略
config.py         配置加载与校验
platforms.py      URL 平台识别
logger.py         日志
extractors/       专用提取器
  base.py         基类 + 注册表
  douyin.py       抖音提取器（Playwright + Chrome）
  http_downloader.py  SafeTransport 安全下载器（strict 模式）
config.yaml       默认配置
config.local.yaml 个人配置覆盖（不入 git）
```

**添加新平台提取器：** 在 `extractors/` 下新建文件 → 继承 `BaseExtractor` → 实现 `extract()` 和 `supports()` → 加 `@register` 装饰器。

**开发者：**

```bash
pip install -r requirements.txt pytest pytest-mock
python -m pytest tests/ -v    # 运行测试（无需网络）
```

**合理限制：** 本项目不保证能下载所有视频。已删除、私密、地区限制、需要登录验证或有验证码的视频可能无法下载。

---

MIT License
