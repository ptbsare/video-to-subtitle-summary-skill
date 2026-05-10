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

# ── 常量 ──────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
ENV_FILE = SKILL_DIR / ".env"
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
DEFAULT_OUTPUT_BASE = Path("/tmp/video_analysis")

# ── .env 加载 ─────────────────────────────────────────────────────────

def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                env[key] = val
                os.environ.setdefault(key, val)
    return env

def get_env(key: str, default: str | None = None, env_map: dict | None = None) -> str | None:
    env_map = env_map or {}
    return env_map.get(key) or os.getenv(key) or default

# ── 工具函数 ──────────────────────────────────────────────────────────

def run(cmd: list[str], check: bool = True, capture: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=check, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"命令超时 (> {timeout}s): {' '.join(cmd)}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()[:500] if exc.stderr else ""
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{stderr}") from exc
    except FileNotFoundError:
        raise RuntimeError(f"命令未找到: {cmd[0]}")

def check_dep(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def url_encode(s: str) -> str:
    return urllib.parse.quote(s, safe="")

def detect_input(s: str) -> tuple[str, str]:
    s = s.strip()
    if s.startswith(("http://", "https://")):
        if re.search(r"(douyin\.com|tiktok\.com)", s): return "url", "douyin"
        if re.search(r"(xiaohongshu\.com|xhslink\.com)", s): return "url", "xiaohongshu"
        if re.search(r"(bilibili\.com|b23\.tv)", s): return "url", "bilibili"
        if re.search(r"(youtube\.com|youtu\.be)", s): return "url", "youtube"
        return "url", "unknown"
    p = Path(s).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {s}")
    ext = p.suffix.lower()
    if ext in VIDEO_EXTS: return "local_video", "local"
    if ext in AUDIO_EXTS: return "local_audio", "local"
    raise ValueError(f"不支持的文件格式: {ext}")

def extract_youtube_id(url: str) -> str:
    for pat in [r"(?:v=|/)([0-9A-Za-z_-]{11})(?:[?&]|$)", r"youtu\.be/([0-9A-Za-z_-]{11})"]:
        m = re.search(pat, url)
        if m: return m.group(1)
    return "yt_video"

# ── 步骤 1: 获取视频信息 (TikHub) ────────────────────────────────────

def fetch_video_info(url: str, platform: str, token: str) -> dict:
    encoded = url_encode(url)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if platform == "douyin":
        api_url = f"https://api.tikhub.io/api/v1/hybrid/video_data?url={encoded}"
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        d = data.get("data", {})
        video_url = None
        download_addr = d.get("video", {}).get("download_addr", {}).get("url_list", [])
        if download_addr:
            video_url = download_addr[0]
        if not video_url:
            play_addr = d.get("video", {}).get("play_addr", {}).get("url_list", [])
            if play_addr:
                video_url = play_addr[0]
        return {"id": d.get("aweme_id", ""), "title": d.get("desc", ""),
                "author": d.get("author", {}).get("nickname", ""),
                "video_url": video_url,
                "platform": "抖音"}
    if platform == "xiaohongshu":
        api_url = f"https://api.tikhub.io/api/v1/xiaohongshu/web/get_note_info_v7?share_text={encoded}"
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        note = data.get("data", [{}])[0].get("note_list", [{}])[0]
        user = data.get("data", [{}])[0].get("user", {})
        vk = note.get("video", {}).get("consumer", {}).get("origin_video_key", "")
        return {"id": note.get("note_id", ""), "title": note.get("title", ""),
                "author": user.get("nickname", ""),
                "video_url": f"https://sns-video-bd.xhscdn.com/{vk}" if vk else "",
                "platform": "小红书"}
    if platform == "bilibili":
        api_url = f"https://api.tikhub.io/api/v1/bilibili/web/fetch_one_video_v3?url={encoded}"
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        d = data.get("data", {})
        return {"id": d.get("bvid", ""), "title": d.get("title", ""),
                "author": d.get("owner", {}).get("name", ""),
                "duration": d.get("duration", 0), "desc": d.get("desc", ""),
                "platform": "B站"}
    return {}

# ── 步骤 2: 下载视频/音频 ─────────────────────────────────────────────

def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())

def _build_ytdlp_cookie_args() -> list:
    args = []
    cookies_str = os.environ.get("YTDLP_COOKIES", "")
    if cookies_str:
        args += ["--cookies", cookies_str]
    cookie_file = os.environ.get("YTDLP_COOKIE_FILE", "")
    if cookie_file and Path(cookie_file).exists():
        args += ["--cookies", cookie_file]
    default_cookie_file = SKILL_DIR / "cookies.txt"
    if default_cookie_file.exists():
        args += ["--cookies", str(default_cookie_file)]
    return args

def _ytdlp_cmd(url: str, output: str, extra_args: list = None) -> list:
    cmd = ["yt-dlp", "--ignore-config"] + _build_ytdlp_cookie_args()
    if extra_args:
        cmd += extra_args
    cmd += ["-o", output, url]
    return cmd

def _ytdlp_download(url: str, video_path: Path) -> None:
    video_path.parent.mkdir(parents=True, exist_ok=True)
    run(_ytdlp_cmd(url, str(video_path)), timeout=600)
    if not video_path.exists():
        raise RuntimeError(f"yt-dlp 下载失败: {url}")

def _ytdlp_download_audio(url: str, audio_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = _ytdlp_cmd(url, str(audio_path.with_suffix("")),
                      extra_args=["-x", "--audio-format", "mp3"])
    run(cmd, timeout=300)
    if not audio_path.exists():
        candidates = list(audio_path.parent.glob("audio.*"))
        if candidates:
            audio_path = candidates[0]
        else:
            raise RuntimeError(f"yt-dlp 下载失败: 未找到输出文件")

def download_youtube_subtitles(url: str, output_dir: Path) -> dict | None:
    output_stem = output_dir / "subtitle"
    try:
        run(_ytdlp_cmd(url, str(output_stem), extra_args=[
             "--skip-download",
             "--write-subs", "--write-auto-subs", "--sub-format", "vtt",
             "--sub-langs", ",".join(("zh-Hans", "zh-Hant", "zh", "en")),
        ]), timeout=120)
    except RuntimeError:
        return None
    vtt_files = sorted(output_dir.glob("subtitle*.vtt"))
    if not vtt_files:
        return None
    srt_path = output_dir / "subtitle.srt"
    text_path = output_dir / "text.txt"
    vtt_text = vtt_files[0].read_text(encoding="utf-8")
    return _vtt_to_outputs(vtt_text, srt_path, text_path)

def _vtt_to_outputs(vtt_content: str, srt_path: Path, text_path: Path) -> dict:
    import html, re as _re
    TAG_RE = _re.compile(r"<[^>]+>")
    TIMING_RE = _re.compile(r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})")
    cues = []
    lines = vtt_content.splitlines()
    i = 0
    while i < len(lines):
        m = TIMING_RE.match(lines[i].strip())
        if not m:
            i += 1; continue
        start = m.group("start").replace(".", ",")
        end = m.group("end").replace(".", ",")
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            line = lines[i].strip()
            if not line.startswith(("NOTE", "STYLE", "REGION")):
                text_lines.append(line)
            i += 1
        text = TAG_RE.sub("", " ".join(text_lines))
        text = html.unescape(" ".join(text.split()))
        if text:
            cues.append((start, end, text))
    srt_content = "".join(f"{idx}\n{s} --> {e}\t{t}\n\n" for idx, (s, e, t) in enumerate(cues, 1))
    text_content = " ".join(t for _, _, t in cues)
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    srt_path.write_text(srt_content, encoding="utf-8")
    text_path.write_text(text_content + "\n", encoding="utf-8")
    return {"srt_path": str(srt_path), "text_path": str(text_path)}

# ── 步骤 3: 提取音频 ──────────────────────────────────────────────────

def extract_audio(video_path: Path, audio_path: Path) -> None:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True, text=True, timeout=15)
        info = json.loads(probe.stdout)
        duration = float(info.get("format", {}).get("duration", 0))
    except Exception:
        duration = 0
    timeout = max(60, min(int(duration * 2), 3600)) if duration > 0 else 600
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-q:a", "0", "-map", "a", str(audio_path)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg 提取音频超时 (> {timeout}s)")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace")[:500] if exc.stderr else ""
        raise RuntimeError(f"ffmpeg 提取音频失败:\n{stderr}")

