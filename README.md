# 视频下载器

把网上的视频下载到电脑上。支持 B站、抖音、YouTube、TikTok 等几乎所有视频网站。

---

## 怎么用

**日常使用就三步：**

1. 双击 `下载视频.bat`
2. 粘贴视频链接
3. 回车

下载完的视频在 `videos` 文件夹里。

---

## 第一次安装

下面每一步都写了怎么做，跟着来就行。装过一次就不用再装了。

### 1. 下载这个项目

点本页面顶部绿色 **<> Code** 按钮 → **Download ZIP** → 解压到桌面。

### 2. 安装 Python

1. 打开 https://www.python.org/downloads/
2. 点黄色大按钮下载
3. 双击安装
4. ⚠️ 安装窗口底部 **Add Python to PATH** 必须勾上！不然后面全报错
5. 点 Install Now

检查装好没：按 `Win + R`，输入 `cmd` 回车，输入 `python --version` 回车。出现 Python 3.x.x 就对了。

### 3. 安装 yt-dlp

在刚才的黑色窗口输入：

```
pip install yt-dlp
```

回车。检查：`yt-dlp --version`

### 4. 安装 FFmpeg

黑色窗口输入：

```
winget install ffmpeg
```

> 如果报错"找不到 winget"，去 https://www.gyan.dev/ffmpeg/builds/ 下载 `ffmpeg-release-essentials.zip`，解压后把 `bin` 文件夹路径记下来，等下要用。

检查：**关掉黑色窗口重新打开**，输入 `ffmpeg -version`

### 5. 进入项目文件夹

打开解压出来的项目文件夹 → 在空白处按住 `Shift` 点右键 → **在此处打开 PowerShell 窗口**。

### 6. 安装依赖

```
pip install -r requirements.txt
```

### 7. 检查是否一切就绪

```
python main.py --check
```

三个都显示 `[OK]` 就行了。如果哪个显示 `[FAIL]`，往回看那一步是不是漏了。

---

## 常见问题

**抖音下不了？**

- 试试在抖音 APP 里点"分享" → "复制链接"，用那个短链接
- 在浏览器打开链接确认视频能放（有些视频已删除或仅限 APP）
- 还是不行的话关掉 Chrome 再试

**B站只能下 480P，怎么下高清？**

确保 Chrome 登录了 B站，然后**关掉 Chrome**再下载。因为 Chrome 开着的时候程序读不了你的登录状态。

**YouTube 下不了？**

需要开代理。

**Chrome Cookie 报错？**

不用管。程序会自动切换模式，不影响下载。只有需要登录的视频才需要关 Chrome。

**支持哪些网站？**

B站、抖音、YouTube、TikTok、小红书、微博、Twitter、Instagram、优酷、腾讯视频、爱奇艺……基本上你能想到的视频网站都支持。底层是 yt-dlp，覆盖 1800+ 个网站。

---

## 高级用法

```bash
python main.py "链接"    # 一行命令直接下载
python main.py --check   # 检查环境
```

### 改配置

用记事本打开 `config.yaml`，可以改：

```yaml
downloader:
  output_dir: videos       # 下载到哪个文件夹
  format: bestvideo+bestaudio/best  # 画质

browser:
  cookies_from_browser: chrome     # 从哪个浏览器读登录状态
```

不要直接改 `config.yaml`，复制一份叫 `config.local.yaml` 再改。这个文件不会被上传到 GitHub。

---

## 技术细节

给想看代码的人。

**整体思路：** yt-dlp 是主力下载引擎，覆盖绝大多数网站。对于 yt-dlp 不稳定的平台（抖音），项目内置了专用提取器。

**抖音下载流程：**

```
URL → Playwright 启动 Chrome (headless)
    → 拦截 aweme/detail API 响应
    → 提取 download_addr (无水印 CDN 地址)
    → 直接 HTTP 下载
    → 失败则回退 yt-dlp
```

**文件结构：**

```
main.py           入口，交互流程
downloader.py     yt-dlp 调用 + Cookie 自动回退 + 混合下载策略
platforms.py      URL 域名检测
extractors/       专用提取器（抖音等）
  base.py         基类 + 提取器注册表
  douyin.py       抖音提取器（Playwright + Chrome）
config.yaml       默认配置
config.local.yaml 个人配置覆盖（不上传 GitHub）
```

**添加新平台提取器：** 在 `extractors/` 下新建文件 → 继承 `BaseExtractor` → 实现 `extract()` 和 `supports()` → 加 `@register` 装饰器。

**运行测试：** `python -m pytest tests/ -v`

---

MIT License
