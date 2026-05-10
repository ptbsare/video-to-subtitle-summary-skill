#!/usr/bin/env python3 -u
"""
transcribe_sherpa_onnx.py — 用 sherpa-onnx 离线转写音频/视频文件

用法:
  python3 transcribe_sherpa_onnx.py <音频或视频文件> [--output-dir /tmp/out] [--model-dir ...]

依赖:
  - sherpa-onnx  : pip install sherpa-onnx
  - numpy        : pip install numpy
  - ffmpeg       : 系统包 (apt/brew install ffmpeg)，用于非 WAV 输入

模型:
  默认自动下载三语 Paraformer (zh + cantonese + en) int8 模型到 skill 目录
  也可通过 --model-dir 和 --model-fp 指定其他模型

输出:
  subtitle.srt  — SRT 字幕文件
  text.txt      — 纯文本
  result.json   — 完整结果

日志:
  运行日志缓存到 /tmp/video_analysis/transcribe_<timestamp>.log
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

# ── 常量 ──────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = SKILL_DIR / "sherpa-onnx-paraformer-trilingual-zh-cantonese-en"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-trilingual-zh-cantonese-en.tar.bz2"

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}

LOG_DIR = Path("/tmp/video_analysis")

# ── 日志配置 ──────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """配置日志：同时输出到终端和文件"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"transcribe_{time.strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # 终端输出（简洁）
    h_term = logging.StreamHandler(sys.stdout)
    h_term.setLevel(logging.INFO)
    h_term.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(h_term)

    # 文件输出（详细）
    h_file = logging.FileHandler(log_file, encoding="utf-8")
    h_file.setLevel(logging.DEBUG)
    h_file.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(h_file)

    logger.info(f"日志文件: {log_file}")
    return logger

log = setup_logging()

# ── 依赖检查 ──────────────────────────────────────────────────────────

def check_dependencies():
    """检查并提示安装缺失依赖"""
    missing = []
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        missing.append(("sherpa-onnx", "pip install sherpa-onnx"))
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append(("numpy", "pip install numpy"))
    if not shutil.which("ffmpeg"):
        missing.append(("ffmpeg", "apt install ffmpeg  /  brew install ffmpeg"))
    if missing:
        for name, cmd in missing:
            log.error(f"  缺少依赖: {name} → {cmd}")
        log.error("请安装缺失依赖后重试")
        sys.exit(1)

check_dependencies()

# ── 模型下载 ──────────────────────────────────────────────────────────

def download_model(model_dir: Path) -> None:
    """如果模型不存在，自动下载并解压"""
    model_file = model_dir / "model.int8.onnx"
    if model_file.exists():
        log.info(f"模型已存在: {model_file}")
        return

    log.info(f"模型不存在，开始下载...")
    log.info(f"URL: {MODEL_URL}")
    log.info(f"目标: {model_dir}")

    model_dir.mkdir(parents=True, exist_ok=True)
    archive = model_dir / "model.tar.bz2"

    # wget 下载，带进度显示
    log.info("下载中（约 1GB，请耐心等待）...")
    t0 = time.time()
    try:
        result = subprocess.run(
            ["wget", "-q", "--show-progress", "--progress=dot:giga",
             "-O", str(archive), MODEL_URL],
            check=True, capture_output=False, timeout=600)
    except FileNotFoundError:
        # 没有 wget，用 urllib
        log.info("wget 不可用，使用 urllib 下载...")
        import urllib.request
        def _progress_hook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0 and block_num % 50 == 0:
                pct = min(downloaded / total_size * 100, 100)
                log.info(f"  下载进度: {pct:.0f}% ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)")
        urllib.request.urlretrieve(MODEL_URL, str(archive), reporthook=_progress_hook)
    except subprocess.TimeoutExpired:
        log.error("下载超时（>600s），请检查网络后重试")
        sys.exit(1)

    elapsed = time.time() - t0
    log.info(f"下载完成 ({elapsed:.0f}s)，开始解压...")

    # 解压
    try:
        subprocess.run(
            ["tar", "xf", str(archive), "-C", str(model_dir)],
            check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError as e:
        log.error(f"解压失败: {e}")
        sys.exit(1)

    # 只保留 model.int8.onnx 和 tokens.txt，删除其他文件
    kept = {"model.int8.onnx", "tokens.txt"}
    for f in model_dir.iterdir():
        if f.is_file() and f.name not in kept:
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)

    # 删除压缩包
    archive.unlink(missing_ok=True)

    if model_file.exists():
        size_mb = model_file.stat().st_size // 1024 // 1024
        log.info(f"模型就绪: {model_file} ({size_mb}MB)")
    else:
        log.error("模型文件不存在，请检查下载是否完整")
        sys.exit(1)

# ── 工具函数 ──────────────────────────────────────────────────────────

def run_cmd(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"命令超时 (> {timeout}s): {' '.join(cmd)}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()[:500] if exc.stderr else ""
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{stderr}")
    except FileNotFoundError:
        raise RuntimeError(f"命令未找到: {cmd[0]}")


def get_audio_duration(path: Path) -> float:
    try:
        r = run_cmd(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)], timeout=15)
        info = json.loads(r.stdout)
        return float(info.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def extract_audio(video_path: Path, audio_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["ffmpeg", "-y", "-i", str(video_path),
             "-vn", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", str(audio_path)], timeout=600)
    log.info(f"音频提取完成: {audio_path.name} ({audio_path.stat().st_size // 1024} KB)")


def read_wave(path: str) -> tuple:
    with wave.open(str(path)) as f:
        if f.getnchannels() != 1:
            raise ValueError(f"期望单声道，实际 {f.getnchannels()} 声道")
        if f.getsampwidth() != 2:
            raise ValueError(f"期望 16-bit，实际 {f.getsampwidth() * 8}-bit")
        n = f.getnframes()
        raw = f.readframes(n)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples, f.getframerate()


def convert_to_wav_16k(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(["ffmpeg", "-y", "-i", str(input_path),
             "-vn", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", str(output_path)], timeout=300)


# ── sherpa-onnx 转写 ──────────────────────────────────────────────────

def load_recognizer(model_dir: str, model_fp: str = "model.int8.onnx", num_threads: int = 0, provider: str = "cpu"):
    import sherpa_onnx

    model_path = Path(model_dir) / model_fp
    tokens_path = Path(model_dir) / "tokens.txt"

    if not model_path.exists():
        model_path = Path(model_dir) / "model.onnx"
    if not model_path.exists():
        raise FileNotFoundError(f"模型文件不存在: {model_dir}/model.int8.onnx 或 model.onnx")
    if not tokens_path.exists():
        raise FileNotFoundError(f"tokens.txt 不存在: {tokens_path}")

    if num_threads <= 0:
        num_threads = min(os.cpu_count() or 4, 16)

    log.info(f"加载模型: {model_path.name} (threads={num_threads})")
    t0 = time.time()

    recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(model_path), tokens=str(tokens_path),
        num_threads=num_threads, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", debug=False, provider=provider)

    log.info(f"模型加载完成 ({time.time() - t0:.1f}s)")
    return recognizer


def transcribe_wav(recognizer, wav_path: str) -> list:
    import sherpa_onnx
    samples, sample_rate = read_wave(wav_path)
    duration = len(samples) / sample_rate
    s = recognizer.create_stream()
    s.accept_waveform(sample_rate, samples)
    recognizer.decode_stream(s)
    text = s.result.text.strip()
    return [{"text": text, "start": 0.0, "end": duration}] if text else []


def transcribe_long_audio(recognizer, wav_path: str, chunk_seconds: float = 30.0) -> list:
    import sherpa_onnx
    samples, sample_rate = read_wave(wav_path)
    total_duration = len(samples) / sample_rate
    chunk_samples = int(chunk_seconds * sample_rate)
    all_segments, offset = [], 0.0
    chunk_idx, total_chunks = 0, max(1, int(np.ceil(len(samples) / chunk_samples)))
    t_start = time.time()

    for start_sample in range(0, len(samples), chunk_samples):
        end_sample = min(start_sample + chunk_samples, len(samples))
        chunk = samples[start_sample:end_sample]
        chunk_dur = len(chunk) / sample_rate
        s = recognizer.create_stream()
        s.accept_waveform(sample_rate, chunk)
        recognizer.decode_stream(s)
        text = s.result.text.strip()
        if text:
            all_segments.append({"text": text, "start": round(offset, 3), "end": round(offset + chunk_dur, 3)})
        offset += chunk_dur
        chunk_idx += 1
        elapsed = time.time() - t_start
        pct = offset / total_duration * 100 if total_duration > 0 else 0
        rtf = elapsed / offset if offset > 0 else 0
        log.info(f"[{chunk_idx}/{total_chunks}] {pct:.0f}% | RTF={rtf:.2f} | {text[:50]}…")

    return all_segments


# ── 输出写入 ──────────────────────────────────────────────────────────

def write_srt(segments: list, path: Path) -> None:
    lines = []
    for i, seg in enumerate(segments, 1):
        s = _srt_time(seg["start"])
        e = _srt_time(seg["end"])
        lines.append(f"{i}\n{s} --> {e}\n{seg['text']}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_text(segments: list, path: Path) -> None:
    text = " ".join(seg["text"] for seg in segments)
    path.write_text(text + "\n", encoding="utf-8")


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── 主流程 ────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="sherpa-onnx 离线音频/视频转写",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n  python3 transcribe_sherpa_onnx.py audio.wav\n  python3 transcribe_sherpa_onnx.py video.mp4\n  python3 transcribe_sherpa_onnx.py audio.wav --model-dir /path/to/model\n")
    parser.add_argument("input", help="音频或视频文件路径")
    parser.add_argument("--output-dir", default=None, help="输出目录 (默认: 输入文件同目录)")
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR), help="模型目录 (默认: 自动下载)")
    parser.add_argument("--model-fp", default="model.int8.onnx", help="模型文件名 (默认: model.int8.onnx)")
    parser.add_argument("--num-threads", type=int, default=0, help="CPU 线程数 (默认: 自动)")
    parser.add_argument("--provider", default="cpu", choices=["cpu", "cuda"], help="推理后端")
    parser.add_argument("--chunk-seconds", type=float, default=30.0, help="长音频分段长度 (秒)")
    parser.add_argument("--no-auto-download", action="store_true", help="禁止自动下载模型")
    args = parser.parse_args(argv)

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        log.error(f"文件不存在: {input_path}")
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_path.parent / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # 模型准备（自动下载）
    model_dir = Path(args.model_dir)
    if not args.no_auto_download:
        download_model(model_dir)
    else:
        log.info(f"跳过自动下载，使用指定模型: {model_dir}")

    ext = input_path.suffix.lower()
    wav_path = output_dir / "audio_16k.wav"

    if ext in VIDEO_EXTS:
        log.info(f"[1/3] 提取音频 ({input_path.suffix})...")
        extract_audio(input_path, wav_path)
    elif ext in AUDIO_EXTS:
        if ext == ".wav":
            try:
                with wave.open(str(input_path)) as f:
                    if f.getframerate() == 16000 and f.getsampwidth() == 2 and f.getnchannels() == 1:
                        wav_path = input_path
                        log.info("[1/3] WAV 已符合要求 (16kHz 16bit mono)，跳过转换")
                    else:
                        log.info("[1/3] 转换音频为 16kHz WAV...")
                        convert_to_wav_16k(input_path, wav_path)
            except Exception:
                log.info("[1/3] 转换音频为 16kHz WAV...")
                convert_to_wav_16k(input_path, wav_path)
        else:
            log.info("[1/3] 转换音频为 16kHz WAV...")
            convert_to_wav_16k(input_path, wav_path)
    else:
        log.error(f"不支持的文件格式: {ext}")
        return 1

    log.info("[2/3] 加载模型...")
    try:
        recognizer = load_recognizer(str(model_dir), args.model_fp, args.num_threads, args.provider)
    except Exception as e:
        log.error(f"模型加载失败: {e}")
        return 1

    log.info("[3/3] 转写中...")
    duration = get_audio_duration(wav_path)
    t0 = time.time()
    if duration > args.chunk_seconds * 1.5:
        segments = transcribe_long_audio(recognizer, str(wav_path), args.chunk_seconds)
    else:
        segments = transcribe_wav(recognizer, str(wav_path))
    elapsed = time.time() - t0
    rtf = elapsed / duration if duration > 0 else 0

    srt_path = output_dir / "subtitle.srt"
    text_path = output_dir / "text.txt"
    result_path = output_dir / "result.json"
    write_srt(segments, srt_path)
    write_text(segments, text_path)

    full_text = " ".join(s["text"] for s in segments)
    result = {
        "input": str(input_path), "output_dir": str(output_dir),
        "duration": round(duration, 2), "elapsed": round(elapsed, 2),
        "rtf": round(rtf, 3), "num_segments": len(segments),
        "text": full_text, "segments": segments,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(f"\n{'=' * 60}")
    log.info(f"✓ 转写完成")
    log.info(f"  音频时长: {duration:.1f}s | 转写耗时: {elapsed:.1f}s | RTF: {rtf:.3f}")
    log.info(f"  分段数: {len(segments)} | 字符数: {len(full_text)}")
    log.info(f"  SRT: {srt_path}")
    log.info(f"  TXT: {text_path}")
    log.info(f"{'=' * 60}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
