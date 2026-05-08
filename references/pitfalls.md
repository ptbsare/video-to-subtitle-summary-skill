# video_to_summary.py — 已知陷阱与修复记录

## 陷阱 1: TikHub API 返回 403

**现象**: `urllib.request.urlopen` 调用 TikHub API 返回 `HTTP Error 403: Forbidden`，但同一 Token 用 `curl` 正常。

**根因**: `urllib.request` 默认 `User-Agent: Python-urllib/3.14`，被 TikHub 的 Cloudflare WAF 拦截。`curl` 自带浏览器 UA 所以能通过。

**修复**: 所有 `urllib.request.Request` 调用必须携带浏览器 UA：
```python
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
```

## 陷阱 2: ffmpeg 进度输出阻塞管道

**现象**: ffmpeg 提取音频时进程卡住，不产生输出也不退出。

**根因**: `-progress pipe:1` 将进度写到 stdout，但 `subprocess.run(capture_output=False)` 时 Python 不读取 stdout 管道。当管道缓冲区满（通常 64KB）后，ffmpeg 的 `write()` 调用阻塞，进程挂起。

**修复**: 使用 `capture_output=True` 静默捕获：
```python
subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
```

## 陷阱 3: Python stdout 缓冲（后台模式）

**现象**: `background=true` 模式下脚本长时间无输出，看起来像卡住了，但实际上在运行。

**根因**: Python 在 non-interactive 模式下 stdout 全缓冲。

**修复**: shebang 改为 `#!/usr/bin/env python3 -u`（强制无缓冲）。

## 陷阱 4: faster-whisper 在慢速 CPU 上极慢

**现象**: Xeon D-1581 @ 1.8GHz 上 small 模型加载需 140 秒，转写速度仅 0.2x 实时（7 分钟音频需 ~22 分钟）。

**根因**: CPU 单核性能弱，ctranslate2 推理慢。模型加载是主要瓶颈。

**修复**: 切换 sherpa-onnx Paraformer int8 — 模型加载 ~15s，转写 10x+ 实时（RTF ≈ 0.08）。

## 陷阱 5: sherpa-onnx 模型文件缺失

**现象**: 首次运行时报 `Model file not found`。

**修复**: 脚本已内置自动下载逻辑。首次运行时自动从 GitHub Releases 下载并解压：
```
https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-trilingual-zh-cantonese-en.tar.bz2
```
解压后只保留 `model.int8.onnx` (234MB) + `tokens.txt`，删除其他无关文件。

支持 `--no-auto-download` 参数跳过自动下载。

**注意**: 不要用 `-progress pipe:1 -nostats` 配 `capture_output=False`，这仍然会阻塞。

## 陷阱 3: Python stdout 缓冲导致后台运行无输出

**现象**: `terminal(background=True)` 启动脚本后，`process(action="poll")` 返回空输出，但进程实际在运行。

**根因**: Python 在 non-interactive 模式下对 stdout 做全缓冲。

**修复**: shebang 改为无缓冲模式：
```python
#!/usr/bin/env python3 -u
```

## 陷阱 4: sherpa-onnx 模型加载需要 ~15 秒

**现象**: 首次运行时模型加载阶段约 15 秒无输出。正常行为，不是卡死。

**实测数据**（Intel Xeon D-1581 @ 1.8GHz, 20核, int8 模型）:
- 模型加载: ~15 秒
- 435 秒音频转写: ~38 秒（RTF=0.088，约 11x 实时）
- 总流程（URL→字幕）: ~3 分钟

**关键参数**: `cpu_threads` 必须设置（默认 1），建议设为 `min(cpu_count, 16)`。

## 陷阱 5: sherpa-onnx 模型文件 protobuf 解析失败

**现象**: `RuntimeError: Load model from .../model.onnx failed:Protobuf parsing failed.`

**根因**: 模型文件解压不完整（tar 进程还在写文件时就尝试加载）。

**修复**: 确保 tar 解压完成后再运行脚本。检查文件大小是否稳定。

**注意**: 使用 `model.int8.onnx`（234MB）比 `model.onnx`（831MB）加载更快且精度损失小。

## 陷阱 6: B站会员画质限制

**现象**: yt-dlp 下载 B站视频时提示 1080P 高码率格式需要会员。

**表现**: yt-dlp 自动降级到 720P，不影响使用。

## 陷阱 7: 依赖缺失时脚本应显式报错

**当前脚本依赖清单**:
| 包 | 用途 | 安装命令 |
|---|---|---|
| `sherpa-onnx` | 离线 ASR | `pip install sherpa-onnx` |
| `numpy` | 数组处理 | `pip install numpy` |
| `ffmpeg` | 音视频处理 | `apt install ffmpeg` / `brew install ffmpeg` |
| `yt-dlp` | 视频下载 | `pip install yt-dlp` |

每个脚本在入口处检查依赖，缺失时打印安装命令后 `sys.exit(1)`。
