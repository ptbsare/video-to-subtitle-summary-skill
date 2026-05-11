---
name: video-to-subtitle-summary-skill
description: Use when user provides a short video platform URL (Douyin, Xiaohongshu, Bilibili, YouTube, etc.) or a local video/audio file path and wants to extract subtitles and generate AI summary. Triggers on URLs like v.douyin.com, xhslink.com, xiaohongshu.com, bilibili.com, b23.tv, youtube.com, youtu.be, share links, or local file paths ending in .mp4/.mp3/.wav etc.

Also supports running as an MCP stdio server via: python3 mcp_server.py or uvx github.com/ptbsare/video-to-subtitle-summary-skill

## MCP 异步任务模式

MCP 服务器暴露两个工具（非原来的单一阻塞工具）：

### 1. `submit_video_task` — 提交任务，立即返回 task_id

```json
{
  "input": "https://v.douyin.com/xxx"
}
```

`output_dir` 可选，默认 `/tmp/video_analysis/<video_id>`。

返回示例：
```
✅ 任务已提交

- task_id: abc123def456
- input: https://v.douyin.com/xxx

请使用 query_video_task 查询进度和结果。
提示: 任务完成后字幕文本和输出目录会直接返回，无需读取文件。
```

### 2. `query_video_task` — 查询任务状态和结果

```json
{ "task_id": "abc123def456" }
```

返回状态：
- **pending** — 等待处理
- **processing** — 处理中（含当前阶段和进度百分比）
- **completed** — 已完成（字幕文本直接返回，无需读文件）
- **failed** — 失败（含错误信息）
- **expired** — 已过期（默认 1 小时 TTL，需重新提交）

### 进度阶段

处理过程中会更新以下阶段：
1. `validating` — 检查依赖
2. `fetching_info` — 获取视频信息
3. `downloading` — 下载视频/音频
4. `extracting_audio` — 提取音频
5. `transcribing` — ASR 转写
6. `finalizing` — 生成输出文件

### 典型调用流程

```
submit_video_task(input="...") → task_id
query_video_task(task_id) → processing 30% (downloading)
query_video_task(task_id) → processing 70% (transcribing)
query_video_task(task_id) → completed (含完整字幕文本)
```
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

### 日志

运行日志自动缓存到 `/tmp/video_analysis/` 目录。

## 支持平台

**明确支持（有专门解析逻辑）：** 抖音/TikTok · 小红书 · B站 · YouTube

**通用支持（yt-dlp 自动回退）：** 微博、知乎、快手、西瓜视频等 **200+ 平台**

## 依赖

脚本自动检测缺失依赖并提示安装命令。

```bash
# 必需
pip install sherpa-onnx numpy yt-dlp
sudo apt install ffmpeg   # Ubuntu/Debian
```

## 环境变量（在 `.env` 中配置）

```bash
ASR_BACKEND=sherpa-onnx    # ASR 后端: sherpa-onnx (默认) | volcengine
TIKHUB_TOKEN=xxx           # TikHub API Token（抖音/小红书/B站）

# YouTube Cookie（解决 "Sign in to confirm you're not a bot"）
YTDLP_COOKIE_FILE=xxx      # Cookie 文件路径（Netscape 格式）
# 或直接把 cookies.txt 放在 skill 根目录（自动检测，已加入 .gitignore）
```

### YouTube Cookie 配置

YouTube 经常需要登录验证才能下载，支持三种方式（优先级从高到低）：

1. **（推荐）** 在 skill 目录下放置 `cookies.txt` 文件（会自动检测）
2. 环境变量 `YTDLP_COOKIE_FILE=/path/to/cookies.txt`
3. 环境变量 `YTDLP_COOKIES="key1=val1; key2=val2; ..."`

Cookie 导出教程：<https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp>

> `cookies.txt` 已加入 `.gitignore`，不会提交到仓库。

## ASR 后端

### sherpa-onnx（默认）

- **模型**：Paraformer 三语（普通话 + 粤语 + 英语），int8 量化 (234MB)
- **首次运行**：自动从 GitHub Releases 下载模型
- **模型加载**：~15 秒，**转写速度**：10x+ 实时（RTF ≈ 0.08）
- **离线运行**，无需 API Key

```bash
# 单独使用转写脚本
python3 "$HOME/.hermes/skills/video-to-subtitle-summary-skill/scripts/transcribe_sherpa_onnx.py" \
  <音频或视频文件> [--output-dir /tmp/out]
```

### volcengine（可选）

- 云端转写，秒级返回
- 需 `BYTEDANCE_VC_TOKEN` + `BYTEDANCE_VC_APPID`

## AI 总结

脚本运行后，读取 `result.json` 中的 `text` 字段，交给 AI 生成总结：

```
以下是一个视频的分析素材：

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
| `缺少依赖: sherpa-onnx` | `pip install sherpa-onnx` |
| YouTube "Sign in to confirm" | 配置 Cookie（见上方说明） |
| TikHub API 403 | 检查 Token，脚本已加 User-Agent |
| 模型下载失败 | 手动下载：`wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-trilingual-zh-cantonese-en.tar.bz2` |

## 已知陷阱

详见 [references/pitfalls.md](references/pitfalls.md)，包含以下场景的详细分析与修复：
- TikHub API 403（urllib UA 问题）
- TikHub `minimal=true` 导致下载地址为空
- ffmpeg 进度输出阻塞管道
- Python stdout 缓冲导致后台无输出
- faster-whisper CPU 模式性能极低
- sherpa-onnx 模型自动下载与清理
- **YouTube Cookie 配置（"Sign in to confirm" 错误）**
- B站会员画质限制
