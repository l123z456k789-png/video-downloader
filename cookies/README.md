# Cookie 文件说明

此目录用于存放各平台的 Cookie 文件（Netscape HTTP Cookie 格式）。

**⚠️ Cookie 文件包含登录凭证，绝对不能提交到 git 或分享给他人。**

## 默认行为

程序默认从浏览器读取 Cookie（`--cookies-from-browser chrome`），无需手动管理 Cookie 文件。

## 手动使用 Cookie 文件

如需使用 Cookie 文件，修改 `config.local.yaml`:

```yaml
cookies:
  mode: file
  file: cookies/youtube.txt
```

支持的模式:
- `browser` — 从浏览器自动读取（默认，推荐）
- `file`   — 从指定文件读取
- `none`   — 不使用 Cookie

## 获取 Cookie 文件

### 方法 1: yt-dlp 导出

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies/youtube.txt
```

### 方法 2: 浏览器扩展

使用 "Get cookies.txt LOCALLY" 等浏览器扩展导出。

### 方法 3: yt-dlp 自动处理

不手动管理 Cookie。程序执行时 yt-dlp 自动从浏览器读取。
