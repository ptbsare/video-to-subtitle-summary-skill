# video_to_summary.py — 已知陷阱与修复记录

## 陷阱 1: TikHub API 返回 403

**现象**: `urllib.request.urlopen` 调用 TikHub API 返回 `HTTP Error 403: Forbidden`，但同一 Token 用 `curl` 正常。

**根因**: `urllib.request` 默认 `User-Agent: Python-urllib/3.14`，被 TikHub 的 Cloudflare WAF 拦截。

**修复**: 所有 `urllib.request.Request` 调用必须携带浏览器 UA：
```python
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
```

## 陷阱 2: TikHub `minimal=true` 导致下载地址为空

**现象**: 抖音视频 `play_addr.url_list` 返回空列表，`video_url` 为 `None`，抛出 `ValueError: unknown url type: 'None'`。

**根因**: TikHub 的 `minimal=true` 参数会精简响应，去掉 `play_addr` 等字段。

**修复**: 不要使用 `minimal=true`。完整响应包含 `download_addr`（无水印）和 `play_addr`（有水印）两个下载地址，优先使用 `download_addr`。

## 陷阱 3: ffmpeg 进度输出阻塞管道

**现象**: ffmpeg 提取音频时进程卡住，不产生输出也不退出。

**根因**: `-progress pipe:1` 将进度写到 stdout，但 `capture_output=False` 时 Python 不读取 stdout 管道，管道缓冲区满后 ffmpeg 阻塞。

**修复**: 使用 `capture_output=True` 静默捕获。

## 陷阱 4: Python stdout 缓冲（后台模式）

**现象**: `background=true` 模式下脚本长时间无输出，看起来像卡住了。

**根因**: Python 在 non-interactive 模式下 stdout 全缓冲。

**修复**: shebang 改为 `#!/usr/bin/env python3 -u`（强制无缓冲）。

## 陷阱 5: faster-whisper 在慢速 CPU 上极慢

**现象**: Xeon D-1581 @ 1.8GHz 上 small 模型加载需 140 秒，转写速度仅 0.2x 实时。

**根因**: CPU 单核性能弱，ctranslate2 推理慢。

**修复**: 切换 sherpa-onnx Paraformer int8 — 模型加载 ~15s，转写 10x+ 实时（RTF ≈ 0.08）。

## 陷阱 6: sherpa-onnx 模型文件缺失或解压不完整

**现象**: `RuntimeError: Model file not found` 或 `Protobuf parsing failed`。

**修复**: 脚本已内置自动下载逻辑。首次运行时自动从 GitHub Releases 下载：
```
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-trilingual-zh-cantonese-en.tar.bz2
```
解压后只保留 `model.int8.onnx` (234MB) + `tokens.txt`。确保 tar 解压完成后再运行脚本。

## 陷阱 7: YouTube "Sign in to confirm you're not a bot"

**现象**: yt-dlp 下载 YouTube 视频时报 `ERROR: Sign in to confirm you're not a bot`。

**根因**: YouTube 检测到非浏览器请求，要求 Cookie 验证。

**修复**: 配置 Cookie 支持三种方式（优先级从高到低）：
1. **（推荐）** 在 skill 目录下放置 `cookies.txt` 文件（Netscape 格式），脚本自动检测
2. 环境变量 `YTDLP_COOKIE_FILE=/path/to/cookies.txt`
3. 环境变量 `YTDLP_COOKIES="key1=val1; key2=val2; ..."`

Cookie 导出教程：https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp

脚本会在检测到 Cookie 相关错误时自动打印配置指引。`cookies.txt` 已加入 `.gitignore`。

## 陷阱 8: B站会员画质限制

**现象**: yt-dlp 下载 B站视频时提示 1080P 高码率格式需要会员。

**表现**: yt-dlp 自动降级到 720P，不影响使用。

## 依赖清单

| 包 | 用途 | 安装命令 |
|---|---|---|
| `sherpa-onnx` | 离线 ASR | `pip install sherpa-onnx` |
| `numpy` | 数组处理 | `pip install numpy` |
| `ffmpeg` | 音视频处理 | `apt install ffmpeg` / `brew install ffmpeg` |
| `yt-dlp` | 视频下载 | `pip install yt-dlp` |

每个脚本在入口处检查依赖，缺失时打印安装命令后 `sys.exit(1)`。
