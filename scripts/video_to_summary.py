#!/usr/bin/env python3 -u
"""
video_to_summary.py — 一键视频转字幕 + AI 总结

用法:
  python3 video_to_summary.py <URL或文件路径> [--output-dir /tmp/video_analysis]

支持:
  - 抖音/TikTok (douyin.com / tiktok.com)
  - 小红书 (xiaohongshu.com / xhslink.com)
  - B站 (bilibili.com / b23.tv)
  - YouTube (youtube.com / youtu.be)
  - 本地视频/音频文件 (.mp4/.mp3/.wav/.m4a/.flac/.avi/.mkv/.mov)

依赖:
  - ffmpeg          : 系统包 (apt/brew install ffmpeg)
  - yt-dlp           : pip install yt-dlp  (B站/YouTube 下载)
  - sherpa-onnx      : pip install sherpa-onnx  (离线 ASR，默认后端)
  - TikHub Token     : 环境变量 TIKHUB_TOKEN (抖音/小红书/B站)

ASR 后端:
  sherpa-onnx (默认) — 离线，~15s 加载，10x+ 实时，中英粤三语
  volcengine         — 云端，需 BYTEDANCE_VC_TOKEN + BYTEDANCE_VC_APPID
"""

from __future__ import annotations

import argparse
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
from typing import Sequence

# ── 常量 ──────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SKILL_DIR / ".env"
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
DEFAULT_OUTPUT_BASE = Path("/tmp/video_analysis")
YOUTUBE_LANGUAGES = ("zh-Hans", "zh-Hant", "zh", "en")

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
    """返回 (mode, platform)"""
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
        # 注意：不加 minimal=true，否则 play_addr.url_list 为空
        api_url = f"https://api.tikhub.io/api/v1/hybrid/video_data?url={encoded}"
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        d = data.get("data", {})
        # 优先用 download_addr（无水印），回退到 play_addr
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

def download_bilibili(url: str, output_dir: Path) -> Path:
    video_path = output_dir / "video.mp4"
    run(["yt-dlp", "-o", str(video_path), url], timeout=600)
    return video_path

def _ytdlp_download(url: str, video_path: Path) -> None:
    """通用 yt-dlp 下载兜底，支持抖音/小红书等 200+ 平台"""
    video_path.parent.mkdir(parents=True, exist_ok=True)
    run(["yt-dlp", "--ignore-config", "-o", str(video_path), url], timeout=600)
    if not video_path.exists():
        raise RuntimeError(f"yt-dlp 下载失败: {url}")
    print(f"  ✓ yt-dlp 下载完成: {video_path}", flush=True)

def _build_ytdlp_cookie_args() -> list:
    """构建 yt-dlp Cookie 参数，支持环境变量和 Cookie 文件"""
    args = []
    # 方式1: 环境变量 YTDLP_COOKIES 直接传 Cookie 字符串
    cookies_str = os.environ.get("YTDLP_COOKIES", "")
    if cookies_str:
        args += ["--cookies", cookies_str]
    # 方式2: 环境变量 YTDLP_COOKIE_FILE 传 Cookie 文件路径
    cookie_file = os.environ.get("YTDLP_COOKIE_FILE", "")
    if cookie_file and Path(cookie_file).exists():
        args += ["--cookies", cookie_file]
    # 方式3: skill 目录下的 cookies.txt 文件（自动检测）
    default_cookie_file = SKILL_DIR / "cookies.txt"
    if default_cookie_file.exists():
        args += ["--cookies", str(default_cookie_file)]
    return args