# ── 步骤 4: ASR 转写 ──────────────────────────────────────────────────

def transcribe_sherpa_onnx(audio_path: Path, output_dir: Path, env_map: dict) -> dict:
    script = SKILL_DIR / "scripts" / "transcribe_sherpa_onnx.py"
    if not script.exists():
        script = SKILL_DIR / "transcribe_sherpa_onnx.py"
    if not script.exists():
        raise RuntimeError("sherpa-onnx 转写脚本不存在")
    
    cmd = [
        sys.executable, str(script), str(audio_path),
        "--output-dir", str(output_dir),
        "--model-dir", str(SKILL_DIR / "sherpa-onnx-paraformer-trilingual-zh-cantonese-en"),
        "--model-fp", "model.int8.onnx", "--chunk-seconds", "30",
    ]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(min(os.cpu_count() or 4, 16))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()[:500] if exc.stderr else ""
        raise RuntimeError(f"sherpa-onnx 转写失败:\n{stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("sherpa-onnx 转写超时 (>600s)")
    result_json = output_dir / "result.json"
    if result_json.exists():
        return json.loads(result_json.read_text(encoding="utf-8"))
    return {}

def transcribe_volcengine(audio_path: Path, output_dir: Path, env_map: dict) -> dict:
    token = get_env("BYTEDANCE_VC_TOKEN", env_map=env_map)
    appid = get_env("BYTEDANCE_VC_APPID", env_map=env_map)
    if not token or not appid:
        raise RuntimeError("火山引擎后端需要 BYTEDANCE_VC_TOKEN 和 BYTEDANCE_VC_APPID")
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    req = urllib.request.Request(
        f"https://openspeech.bytedance.com/api/v1/vc/submit?appid={appid}&language=zh-CN&words_per_line=20&max_lines=2",
        data=audio_data,
        headers={"Content-Type": "audio/mpeg", "Authorization": f"Bearer;{token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        submit_data = json.loads(resp.read())
    task_id = submit_data.get("id")
    if not task_id:
        raise RuntimeError(f"火山引擎提交失败: {submit_data}")
    import time as _time
    for _ in range(60):
        _time.sleep(5)
        req2 = urllib.request.Request(
            f"https://openspeech.bytedance.com/api/v1/vc/query?appid={appid}&id={task_id}",
            headers={"Authorization": f"Bearer;{token}"})
        with urllib.request.urlopen(req2, timeout=30) as resp:
            query_data = json.loads(resp.read())
        if query_data.get("result"):
            break
    else:
        raise RuntimeError("火山引擎转写超时")
    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "subtitle.srt"
    text_path = output_dir / "text.txt"
    def ms_to_srt(ms):
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    utterances = query_data.get("result", [])
    srt_lines, text_parts = [], []
    for i, u in enumerate(utterances, 1):
        text = u.get("text", "").strip()
        if not text: continue
        srt_lines.append(f"{i}\n{ms_to_srt(u['start_time'])} --> {ms_to_srt(u['end_time'])}\n{text}\n")
        text_parts.append(text)
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    text_path.write_text(" ".join(text_parts) + "\n", encoding="utf-8")
    return {"srt_path": str(srt_path), "text_path": str(text_path),
            "segments": len(utterances), "text": " ".join(text_parts)}

# ── 主要处理函数 ──────────────────────────────────────────────────────

def process_video_to_subtitle_summary(input_path: str, output_dir: str = None) -> dict:
    env_map = load_env()
    asr_backend = get_env("ASR_BACKEND", "sherpa-onnx", env_map)
    tikhub_token = get_env("TIKHUB_TOKEN", env_map=env_map)

    mode, platform = detect_input(input_path)

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
            import sherpa_onnx
        except ImportError:
            missing.append("sherpa-onnx (pip install sherpa-onnx)")
    elif asr_backend == "volcengine":
        if not get_env("BYTEDANCE_VC_TOKEN", env_map=env_map):
            missing.append("BYTEDANCE_VC_TOKEN")
        if not get_env("BYTEDANCE_VC_APPID", env_map=env_map):
            missing.append("BYTEDANCE_VC_APPID")
    
    if missing:
        raise RuntimeError(f"缺少依赖: {', '.join(missing)}")

    video_info: dict = {}
    video_path: Path | None = None
    audio_path: Path | None = None
    subtitle_from_youtube = False

    if mode == "url":
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
                    download_file(video_url, video_path)
                except Exception:
                    _ytdlp_download(input_path, video_path)
            else:
                _ytdlp_download(input_path, video_path)
        elif platform == "xiaohongshu":
            video_path = output_dir_path / "video.mp4"
            video_url = video_info.get("video_url")
            if video_url:
                try:
                    download_file(video_url, video_path)
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

        if not subtitle_from_youtube and audio_path is None and video_path and video_path.exists():
            audio_path = output_dir_path / "audio.mp3"
            extract_audio(video_path, audio_path)
    else:
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

    if not subtitle_from_youtube:
        if asr_backend == "sherpa-onnx":
            result = transcribe_sherpa_onnx(audio_path, output_dir_path, env_map)
        elif asr_backend == "volcengine":
            result = transcribe_volcengine(audio_path, output_dir_path, env_map)
        else:
            raise RuntimeError(f"不支持的 ASR_BACKEND: {asr_backend}")
    else:
        result = {"text": "YouTube 字幕已提取"}

    srt_path = output_dir_path / "subtitle.srt"
    text_path = output_dir_path / "text.txt"
    if not text_path.exists():
        raise RuntimeError("未生成字幕文本")
    text_content = text_path.read_text(encoding="utf-8").strip()

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