#!/usr/bin/env python3 -u
"""
transcribe_sherpa_onnx.py — 用 sherpa-onnx 离线转写音频/视频文件

用法:
  python3 transcribe_sherpa_onnx.py <音频或视频文件> [--output-dir /tmp/out] [--model-dir ...]

依赖:
  - sherpa-onnx  : pip install sherpa-onnx
  - numpy        : pip install numpy
  - ffmpeg       : 系统包 (apt/brew install ffmpeg)，用于非 WAV 输入

支持输入格式:
  音频: .wav .mp3 .m4a .flac .ogg .aac .wma
  视频: .mp4 .mov .avi .mkv .webm .flv .wmv (自动提取音频)

模型:
  默认使用 skill 目录下的三语 Paraformer 模型 (zh + cantonese + en)
  也可通过 --model-dir 和 --model-fp 指定其他模型

输出:
  subtitle.srt  — SRT 字幕文件
  text.txt      — 纯文本
  result.json   — 完整结果
"""

from __future__ import annotations

import argparse
import json
import os
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

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"}

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
    import shutil
    if not shutil.which("ffmpeg"):
        missing.append(("ffmpeg", "apt install ffmpeg  /  brew install ffmpeg"))
    if missing:
        print("ERROR: 缺少依赖:", file=sys.stderr)
        for name, install_cmd in missing:
            print(f"  - {name}: {install_cmd}", file=sys.stderr)
        sys.exit(1)

# 在导入时就检查
check_dependencies()

# ── 工具函数 ──────────────────────────────────────────────────────────

def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
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
        r = run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)], timeout=15)
        info = json.loads(r.stdout)
        return float(info.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def extract_audio(video_path: Path, audio_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-i", str(video_path),
         "-vn", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000", str(audio_path)], timeout=600)
    print(f"  ✓ 音频提取完成: {audio_path.name} ({audio_path.stat().st_size // 1024} KB)", flush=True)


def read_wave(path: str) -> tuple:
    with wave.open(str(path)) as f:
        assert f.getnchannels() == 1, f"期望单声道，实际 {f.getnchannels()} 声道"
        assert f.getsampwidth() == 2, f"期望 16-bit，实际 {f.getsampwidth() * 8}-bit"
        n = f.getnframes()
        raw = f.readframes(n)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples, f.getframerate()


def convert_to_wav_16k(input_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-i", str(input_path),
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
    print(f"  加载模型: {model_path.name} (threads={num_threads})", flush=True)
    t0 = time.time()
    recognizer = sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(model_path), tokens=str(tokens_path),
        num_threads=num_threads, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", debug=False, provider=provider)
    print(f"  模型加载完成 ({time.time() - t0:.1f}s)", flush=True)
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
        print(f"  [{chunk_idx}/{total_chunks}] {pct:.0f}% | RTF={rtf:.2f} | {text[:40]}…", flush=True)
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
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR), help="模型目录")
    parser.add_argument("--model-fp", default="model.int8.onnx", help="模型文件名 (默认: model.int8.onnx)")
    parser.add_argument("--num-threads", type=int, default=0, help="CPU 线程数 (默认: 自动)")
    parser.add_argument("--provider", default="cpu", choices=["cpu", "cuda"], help="推理后端")
    parser.add_argument("--chunk-seconds", type=float, default=30.0, help="长音频分段长度 (秒)")
    args = parser.parse_args(argv)

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"ERROR: 文件不存在: {input_path}", file=sys.stderr)
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_path.parent / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = input_path.suffix.lower()
    wav_path = output_dir / "audio_16k.wav"

    if ext in VIDEO_EXTS:
        print(f"[1/3] 提取音频 ({input_path.suffix})...", flush=True)
        extract_audio(input_path, wav_path)
    elif ext in AUDIO_EXTS:
        if ext == ".wav":
            try:
                with wave.open(str(input_path)) as f:
                    if f.getframerate() == 16000 and f.getsampwidth() == 2 and f.getnchannels() == 1:
                        wav_path = input_path
                        print("[1/3] WAV 已符合要求，跳过转换", flush=True)
                    else:
                        print("[1/3] 转换音频为 16kHz WAV...", flush=True)
                        convert_to_wav_16k(input_path, wav_path)
            except Exception:
                print("[1/3] 转换音频为 16kHz WAV...", flush=True)
                convert_to_wav_16k(input_path, wav_path)
        else:
            print("[1/3] 转换音频为 16kHz WAV...", flush=True)
            convert_to_wav_16k(input_path, wav_path)
    else:
        print(f"ERROR: 不支持的文件格式: {ext}", file=sys.stderr)
        return 1

    print("[2/3] 加载模型...", flush=True)
    try:
        recognizer = load_recognizer(args.model_dir, args.model_fp, args.num_threads, args.provider)
    except Exception as e:
        print(f"ERROR: 模型加载失败: {e}", file=sys.stderr)
        return 1

    print("[3/3] 转写中...", flush=True)
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

    print(f"\n{'=' * 60}", flush=True)
    print(f"✓ 转写完成", flush=True)
    print(f"  音频时长: {duration:.1f}s | 转写耗时: {elapsed:.1f}s | RTF: {rtf:.3f}", flush=True)
    print(f"  分段数: {len(segments)} | 字符数: {len(full_text)}", flush=True)
    print(f"  SRT: {srt_path}", flush=True)
    print(f"  TXT: {text_path}", flush=True)
    print(f"  JSON: {result_path}", flush=True)
    print(f"{'=' * 60}", flush=True)
    if full_text:
        print(f"\n预览: {full_text[:300]}{'…' if len(full_text) > 300 else ''}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
