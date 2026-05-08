# video-to-subtitle-summary

A Claude Code Skill that automatically converts video platform videos or local video/audio files into subtitle text and generates AI summaries.

**Core Flow:**
- **Online video:** Provide a video link → Auto-download video or fetch native subtitles → Generate subtitles → AI summary
- **Local file:** Provide a local video/audio path → Extract audio (if needed) → ASR transcription → Generate subtitles → AI summary

The default ASR backend is local **sherpa-onnx** (Paraformer trilingual model, Chinese + Cantonese + English, int8 quantized), with optional support for Volcengine VC.

[中文文档](./README.md)

## Supported Platforms

**Explicitly supported (with dedicated parsing):**
- Douyin/TikTok (`douyin.com` / `tiktok.com`)
- Xiaohongshu (`xiaohongshu.com` / `xhslink.com`)
- Bilibili (`bilibili.com` / `b23.tv`)
- YouTube (`youtube.com` / `youtu.be`)

**Generic support (yt-dlp compatible, auto fallback):**
- Weibo, Zhihu, Kuaishou, Xigua Video, and **200+ platforms**
- Any video URL that yt-dlp can download will automatically fall back to: download → extract audio → ASR transcription

## Demo

Give it a video link or a local file path, and it automatically outputs:

```markdown
## Video Analysis Result

### Video Info
| Field | Value |
|-------|-------|
| Platform | Bilibili |
| Title | 说一说起迪max4的使用体验 |
| Author | 3D学习小屋屋 |

### AI Generated Title
起帝max4 3D打印机深度体验

### AI Summary
The video shares a detailed review of the Qidi Max 4 3D printer...

### Key Points
1. Cooling solution is the key advantage: built-in machine air conditioning
2. Large prints without splicing: full-bed single prints
3. Reliable multi-color unit: anti-jam and anti-leak design
```

## Prerequisites

### Required Dependencies

```bash
# 1. sherpa-onnx (offline ASR engine)
pip install sherpa-onnx

# 2. numpy (sherpa-onnx dependency)
pip install numpy

# 3. ffmpeg (audio/video processing)
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
```

### Optional Dependencies

```bash
# yt-dlp (Bilibili / YouTube / 200+ platform downloads)
pip install yt-dlp
```

### TikHub Token (Douyin / Xiaohongshu / Bilibili)

Sign up at https://tikhub.io/ — 100 free requests/day, paid from $0.001/request.

## Quick Start

### 1. Install Python Dependencies

```bash
pip install sherpa-onnx numpy yt-dlp
```

### 2. Install FFmpeg

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 3. Configure Environment Variables

```bash
cp .env.example .env
# Edit .env and fill in your TikHub Token
```

### 4. Run

```bash
# Online video
python3 scripts/video_to_summary.py "https://www.bilibili.com/video/BVxxx"
python3 scripts/video_to_summary.py "https://v.douyin.com/xxx"

# Local file
python3 scripts/video_to_summary.py /path/to/video.mp4
python3 scripts/video_to_summary.py /path/to/audio.mp3
```

## Model

### Trilingual Model (default, auto-download)

- **Languages:** Mandarin + Cantonese + English
- **Format:** int8 quantized, 234MB
- **First run:** Automatically downloads from GitHub Releases
- **RTF:** ≈ 0.08 (12x realtime)

### Chinese Model (alternative)

- **Language:** Mandarin only
- **Format:** int8 quantized, 214MB
- **RTF:** ≈ 0.09

## ASR Backend Comparison

| Backend | Model Load | Speed | Languages | Dependency |
|---------|-----------|-------|-----------|------------|
| **sherpa-onnx** (default) | ~15s | **10x+ realtime** | Chinese/Cantonese/English | `pip install sherpa-onnx` |
| volcengine | Network | Seconds | Chinese | API Key |

## Logs

Runtime logs are cached to `/tmp/video_analysis/`:
- `video_to_summary_<timestamp>.log` — main script log
- `transcribe_<timestamp>.log` — transcription script log

## Project Structure

```text
video-to-subtitle-summary/
├── README.md
├── README_en.md
├── SKILL.md                      # Skill definition
├── .env                          # Environment variables
├── .gitignore
├── scripts/
│   ├── video_to_summary.py       # Main entry script
│   ├── transcribe_sherpa_onnx.py # sherpa-onnx transcription script
│   └── download_youtube_subtitles.py
├── sherpa-onnx-paraformer-trilingual-zh-cantonese-en/  # Trilingual model (auto-download)
│   ├── model.int8.onnx           # int8 quantized model (234MB)
│   └── tokens.txt
└── docs/
    └── tikhub-setup.md
```

## Pricing

| Service | Cost |
|---------|------|
| TikHub API | 100 free requests/day, paid from $0.001/request |
| sherpa-onnx | Free, offline |
| yt-dlp | Free |
| Volcengine VC | Pay-per-use (volcengine backend only) |

## License

[MIT](./LICENSE)
