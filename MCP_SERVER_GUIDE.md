# MCP Server Guide for video-to-subtitle-summary-skill

This skill now supports running as an MCP (Model Context Protocol) stdio server, allowing integration with any MCP-compatible client.

## Features

- **Preserves all original functionality** - All existing scripts continue to work as before
- **MCP stdio server** - Can be run as a standalone MCP server
- **uvx support** - Can be installed and run directly via `uvx github.com/ptbsare/video-to-subtitle-summary-skill`
- **Tool-based interface** - Exposes one tool: `video_to_subtitle_summary`

## Running the MCP Server

### Method 1: Direct Python execution

```bash
cd /path/to/video-to-subtitle-summary-skill
python3 mcp_server.py
```

The server will start and listen on stdin/stdout for MCP messages.

### Method 2: Using uvx (recommended)

First, ensure you have uv installed:

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then run:

```bash
uvx github.com/ptbsare/video-to-subtitle-summary-skill
```

### Method 3: Install as a package

```bash
cd /path/to/video-to-subtitle-summary-skill
python3 install_as_uvx.py

# Then run
video-to-subtitle-summary-skill
```

## MCP Tool Interface

### Tool: `video_to_subtitle_summary`

Extracts subtitles and generates AI summaries from videos on various platforms or local video/audio files.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `input` | string | Yes | Video URL or local file path. Supported: douyin.com, xiaohongshu.com, bilibili.com, youtube.com, or local video/audio files (.mp4, .mp3, .wav, etc.) |
| `output_dir` | string | No | Optional output directory. Default: `/tmp/video_analysis/<video_id>` |

#### Example Call

```json
{
  "name": "video_to_subtitle_summary",
  "arguments": {
    "input": "https://www.bilibili.com/video/BVxxx",
    "output_dir": "/tmp/my_analysis"
  }
}
```

#### Response Format

The tool returns formatted text with:
- Video information (platform, title, author)
- First 500 characters of the subtitle text
- List of generated files (video, audio, SRT, text)
- Path to the complete result.json file

## Supported Platforms

**Explicitly supported (with dedicated parsing):**
- Douyin/TikTok (`douyin.com` / `tiktok.com`)
- Xiaohongshu (`xiaohongshu.com` / `xhslink.com`)
- Bilibili (`bilibili.com` / `b23.tv`)
- YouTube (`youtube.com` / `youtu.be`)

**Generic support (yt-dlp compatible, auto fallback):**
- Weibo, Zhihu, Kuaishou, Xigua Video, and **200+ platforms**
- Any video URL that yt-dlp can download will automatically fall back to: download → extract audio → ASR transcription

## Dependencies

The tool will check for and require:
- `ffmpeg`: System package (apt/brew install ffmpeg)
- `yt-dlp`: pip install yt-dlp (for online video downloads)
- `sherpa-onnx`: pip install sherpa-onnx (offline ASR engine)
- `numpy`: pip install numpy (sherpa-onnx dependency)

## Environment Variables

Create a `.env` file in the skill directory or set these environment variables:

```bash
# ASR backend: sherpa-onnx (default, offline) | volcengine (cloud, requires API key)
ASR_BACKEND=sherpa-onnx

# TikHub API — for Douyin/Xiaohongshu/Bilibili video info (YouTube doesn't need)
TIKHUB_TOKEN=your_tikhub_token

# Volcengine VC — only when ASR_BACKEND=volcengine
BYTEDANCE_VC_TOKEN=your_bytedance_vc_token
BYTEDANCE_VC_APPID=your_bytedance_vc_appid

# YouTube Cookie (fix "Sign in to confirm you're not a bot")
YTDLP_COOKIE_FILE=/path/to/cookies.txt
# or place cookies.txt in the skill directory (auto-detected)
```

## Output Files

The tool generates the following files in the output directory:

- `subtitle.srt` — SRT subtitle file
- `text.txt` — Plain text transcription
- `result.json` — Complete result with metadata

## Example Output

```markdown
## 视频分析结果

### 视频信息
| 平台 | B站 |
| 标题 | 说一说起迪max4的使用体验 |
| 作者 | 3D学习小屋屋 |
| 输出目录 | /tmp/video_analysis/BVxxx |

### 字幕文本 (前500字)
本期视频博主详细分享了起帝max4 3D打印机的使用体验...

### 生成文件
- 视频: /tmp/video_analysis/BVxxx/video.mp4
- 音频: /tmp/video_analysis/BVxxx/audio.mp3
- SRT字幕: /tmp/video_analysis/BVxxx/subtitle.srt
- 纯文本: /tmp/video_analysis/BVxxx/text.txt

结果已保存至: /tmp/video_analysis/BVxxx/result.json
```

## File Structure

```
video-to-subtitle-summary-skill/
├── mcp_server.py              # MCP server implementation
├── run_mcp_server.py          # Entry point for uvx
├── pyproject.toml             # Package configuration for uvx
├── install_as_uvx.py          # Helper script to install as package
├── test_mcp_server.py         # Test script for MCP server
├── MCP_SERVER_GUIDE.md        # This guide
├── scripts/                   # Original skill scripts (unchanged)
│   ├── video_to_summary.py    # Main script
│   ├── transcribe_sherpa_onnx.py
│   └── download_youtube_subtitles.py
└── ...                        # Other original files
```

## Testing

Run the test script to verify the MCP server:

```bash
python3 test_mcp_server.py
```

## Troubleshooting

### "Missing dependencies" error

Install the required dependencies:

```bash
pip install sherpa-onnx numpy yt-dlp mcp
sudo apt install ffmpeg  # Ubuntu/Debian
brew install ffmpeg      # macOS
```

### "TIKHUB_TOKEN required" error

Set your TikHub token in `.env` or as an environment variable for Douyin/Xiaohongshu/Bilibili support.

### "YouTube cookie required" error

Configure YouTube cookies as described in the Environment Variables section.

## License

MIT
