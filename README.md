# Video Downloader — 全平台视频下载工具

> 支持 YouTube、B站、抖音、TikTok、Twitter、Instagram 等 1800+ 网站。
> 复制链接 → 粘贴 → 下载。就这么简单。

## 目录

1. [这个项目是什么](#这个项目是什么)
2. [有什么特点](#有什么特点)
3. [和同类工具对比](#和同类工具对比)
4. [第一次安装（小白版）](#第一次安装小白版)
5. [怎么用](#怎么用)
6. [常见问题](#常见问题)
7. [配置说明](#配置说明)
8. [项目架构](#项目架构)
9. [开发指南](#开发指南)
10. [许可与免责](#许可与免责)

---

## 这个项目是什么

一个帮你从网上下载视频的工具。你负责复制视频链接，它负责下载。

**支持的网站包括但不限于：**

| 平台 | 能不能下 | 备注 |
|------|---------|------|
| 抖音 | ✅ | 专用提取器 + yt-dlp 双保险 |
| B站 | ✅ | 登录后可下 1080P |
| YouTube | ✅ | 需代理，稳定 |
| TikTok | ✅ | 需伪装 + Cookie |
| 小红书 | ✅ | |
| Twitter/X | ✅ | |
| Instagram | ✅ | |
| 微博 | ✅ | |
| 优酷、腾讯、爱奇艺 | ✅ | |
| 其他 1800+ 网站 | ✅ | 把链接丢进去试试 |

---

## 有什么特点

**优点：**

- **抖音稳** — 项目给抖音专门写了一套"浏览器渲染"方案。普通工具（纯 yt-dlp）遇到抖音经常报错，这个项目会自动切换策略，成功率高得多。
- **Chrome 开着也能用** — 大部分工具读 Chrome Cookie 时要求关掉 Chrome。这个项目会自动检测，如果 Chrome 锁了 Cookie 就自动切到无 Cookie 模式，不会报错卡住。
- **高清无水印** — 自动选最高画质，抖音优先获取无水印地址。
- **双击即用** — 不用记命令，双击 `下载视频.bat` 就行。
- **中文界面** — 从提示到错误信息全是中文，不会蹦英文。
- **开源免费** — MIT 协议，代码全公开，没有付费墙、没有广告。

**缺点：**

- **需要装环境** — 不是下载一个 exe 就能用，第一次要装 Python、yt-dlp、FFmpeg（约 10-15 分钟，下面有详细教程）。
- **抖音下载稍慢** — 因为要启动一个"隐形浏览器"渲染页面，比普通下载多花 10-15 秒。
- **黑窗口界面** — 没有漂亮的图形按钮，是命令行黑窗口。
- **依赖 Chrome** — 抖音下载需要电脑上装了 Chrome 浏览器。
- **不支持批量下载** — 一次只能下一个视频，不能粘贴一堆链接同时下。

---

## 和同类工具对比

| | 这个项目 | 纯 yt-dlp | 在线下载网站 |
|---|---|---|---|
| 能下抖音 | ✅ 双保险，稳 | ❌ 经常报错 | ⚠️ 看运气 |
| 隐私安全 | ✅ 全部本地运行 | ✅ 全部本地运行 | ❌ 你的链接被传到别人服务器 |
| 需要安装 | ⚠️ 第一次要装环境 | ⚠️ 要装环境 | ✅ 不用装 |
| 下载速度 | ✅ 满速 | ✅ 满速 | ❌ 限速 |
| 高清无水印 | ✅ | ✅ | ❌ 高清要付费 |
| 免费 | ✅ | ✅ | ⚠️ |

**一句话：如果你愿意花 15 分钟装一次环境，之后每次下载就是"双击 → 粘贴 → 回车"，比任何在线网站都快、都稳、都安全。**

---

## 第一次安装（小白版）

如果你完全没用过命令行，跟着下面一步步做就行。只需要做一次。

### 第 1 步：下载这个项目

点击本页面顶部绿色的 **<> Code** 按钮 → **Download ZIP** → 解压到桌面或任意位置。

### 第 2 步：安装 Python

1. 打开浏览器，输入：**https://www.python.org/downloads/**
2. 页面中间黄色大按钮 **Download Python 3.x.x**，点它下载
3. 双击下载的 `.exe` 文件
4. ⚠️ **最重要的一步**：安装窗口底部有一个 **Add Python to PATH** 的复选框，**一定要勾上！**
5. 点 **Install Now**，等进度条跑完

**验证：** 按键盘 `Win + R`，输入 `cmd` 回车，在黑色窗口输入 `python --version` 回车。出现 `Python 3.x.x` 就对了。

### 第 3 步：安装 yt-dlp

在黑色窗口（CMD）里输入：

```
pip install yt-dlp
```

回车。等几十秒出现 `Successfully installed` 就行。

验证：输入 `yt-dlp --version` 回车，出现版本号就对了。

### 第 4 步：安装 FFmpeg

在黑色窗口输入：

```
winget install ffmpeg
```

回车。等一会装好。

> 如果提示找不到 winget，去 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip`，解压后记住 `bin` 文件夹的位置。

验证：**关掉 CMD 重新打开**，输入 `ffmpeg -version` 回车，出现一大串版本信息就对了。

### 第 5 步：进入项目文件夹

1. 打开项目文件夹
2. 在文件夹**空白处**，按住 `Shift` 不放，点鼠标右键
3. 选 **在此处打开 PowerShell 窗口**

### 第 6 步：安装项目依赖

在 PowerShell 窗口输入：

```
pip install -r requirements.txt
```

回车。等几秒出现 `Successfully installed`。

### 第 7 步：环境检查

输入：

```
python main.py --check
```

三个都显示 `[OK]` 就一切就绪。如果有 `[FAIL]`，回头看前面是哪步没装好。

---

## 怎么用

### 日常使用（推荐）

1. 双击 `下载视频.bat`
2. 看到 "粘贴视频链接:" 时，把链接粘贴进去
3. 回车，等着

视频自动保存在 `videos/` 文件夹里。

### 命令行模式

```bash
python main.py                        # 交互模式，粘贴链接
python main.py "视频链接"              # 一行命令直接下载
python main.py --check                # 环境检查
```

### 各平台下载示例

```
# B站
python main.py "https://www.bilibili.com/video/BV1GJ411x7h7"

# 抖音（短链接也行）
python main.py "https://v.douyin.com/xxxxx"

# YouTube
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

# TikTok
python main.py "https://www.tiktok.com/@user/video/123456"
```

---

## 常见问题

### Q: 抖音下载失败怎么办？

抖音的反爬是全网最严的。试试这些：

1. **换链接格式** — 在抖音 APP 里点"分享" → "复制链接"，粘贴那个短链接（`v.douyin.com/...`）
2. **确认视频能看** — 在浏览器打开链接，确认视频能播放（有些视频被删了或者仅限 APP 观看）
3. **关掉 Chrome** — 如果用的是需要登录的抖音账号，关掉 Chrome 后重试，让程序能读取登录 Cookie

### Q: B站只能下 480P，怎么下 1080P？

B站的高清视频需要登录。确保：
1. 你的 Chrome 浏览器登录了 B站
2. **关掉 Chrome**（因为开着会锁 Cookie）
3. 再运行程序下载

### Q: Chrome Cookie 报错怎么办？

程序会自动处理。看到 `[WARN] Chrome Cookie 读取失败` 然后 `[INFO] 自动切换为无 Cookie 模式` —— 这是正常的，程序会自动重试。只有需要登录的网站（B站高清、会员视频等）才需要关 Chrome。

### Q: YouTube 下载失败？

YouTube 在国内被墙，需要科学上网。确保代理开着。

### Q: 日志文件会不会一直占硬盘？

不会。日志按月留存，超过 30 天自动删除。

### Q: 我的 Cookie 会不会被泄露？

不会。Cookie 默认从浏览器直接读取，不会生成文件到硬盘。即使使用 Cookie 文件模式，`cookies.txt` 也已被 `.gitignore` 排除，不会上传到 GitHub。

---

## 配置说明

项目配置在 `config.yaml` 文件中。用记事本打开就能改。

**基本配置（一般不用改）：**

```yaml
downloader:
  output_dir: videos        # 视频保存目录
  format: bestvideo+bestaudio/best   # 画质选择

browser:
  cookies_from_browser: chrome      # 从哪个浏览器读 Cookie
```

**抖音增强配置（已内置，一般不用动）：**

```yaml
impersonate:
  target: chrome-131        # 模拟 Chrome 浏览器指纹

platforms:
  douyin:
    user_agent: "Mozilla/5.0 ..."   # 模拟真实浏览器
    referer: "https://www.douyin.com/"
```

**个人配置覆盖：**

创建一个 `config.local.yaml` 文件，写你自己的配置。这个文件被 `.gitignore` 排除了，不会提交到 GitHub。

---

## 项目架构

```
用户粘贴链接
      │
      ▼
  平台检测 (platforms.py)
      │
   ┌──┴──┐
   │     │
 抖音   其他
   │     │
   ▼     ▼
专用    yt-dlp
提取器   下载
   │     │
   │      ├─ Chrome Cookie 锁定？ → 自动回退无 Cookie
   │      └─ 正常下载
   ▼
提取视频直链
   │
   ▼
HTTP 下载 → videos/
```

**核心模块：**

| 文件/目录 | 做什么 |
|-----------|--------|
| `main.py` | 入口，交互流程 |
| `downloader.py` | yt-dlp 调用 + Cookie 自动回退 + 混合下载 |
| `config.yaml` | 默认配置 |
| `platforms.py` | URL 平台检测 |
| `extractors/` | 专用提取器包（抖音等 yt-dlp 不稳定的平台） |
| `logger.py` | 日志记录 |
| `下载视频.bat` | 双击启动器 |

**抖音提取器工作流程：**

1. Playwright 启动系统 Chrome（headless 隐身模式）
2. 导航到抖音视频页面
3. 拦截页面的 `aweme/detail` API 请求
4. 从 API 响应中提取 `download_addr`（无水印 CDN 地址）
5. HTTPX 直接下载视频文件
6. 如果提取器失败 → 自动回退 yt-dlp

---

## 开发指南

```bash
# 运行测试
python -m pytest tests/ -v

# 添加新平台提取器
# 1. 在 extractors/ 下新建 xxx.py
# 2. 继承 BaseExtractor，实现 extract() 和 supports()
# 3. 用 @register 装饰器注册
# 4. 在 extractors/__init__.py 里 import 即可
```

**提取器模板：**

```python
from .base import BaseExtractor, ExtractResult, VideoInfo, register

@register
class MyExtractor(BaseExtractor):
    platform = "my_platform"

    def supports(self, url: str) -> bool:
        return "my_platform.com" in url

    def extract(self, url: str, cookies=None) -> ExtractResult:
        # 你的提取逻辑
        return ExtractResult(
            success=True,
            videos=[VideoInfo(url="https://cdn.example.com/video.mp4")]
        )
```

---

## 许可与免责

**许可：** MIT License

**免责声明：**

1. 本工具仅供个人学习使用。
2. 请遵守版权法，仅下载你有权限的内容。
3. 未经版权方授权，不得下载、传播或商用受版权保护的视频。
4. 使用者对下载行为承担全部法律责任。