def _ytdlp_download_audio(url: str, audio_path: Path) -> None:
    """下载音频（带 Cookie 支持），失败时打印友好提示"""
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_args = _build_ytdlp_cookie_args()
    cmd = ["yt-dlp", "--ignore-config"] + cookie_args + [
        "-x", "--audio-format", "mp3",
        "-o", str(audio_path.with_suffix("")), url]
    try:
        run(cmd, timeout=300)
    except RuntimeError as e:
        # 检测是否是 Cookie 相关错误
        err_str = str(e)
        if "Sign in" in err_str or "cookie" in err_str.lower() or "confirm" in err_str.lower():
            log_hint = (
                "\n  ⚠ YouTube 需要登录验证（Cookie）才能下载。"
                "\n  请任选以下方式之一配置 Cookie："
                "\n"
                "\n  方式1（推荐）: 在 skill 目录下放置 cookies.txt 文件"
                "\n    → 从浏览器导出 YouTube Cookie（Netscape 格式），保存为："
                f"\n      {SKILL_DIR}/cookies.txt"
                "\n"
                "\n  方式2: 设置环境变量 YTDLP_COOKIE_FILE"
                "\n    → export YTDLP_COOKIE_FILE=/path/to/cookies.txt"
                "\n"
                "\n  方式3: 设置环境变量 YTDLP_COOKIES（直接传 Cookie 字符串）"
                "\n    → export YTDLP_COOKIES=\"key1=val1; key2=val2; ...\""
                "\n"
                "\n  导出教程: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"
            )
            print(log_hint, flush=True)
            raise RuntimeError(f"yt-dlp 下载失败（需要 Cookie 验证）\n{err_str}") from e
        raise
    if not audio_path.exists():
        candidates = list(audio_path.parent.glob("audio.*"))
        if candidates:
            audio_path = candidates[0]
        else:
            raise RuntimeError(f"yt-dlp 下载失败: 未找到输出文件")

def download_youtube_subtitles(url: str, output_dir: Path) -> dict | None:
    output_stem = output_dir / "subtitle"
    cookie_args = _build_ytdlp_cookie_args()
    try:
        run(["yt-dlp", "--ignore-config"] + cookie_args + [
             "--skip-download",
             "--write-subs", "--write-auto-subs", "--sub-format", "vtt",
             "--sub-langs", ",".join(YOUTUBE_LANGUAGES),
             "-o", str(output_stem), url], timeout=120)
    except RuntimeError:
        return None
    vtt_files = sorted(output_dir.glob("subtitle*.vtt"))
    if not vtt_files:
        return None
    # 转换 VTT → SRT + text
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
    print(f"  ✓ 音频提取完成: {audio_path.name} ({audio_path.stat().st_size // 1024} KB)", flush=True)

# ── 步骤 4: ASR 转写 ──────────────────────────────────────────────────

def transcribe_sherpa_onnx(audio_path: Path, output_dir: Path, env_map: dict) -> dict:
    """sherpa-onnx 离线转写（默认后端），输出 SRT/text/result.json"""
    script = SKILL_DIR / "scripts" / "transcribe_sherpa_onnx.py"
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
    """火山引擎云端转写"""
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

