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

**验证**:
```python
import urllib.request, urllib.parse
req = urllib.request.Request(api_url, headers=headers)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read())
assert data.get("code") == 200
```

## 陷阱 2: ffmpeg 进度输出阻塞管道

**现象**: ffmpeg 提取音频时进程卡住，不产生输出也不退出。

**根因**: `-progress pipe:1` 将进度写到 stdout，但 `subprocess.run(capture_output=False)` 时 Python 不读取 stdout 管道。当管道缓冲区满（通常 64KB）后，ffmpeg 的 `write()` 调用阻塞，进程挂起。

**错误代码**:
```python
# ❌ 会阻塞
subprocess.run(["ffmpeg", "-progress", "pipe:1", ...], capture_output=False)
```

**修复方案**（推荐）: 使用 `capture_output=True` 静默捕获：
```python
# ✅ 安全
subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
```

**注意**: 不要用 `-progress pipe:1 -nostats` 配 `capture_output=False`，这仍然会阻塞。

## 陷阱 3: Python stdout 缓冲导致后台运行无输出

**现象**: `terminal(background=True)` 启动脚本后，`process(action="poll")` 返回空输出，但进程实际在运行。

**根因**: Python 在 non-interactive 模式下对 stdout 做全缓冲（不是行缓冲）。`print()` 输出积累在缓冲区不立即写出。

**修复**: shebang 改为无缓冲模式：
```python
#!/usr/bin/env python3 -u
```

或运行时加 `-u`：
```bash
python3 -u script.py
```

## 陷阱 4: faster-whisper CPU 模式性能极低

**现象**: small 模型转写 7 分钟音频需要 20+ 分钟，看起来像卡死。

**实测数据**（Intel Xeon D-1581 @ 1.8GHz, 20核）:
- 模型加载: ~140 秒
- 30 秒音频转写: ~36 秒（0.2x 实时）
- 7 分钟音频转写: ~22 分钟

**根因**: ctranslate2 在 CPU 上推理受限于单核性能，20 核 CPU 无法加速（faster-whisper 的 CPU 推理不能充分利用多核）。

**缓解方案**:
1. 设置 `cpu_threads` 参数（最多 16）：
   ```python
   model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=16)
   ```
2. 用 `tiny` 模型提速（精度下降）
3. 切换到 `volcengine` 云端 ASR（秒级返回）

**用户提示**: 脚本应在 ASR 开始前打印预估时间。

## 陷阱 5: B站会员画质限制

**现象**: yt-dlp 下载 B站视频时提示 1080P 高码率格式需要会员。

**表现**: yt-dlp 自动降级到 720P，不影响使用。

**解决**: 如需高画质，配置 cookies：`yt-dlp --cookies-from-browser chrome ...`

## 陷阱 6: sherpa-onnx 模型加载需要 15 秒

**现象**: 首次运行 sherpa-onnx 转写时，模型加载阶段约 15 秒无输出。

**根因**: ONNX Runtime 初始化 + 模型文件 mmap。正常行为，不是卡死。

**实测数据**（Intel Xeon D-1581 @ 1.8GHz, 20核, int8 模型）:
- 模型加载: ~15 秒
- 435 秒音频转写: ~38 秒（RTF=0.088，约 11x 实时）
- 总流程（URL→字幕）: ~3 分钟

**对比 faster-whisper**:
| 指标 | faster-whisper | sherpa-onnx |
|------|---------------|-------------|
| 模型加载 | 140s | **15s** |
| 转写速度 | 0.2x 实时 | **11x 实时** |
| 7 分钟音频 | ~22 分钟 | **38 秒** |

## 陷阱 7: 模型首次下载耗时

**现象**: 首次运行 faster-whisper 时长时间无输出。

**根因**: 自动下载模型文件（small ~500MB, tiny ~75MB）。

**预热命令**:
```bash
python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```
