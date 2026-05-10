#!/usr/bin/env python3
"""
MCP stdio server for video-to-subtitle-summary-skill

This server exposes the video-to-subtitle-summary-skill as an MCP tool.
It can extract subtitles and generate AI summaries from videos on various platforms
or local video/audio files.

Usage:
  python3 mcp_server.py
  
The server will start and listen on stdin/stdout for MCP messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

# ── 导入原有 skill 的代码 ──────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

# Import the main video processing functions from the existing scripts
from scripts.video_to_summary import (
    load_env, get_env, detect_input, extract_youtube_id, fetch_video_info,
    _ytdlp_cmd, _build_ytdlp_cookie_args, _ytdlp_download, _ytdlp_download_audio,
    download_youtube_subtitles, _vtt_to_outputs, extract_audio,
    transcribe_sherpa_onnx, transcribe_volcengine, run, check_dep
)

# ── 常量 ──────────────────────────────────────────────────────────────

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
DEFAULT_OUTPUT_BASE = Path("/tmp/video_analysis")

# ── 主要处理函数 ──────────────────────────────────────────────────────

def process_video_to_subtitle_summary(input_path: str, output_dir: str = None) -> dict:
    """处理视频转字幕和总结的主函数"""
    # 加载环境变量
    env_map = load_env()
    asr_backend = get_env("ASR_BACKEND", "sherpa-onnx", env_map)
    tikhub_token = get_env("TIKHUB_TOKEN", env_map=env_map)

    # 判断输入类型
    mode, platform = detect_input(input_path)

    # 依赖检查
    missing: list[str] = []
    if mode == "url" and platform in ("bilibili", "youtube"):
        if not check_dep("yt-dlp"):
            missing.append("yt-dlp (pip install yt-dlp)")
    if mode == "url" and platform in ("douyin", "xiaohongshu", "bilibili"):
        if not tikhub_token:
            missing.append("TIKHUB_TOKEN (在 .env 中配置)")
    if mode == "local_video":
        if not check_dep("ffmpeg"):
            missing.append("ffmpeg (apt/brew install ffmpeg)")
    if asr_backend == "sherpa-onnx":
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            missing.append("sherpa-onnx (pip install sherpa-onnx)")
    elif asr_backend == "volcengine":
        if not get_env("BYTEDANCE_VC_TOKEN", env_map=env_map):
            missing.append("BYTEDANCE_VC_TOKEN")
        if not get_env("BYTEDANCE_VC_APPID", env_map=env_map):
            missing.append("BYTEDANCE_VC_APPID")
    
    if missing:
        raise RuntimeError(f"缺少依赖: {', '.join(missing)}")

    # 初始化
    video_info: dict = {}
    video_path: Path | None = None
    audio_path: Path | None = None
    subtitle_from_youtube = False

    if mode == "url":
        # 步骤 1: 获取视频信息
        if platform == "youtube":
            video_id = extract_youtube_id(input_path)
            video_info = {"id": video_id, "title": "", "author": "", "platform": "YouTube"}
        elif platform == "unknown":
            video_info = {"id": "unknown", "title": "", "author": "", "platform": "未知"}
        else:
            if not tikhub_token:
                raise RuntimeError("需要 TIKHUB_TOKEN 来获取视频信息")
            try:
                video_info = fetch_video_info(input_path, platform, tikhub_token)
            except Exception as exc:
                video_info = {"id": "unknown", "title": "", "author": "", "platform": platform}
        vid = video_info.get("id", "unknown")
        output_dir_path = Path(output_dir) if output_dir else DEFAULT_OUTPUT_BASE / vid
        output_dir_path.mkdir(parents=True, exist_ok=True)

        # 步骤 2: 下载 / 抓字幕
        if platform == "youtube":
            sub_result = download_youtube_subtitles(input_path, output_dir_path)
            if sub_result:
                subtitle_from_youtube = True
            else:
                audio_path = output_dir_path / "audio.mp3"
                _ytdlp_download_audio(input_path, audio_path)
        elif platform == "douyin":
            video_path = output_dir_path / "video.mp4"
            video_url = video_info.get("video_url")
            if video_url:
                try:
                    # Download using urllib
                    req = urllib.request.Request(video_url, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                    })
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        video_path.write_bytes(resp.read())
                except Exception:
                    _ytdlp_download(input_path, video_path)
            else:
                _ytdlp_download(input_path, video_path)
        elif platform == "xiaohongshu":
            video_path = output_dir_path / "video.mp4"
            video_url = video_info.get("video_url")
            if video_url:
                try:
                    req = urllib.request.Request(video_url, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                    })
                    with urllib.request.urlopen(req, timeout=120) as resp:
                        video_path.write_bytes(resp.read())
                except Exception:
                    _ytdlp_download(input_path, video_path)
            else:
                _ytdlp_download(input_path, video_path)
        elif platform == "bilibili":
            video_path = output_dir_path / "video.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            run(_ytdlp_cmd(input_path, str(video_path)), timeout=600)
        else:
            try:
                video_path = output_dir_path / "video.mp4"
                run(_ytdlp_cmd(input_path, str(video_path)), timeout=600)
            except RuntimeError:
                raise RuntimeError("无法下载该 URL")

        # 步骤 3: 提取音频
        if not subtitle_from_youtube and audio_path is None and video_path and video_path.exists():
            audio_path = output_dir_path / "audio.mp3"
            extract_audio(video_path, audio_path)
    else:
        # 本地文件
        local_path = Path(input_path).expanduser().resolve()
        vid = local_path.stem
        output_dir_path = Path(output_dir) if output_dir else DEFAULT_OUTPUT_BASE / vid
        output_dir_path.mkdir(parents=True, exist_ok=True)
        video_info = {"id": vid, "title": local_path.stem, "author": "", "platform": "本地文件"}
        if mode == "local_video":
            video_path = output_dir_path / local_path.name
            if video_path.resolve() != local_path.resolve():
                shutil.copy2(local_path, video_path)
            audio_path = output_dir_path / "audio.mp3"
            extract_audio(video_path, audio_path)
        else:
            audio_path = output_dir_path / local_path.name
            if audio_path.resolve() != local_path.resolve():
                shutil.copy2(local_path, audio_path)

    # 步骤 4: ASR
    if not subtitle_from_youtube:
        if asr_backend == "sherpa-onnx":
            result = transcribe_sherpa_onnx(audio_path, output_dir_path, env_map)
        elif asr_backend == "volcengine":
            result = transcribe_volcengine(audio_path, output_dir_path, env_map)
        else:
            raise RuntimeError(f"不支持的 ASR_BACKEND: {asr_backend}")
    else:
        result = {"text": "YouTube 字幕已提取"}

    # 生成最终结果
    srt_path = output_dir_path / "subtitle.srt"
    text_path = output_dir_path / "text.txt"
    if not text_path.exists():
        raise RuntimeError("未生成字幕文本")
    text_content = text_path.read_text(encoding="utf-8").strip()
    title = video_info.get("title", "")
    author = video_info.get("author", "")
    plat = video_info.get("platform", "")

    return {
        "video_info": video_info,
        "text_content": text_content,
        "output_dir": str(output_dir_path),
        "srt_path": str(srt_path) if srt_path.exists() else None,
        "text_path": str(text_path),
        "video_path": str(video_path) if video_path and video_path.exists() else None,
        "audio_path": str(audio_path) if audio_path and audio_path.exists() else None,
    }

# ── MCP 服务器实现 ──────────────────────────────────────────────────

app = Server("video-to-subtitle-summary-skill")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="video_to_subtitle_summary",
            description="Extract subtitles and generate AI summaries from videos on various platforms or local video/audio files. Supports Douyin, Xiaohongshu, Bilibili, YouTube, and local files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Video URL or local file path. Supported platforms: douyin.com, xiaohongshu.com, bilibili.com, youtube.com, or local video/audio files (.mp4, .mp3, .wav, etc.)"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional output directory. Default: /tmp/video_analysis/<video_id>"
                    }
                },
                "required": ["input"]
            },
        ),
    ]

@app.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    if name != "video_to_subtitle_summary":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments.get("input"):
        return [types.TextContent(
            type="text",
            text="Error: input parameter is required"
        )]

    try:
        input_path = arguments["input"]
        output_dir = arguments.get("output_dir")

        result = process_video_to_subtitle_summary(input_path, output_dir)

        # Format the response
        text_content = result["text_content"]
        video_info = result["video_info"]

        response = f"""## 视频分析结果

### 视频信息
| 平台 | {video_info.get('platform', 'N/A')} |
| 标题 | {video_info.get('title', 'N/A')} |
| 作者 | {video_info.get('author', 'N/A')} |
| 输出目录 | {result['output_dir']} |

### 字幕文本 (前500字)
{text_content[:500]}{'…' if len(text_content) > 500 else ''}

### 生成文件
"""
        if result['video_path']:
            response += f"- 视频: {result['video_path']}\n"
        if result['audio_path']:
            response += f"- 音频: {result['audio_path']}\n"
        if result['srt_path']:
            response += f"- SRT字幕: {result['srt_path']}\n"
        response += f"- 纯文本: {result['text_path']}\n"
        response += f"\n结果已保存至: {result['output_dir']}/result.json"

        return [types.TextContent(
            type="text",
            text=response
        )]

    except Exception as e:
        return [types.TextContent(
            type="text",
            text=f"Error processing video: {str(e)}"
        )]

# ── 主函数 ────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())