# ── 主流程 ────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    # 日志配置
    _log_dir = Path("/tmp/video_analysis")
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = _log_dir / f"video_to_summary_{time.strftime('%Y%m%d_%H%M%S')}.log"
    _logger = logging.getLogger("video_to_summary")
    _logger.setLevel(logging.DEBUG)
    _logger.handlers.clear()
    _h_term = logging.StreamHandler(sys.stdout)
    _h_term.setLevel(logging.INFO)
    _h_term.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h_term)
    _h_file = logging.FileHandler(_log_file, encoding="utf-8")
    _h_file.setLevel(logging.DEBUG)
    _h_file.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(_h_file)

    parser = argparse.ArgumentParser(
        description="一键视频转字幕 + AI 总结",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 video_to_summary.py \"https://v.douyin.com/xxx\"\n  python3 video_to_summary.py \"https://www.bilibili.com/video/BVxxx\"\n  python3 video_to_summary.py /path/to/video.mp4\n  python3 video_to_summary.py /path/to/audio.mp3\n")
    parser.add_argument("input", help="视频URL或本地文件路径")
    parser.add_argument("--output-dir", default=None, help="输出目录 (默认: /tmp/video_analysis/<id>)")
    args = parser.parse_args(argv)

    _logger.info(f"日志文件: {_log_file}")

    # 加载环境变量
    env_map = load_env()
    asr_backend = get_env("ASR_BACKEND", "sherpa-onnx", env_map)
    tikhub_token = get_env("TIKHUB_TOKEN", env_map=env_map)

    # 判断输入类型
    mode, platform = detect_input(args.input)
    print(f"[1/5] 输入类型: {mode}, 平台: {platform}", flush=True)

    # 依赖检查
    print("[2/5] 检查依赖...", flush=True)
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
        print("ERROR: 缺少依赖:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1
    print(f"  ✓ 依赖就绪 (ASR_BACKEND={asr_backend})", flush=True)

    # 初始化
    video_info: dict = {}
    video_path: Path | None = None
    audio_path: Path | None = None
    subtitle_from_youtube = False

    if mode == "url":
        # 步骤 1: 获取视频信息
        print(f"[3/5] 获取视频信息 ({platform})...", flush=True)
        if platform == "youtube":
            video_id = extract_youtube_id(args.input)
            video_info = {"id": video_id, "title": "", "author": "", "platform": "YouTube"}
        elif platform == "unknown":
            video_info = {"id": "unknown", "title": "", "author": "", "platform": "未知"}
        else:
            if not tikhub_token:
                print("ERROR: 需要 TIKHUB_TOKEN 来获取视频信息", file=sys.stderr)
                return 1
            try:
                video_info = fetch_video_info(args.input, platform, tikhub_token)
            except Exception as exc:
                print(f"WARNING: 获取视频信息失败: {exc}", flush=True)
                video_info = {"id": "unknown", "title": "", "author": "", "platform": platform}
        vid = video_info.get("id", "unknown")
        output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_BASE / vid
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"  标题: {video_info.get('title', 'N/A')}", flush=True)
        print(f"  作者: {video_info.get('author', 'N/A')}", flush=True)

        # 步骤 2: 下载 / 抓字幕
        print(f"[4/5] 下载视频/字幕...", flush=True)
        if platform == "youtube":
            sub_result = download_youtube_subtitles(args.input, output_dir)
            if sub_result:
                subtitle_from_youtube = True
                print("  ✓ YouTube 字幕抓取成功", flush=True)
            else:
                print("  ⚠ 无可用字幕，回退到 ASR 转写", flush=True)
                audio_path = output_dir / "audio.mp3"
                _ytdlp_download_audio(args.input, audio_path)
        elif platform == "douyin":
            video_path = output_dir / "video.mp4"
            video_url = video_info.get("video_url")
            if video_url:
                try:
                    download_file(video_url, video_path)
                    print(f"  ✓ TikHub 下载完成: {video_path}", flush=True)
                except Exception as e:
                    print(f"  ⚠ TikHub 下载失败: {e}，回退到 yt-dlp...", flush=True)
                    _ytdlp_download(args.input, video_path)
            else:
                print(f"  ⚠ TikHub 未返回下载地址，使用 yt-dlp 下载...", flush=True)
                _ytdlp_download(args.input, video_path)
        elif platform == "xiaohongshu":
            video_path = output_dir / "video.mp4"
            video_url = video_info.get("video_url")
            if video_url:
                try:
                    download_file(video_url, video_path)
                    print(f"  ✓ TikHub 下载完成: {video_path}", flush=True)
                except Exception as e:
                    print(f"  ⚠ TikHub 下载失败: {e}，回退到 yt-dlp...", flush=True)
                    _ytdlp_download(args.input, video_path)
            else:
                print(f"  ⚠ TikHub 未返回下载地址，使用 yt-dlp 下载...", flush=True)
                _ytdlp_download(args.input, video_path)
        elif platform == "bilibili":
            video_path = download_bilibili(args.input, output_dir)
            print(f"  ✓ 下载完成: {video_path}", flush=True)
        else:
            try:
                video_path = output_dir / "video.mp4"
                run(["yt-dlp", "-o", str(video_path), args.input], timeout=600)
            except RuntimeError:
                print("ERROR: 无法下载该 URL", file=sys.stderr)
                return 1

        # 步骤 3: 提取音频
        if not subtitle_from_youtube and audio_path is None and video_path and video_path.exists():
            print("  提取音频...", flush=True)
            audio_path = output_dir / "audio.mp3"
            extract_audio(video_path, audio_path)
    else:
        # 本地文件
        local_path = Path(args.input).expanduser().resolve()
        vid = local_path.stem
        output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_BASE / vid
        output_dir.mkdir(parents=True, exist_ok=True)
        video_info = {"id": vid, "title": local_path.stem, "author": "", "platform": "本地文件"}
        if mode == "local_video":
            video_path = output_dir / local_path.name
            if video_path.resolve() != local_path.resolve():
                shutil.copy2(local_path, video_path)
            audio_path = output_dir / "audio.mp3"
            print(f"[3/5] 提取音频...", flush=True)
            extract_audio(video_path, audio_path)
        else:
            audio_path = output_dir / local_path.name
            if audio_path.resolve() != local_path.resolve():
                shutil.copy2(local_path, audio_path)

    # 步骤 4: ASR
    if not subtitle_from_youtube:
        print(f"[5/5] ASR 转写 ({asr_backend})...", flush=True)
        if asr_backend == "sherpa-onnx":
            result = transcribe_sherpa_onnx(audio_path, output_dir, env_map)
        elif asr_backend == "volcengine":
            result = transcribe_volcengine(audio_path, output_dir, env_map)
        else:
            print(f"ERROR: 不支持的 ASR_BACKEND: {asr_backend}", file=sys.stderr)
            return 1
        n_segs = len(result.get("segments", [])) if isinstance(result, dict) else "?"
        print(f"  ✓ 转写完成: {n_segs} 段", flush=True)

    # 输出结果
    srt_path = output_dir / "subtitle.srt"
    text_path = output_dir / "text.txt"
    if not text_path.exists():
        print("ERROR: 未生成字幕文本", file=sys.stderr)
        return 1
    text_content = text_path.read_text(encoding="utf-8").strip()
    title = video_info.get("title", "")
    author = video_info.get("author", "")
    plat = video_info.get("platform", "")

    print("\n" + "=" * 60, flush=True)
    print("## 视频分析结果", flush=True)
    print(f"\n### 视频信息", flush=True)
    print(f"| 平台 | {plat} |", flush=True)
    print(f"| 标题 | {title or 'N/A'} |", flush=True)
    print(f"| 作者 | {author or 'N/A'} |", flush=True)
    print(f"| 输出目录 | {output_dir} |", flush=True)
    print(f"\n### 字幕文本 (前500字)", flush=True)
    print(text_content[:500] + ("…" if len(text_content) > 500 else ""), flush=True)
    print(f"\n### 生成文件", flush=True)
    if video_path and video_path.exists(): print(f"- 视频: {video_path}", flush=True)
    if audio_path and audio_path.exists(): print(f"- 音频: {audio_path}", flush=True)
    if srt_path.exists(): print(f"- SRT字幕: {srt_path}", flush=True)
    print(f"- 纯文本: {text_path}", flush=True)
    print("=" * 60, flush=True)

    output = {
        "video_info": video_info, "text_content": text_content,
        "output_dir": str(output_dir), "srt_path": str(srt_path) if srt_path.exists() else None,
        "text_path": str(text_path),
        "video_path": str(video_path) if video_path and video_path.exists() else None,
        "audio_path": str(audio_path) if audio_path and audio_path.exists() else None,
    }
    (output_dir / "result.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存至: {output_dir / 'result.json'}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
