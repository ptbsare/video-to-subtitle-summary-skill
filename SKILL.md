---
name: video-to-subtitle-summary
description: Use when user provides a short video platform URL (Douyin, Xiaohongshu, Bilibili, YouTube, etc.) or a local video/audio file path and wants to extract subtitles and generate AI summary. Triggers on URLs like v.douyin.com, xhslink.com, xiaohongshu.com, bilibili.com, b23.tv, youtube.com, youtu.be, share links, or local file paths ending in .mp4/.mp3/.wav etc.
---

# 视频转字幕与 AI 总结

## 一键运行

```bash
python3 "$HOME/.hermes/skills/video-to-subtitle-summary-skill/scripts/video_to_summary.py" <URL或文件路径>
```

脚本自动完成：依赖检查 → 平台识别 → 获取信息 → 下载 → 提取音频 → ASR 转写 → 输出字幕。

### 示例

```bash
# 在线视频
python3 .../video_to_summary.py "https://v.douyin.com/xxx"
python3 .../video_to_summary.py "https://www.bilibili.com/video/BVxxx"
python3 .../video_to_summary.py "https://www.youtube.com/watch?v=xxx"
python3 .../video_to_summary.py "https://www.xiaohongshu.com/explore/xxx"

# 本地文件
python3 .../video_to_summary.py /path/to/video.mp4
python3 .../video_to_summary.py /path/to/audio.mp3
```

### 参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `input` | URL 或本地文件路径 | 必填 |
| `--output-dir` | 输出目录 | `/tmp/video_analysis/<id>` |

### 输出

- `subtitle.srt` — SRT 字幕
- `text.txt` — 纯文本
- `result.json` — 完整结果 (含 text, video_info, segments, 文件路径)

## 支持平台

| 平台 | URL 特征 | 下载方式 | 字幕来源 |
|------|----------|----------|----------|
| 抖音/TikTok | `douyin.com`, `tiktok.com` | TikHub API | ASR |
| 小红书 | `xiaohongshu.com`, `xhslink.com` | TikHub API | ASR |
| B站 | `bilibili.com`, `b23.tv` | yt-dlp | ASR |
| YouTube | `youtube.com`, `youtu.be` | yt-dlp 抓字幕优先 | 字幕 → ASR 回退 |
| 本地视频 | `.mp4`, `.mov`, `.avi`, `.mkv` 等 | 直接读取 | ASR |
| 本地音频 | `.mp3`, `.wav`, `.m4a`, `.flac` 等 | 直接读取 | ASR |

## 依赖安装

### 必需

```bash
# sherpa-onnx（离线 ASR 引擎）
pip install sherpa-onnx

# numpy（sherpa-onnx 依赖）
pip install numpy

# ffmpeg（音视频处理）
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
```

### 可选

```bash
# yt-dlp（B站/YouTube 下载）
pip install yt-dlp
```

### TikHub Token（抖音/小红书/B站需要）

在 `.env` 文件中配置：
```
TIKHUB_TOKEN=your_token_here
```

申请地址：https://tikhub.io/

## 环境变量

从 skill 目录下的 `.env` 读取：

```bash
ASR_BACKEND=sherpa-onnx              # ASR 后端: sherpa-onnx (默认) | volcengine
TIKHUB_TOKEN=xxx                     # TikHub API Token (抖音/小红书/B站)
BYTEDANCE_VC_TOKEN=xxx               # 火山引擎 Token (volcengine 后端)
BYTEDANCE_VC_APPID=xxx               # 火山引擎 AppID (volcengine 后端)
```

## ASR 后端

### sherpa-onnx（默认）

- **模型**：Paraformer 三语（普通话 + 粤语 + 英语），int8 量化
- **模型加载**：~15 秒
- **转写速度**：10x+ 实时（RTF ≈ 0.08）
- **依赖**：`pip install sherpa-onnx`
- **离线运行**，无需 API Key

```bash
# 单独使用转写脚本
python3 "$HOME/.hermes/skills/video-to-subtitle-summary-skill/scripts/transcribe_sherpa_onnx.py" \
  <音频或视频文件> [--output-dir /tmp/out]
```

### volcengine（可选）

- **依赖**：`BYTEDANCE_VC_TOKEN` + `BYTEDANCE_VC_APPID`
- **转写速度**：秒级（云端）
- 开通：https://www.volcengine.com/

## AI 总结

脚本运行后，读取 `result.json` 中的 `text` 字段，交给 AI 生成总结：

```
以下是一个视频的分析素材，请基于这些信息生成总结：

原视频标题：{video_info.title}
来源平台：{video_info.platform}
作者：{video_info.author}

语音识别文本：
{text}

请输出：
1. AI生成标题：简洁概括，不超过30字
2. AI摘要：提炼主要观点和关键信息，200-300字
3. 核心要点：3-5条结构化要点
```

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| `Missing dependency: sherpa-onnx` | `pip install sherpa-onnx` |
| `Missing dependency: numpy` | `pip install numpy` |
| `Missing dependency: ffmpeg` | `apt install ffmpeg` / `brew install ffmpeg` |
| `Missing dependency: yt-dlp` | `pip install yt-dlp` |
| `TIKHUB_TOKEN 缺失` | 在 `.env` 中填入 TikHub Token |
| YouTube 无字幕 | 自动回退到 yt-dlp 下载音频 + ASR |
| TikHub API 403 | 脚本已加 User-Agent，如仍失败请检查 Token |
| 模型加载失败 | 检查 `sherpa-onnx-paraformer-trilingual-zh-cantonese-en/model.int8.onnx` 是否存在 |
