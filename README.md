# Video Downloader — 全平台视频下载工具

> 支持 YouTube、B站、抖音、TikTok、Twitter、Instagram 等 1800+ 网站。
> 复制链接 → 粘贴 → 下载。就这么简单。

## 特性

- **全平台覆盖** — yt-dlp 支持 1800+ 网站，抖音有专用提取器双保险
- **Chrome 开着也能用** — Cookie 读取失败自动回退无 Cookie 模式，不会报错
- **浏览器指纹伪装** — `curl_cffi` 模拟 Chrome TLS 指纹，应对抖音等平台的反爬
- **双击即用** — `下载视频.bat` 双击打开，粘贴链接回车即可
- **高清无水印** — 自动选择最佳画质，抖音专用提取器优先获取无水印地址

## 快速开始

### 1. 安装依赖

```bash
# Python 3.10+
pip install -r requirements.txt

# 核心工具
pip install yt-dlp
winget install ffmpeg    # 或从 https://www.gyan.dev/ffmpeg/builds/ 手动下载
```

### 2. 环境检查

```bash
python main.py --check
```

三个都显示 `[OK]` 就绪。

### 3. 下载视频

**方式一：双击 `下载视频.bat`** → 粘贴链接 → 回车

**方式二：命令行**
```bash
python main.py                        # 交互模式
python main.py "视频链接"              # 一行命令
```

视频保存在 `videos/` 文件夹。

## 架构

```
URL → 平台检测
        │
    ┌───┴───┐
    │       │
  抖音    其他平台
    │       │
    ▼       ▼
 专用      yt-dlp
 提取器    下载
 (HTTPX)     │
    │       Chrome Cookie 锁定?
    │         ├─ 是 → 自动无 Cookie 重试
    ▼         └─ 否 → 正常下载
  HTTP
  直链下载
    │
    └────→ videos/
```

- **yt-dlp** — 主力下载引擎，覆盖 1800+ 网站
- **extractors/** — 专用提取器包，处理 yt-dlp 不稳定的平台（目前：抖音）
- **下载视频.bat** — 极简启动器，双击即用

## 配置

编辑 `config.yaml`（个人覆盖写 `config.local.yaml`）：

```yaml
downloader:
  output_dir: videos      # 下载目录
  format: bestvideo+bestaudio/best

browser:
  cookies_from_browser: chrome   # Cookie 来源: chrome / firefox / edge

impersonate:
  target: chrome-131      # 浏览器伪装（抖音需要），设为 "" 禁用
```

## 支持的平台

| 平台 | 下载方式 | 备注 |
|------|---------|------|
| YouTube | yt-dlp | 稳定 |
| Bilibili | yt-dlp | 稳定，高清需登录 |
| 抖音 | 专用提取器 → yt-dlp 回退 | yt-dlp 常失效，双保险 |
| TikTok | yt-dlp | 需伪装 + Cookie |
| Twitter/X | yt-dlp | 稳定 |
| Instagram | yt-dlp | 稳定 |
| 其他 1800+ | yt-dlp | 试试就知道 |

## 常见问题

**Q: 抖音下载失败？**
抖音的反爬最严格。尝试：
1. 在浏览器打开视频 → 播放 → 复制地址栏完整链接再试
2. 关掉 Chrome 后重试（让程序能读取 Cookie）
3. 用抖音APP分享 → 复制链接 → 粘贴到程序

**Q: Chrome Cookie 报错？**
程序会自动检测并回退到无 Cookie 模式，不需要手动操作。B站等需要登录的平台关一下 Chrome 就好。

**Q: B站下载只有 480P？**
需要在 Chrome 里登录 B 站账号，然后关掉 Chrome 运行下载。

## 开发

```bash
# 运行测试
python -m pytest tests/ -v

# 添加新平台提取器
# 1. 在 extractors/ 下新建 xxx.py
# 2. 继承 BaseExtractor，实现 extract() 和 supports()
# 3. 用 @register 装饰器注册
```

## 许可

MIT License

## 免责声明

本工具仅供个人学习使用。请遵守版权法，仅下载你有权限的内容。
