---
name: video-to-subtitle-summary-skill
description: "Use when user provides a short video platform URL (Douyin, Xiaohongshu, Bilibili, YouTube, etc.) or a local video/audio file path and wants to extract subtitles and generate AI summary. Triggers on URLs like v.douyin.com, xhslink.com, xiaohongshu.com, bilibili.com, b23.tv, youtube.com, youtu.be, share links, or local file paths ending in .mp4/.mp3/.wav etc."
---

# 视频转字幕与 AI 总结

MCP 服务器暴露两个异步工具，避免长时间处理导致客户端超时。

## MCP 工具

### submit_video_task

提交一个视频转字幕任务，立即返回 task_id。

**参数：**
- `input`（必填）— 视频 URL 或本地文件路径
- `output_dir`（可选）— 输出目录，默认 `/tmp/video_analysis/<video_id>`

**返回：**
```
✅ 任务已提交

- task_id: abc123def456
- input: https://v.douyin.com/xxx

请使用 query_video_task 查询进度和结果。
```

**支持平台：** douyin.com, tiktok.com, xiaohongshu.com, xhslink.com, bilibili.com, b23.tv, youtube.com, youtu.be 以及 yt-dlp 支持的 200+ 平台。

**支持格式：** .mp4 .mov .avi .mkv .webm .flv .wmv .mp3 .wav .m4a .flac .ogg .aac .wma

### query_video_task

查询任务状态和结果。

**参数：**
- `task_id`（必填）— submit_video_task 返回的任务 ID

**返回状态：**
- **pending** — 等待处理
- **processing** — 处理中（含当前阶段和进度百分比）
- **completed** — 已完成（字幕文本和输出目录直接返回，无需读文件）
- **failed** — 失败（含错误信息）
- **expired** — 已过期（默认 1 小时 TTL，需重新提交）

**completed 返回示例：**
```
## 任务 abc123def456

| 状态 | ✅ 已完成 |
| 阶段 | completed |
| 进度 | 100% |

### 视频信息
| 平台 | B站 |
| 标题 | 视频标题 |
| 作者 | UP主 |

### 字幕文本
```
这里是完整的字幕文本...
```

### 输出文件
- 输出目录: `/tmp/video_analysis/BVxxx`
- SRT 字幕: `/tmp/video_analysis/BVxxx/subtitle.srt`
- 纯文本: `/tmp/video_analysis/BVxxx/text.txt`
```

## 典型调用流程

```
submit_video_task(input="...") → task_id
query_video_task(task_id) → processing 30% (downloading)
query_video_task(task_id) → processing 70% (transcribing)
query_video_task(task_id) → completed (含完整字幕文本和输出目录)
```

## 进度阶段

| 阶段 | 说明 |
|------|------|
| `validating` | 检查依赖 |
| `downloading_model` | 下载 ASR 模型（首次运行，~234MB） |
| `fetching_info` | 获取视频信息 |
| `downloading` | 下载视频/音频 |
| `extracting_audio` | 提取音频 |
| `transcribing` | ASR 转写 |
| `finalizing` | 生成输出文件 |

---

# 一键脚本模式

```bash
python3 scripts/video_to_summary.py <URL或文件路径>
```

## 依赖

```bash
pip install sherpa-onnx numpy yt-dlp
sudo apt install ffmpeg   # Ubuntu/Debian
brew install ffmpeg       # macOS
```

## 环境变量（在 `.env` 中配置）

```bash
ASR_BACKEND=sherpa-onnx
TIKHUB_TOKEN=xxx           # TikHub API Token（抖音/小红书/B站）
YTDLP_COOKIE_FILE=xxx      # YouTube Cookie 文件路径
YTDLP_COOKIES=xxx          # YouTube Cookie 字符串
YTDLP_WORKERS=4            # yt-dlp 并发线程数
MODEL_CACHE_DIR=xxx         # 模型缓存目录（默认 ~/.cache/video-to-subtitle-summary）
BYTEDANCE_VC_TOKEN=xxx     # 火山引擎（可选）
BYTEDANCE_VC_APPID=xxx     # 火山引擎（可选）
```

## ASR 后端

### sherpa-onnx（默认）

- Paraformer 三语（普通话 + 粤语 + 英语），int8 量化 (234MB)
- 模型加载 ~15 秒，转写 10x+ 实时（RTF ≈ 0.08）
- 离线运行，无需 API Key

### volcengine（可选）

- 云端转写，秒级返回
- 需 `BYTEDANCE_VC_TOKEN` + `BYTEDANCE_VC_APPID`
