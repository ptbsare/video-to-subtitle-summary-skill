# video-to-subtitle-summary-skill

一个支持 MCP 协议的视频转字幕 + AI 总结技能，可直接通过 uvx 运行。

> **核心流程：**
> - **在线视频：** 提供视频链接 → 自动下载视频或直接抓字幕 → ASR 转写 → 生成字幕 → AI 总结
> - **本地文件：** 提供本地视频/音频路径 → 提取音频（如需）→ ASR 转写 → 生成字幕 → AI 总结

默认 ASR 后端是本地 **sherpa-onnx**（Paraformer 三语模型，中英粤，int8 量化），也支持切换到火山引擎 VC。

English docs: [README_en.md](./README_en.md) *(已合并至本文件)*

---

## 🚀 快速开始

### 推荐方式：uvx 一键运行

```bash
# 启动 MCP stdio 服务器（自动下载并安装所有依赖）
uvx github.com/ptbsare/video-to-subtitle-summary-skill
```

服务器启动后会监听 stdin/stdout 接收 MCP 消息，适合集成到任何 MCP 客户端。

### 独立脚本模式

```bash
# 克隆仓库
git clone https://github.com/ptbsare/video-to-subtitle-summary-skill.git
cd video-to-subtitle-summary-skill

# 安装依赖
pip install sherpa-onnx numpy yt-dlp mcp

# 运行
python3 scripts/video_to_summary.py "https://www.bilibili.com/video/BVxxx"
python3 scripts/video_to_summary.py /path/to/video.mp4
```

### 本地构建安装

```bash
cd video-to-subtitle-summary-skill
pip install build
python3 -m build
pip install dist/*.whl

# 然后直接运行
video-to-subtitle-summary-skill
```

---

## 🎯 MCP 异步任务模式

MCP 服务器暴露 **两个工具**，采用异步任务模式避免长时间阻塞导致客户端超时。

### 工具 1：`submit_video_task` — 提交任务，立即返回 task_id

```json
{
  "name": "submit_video_task",
  "arguments": {
    "input": "https://v.douyin.com/xxx"
  }
}
```

`output_dir` 可选，默认 `/tmp/video_analysis/<video_id>`。任务完成后 `query_video_task` 会返回实际输出目录路径。

返回示例：
```
✅ 任务已提交

- task_id: abc123def456
- input: https://v.douyin.com/xxx

请使用 query_video_task 查询进度和结果。
```

### 工具 2：`query_video_task` — 查询任务状态和结果

```json
{
  "name": "query_video_task",
  "arguments": {
    "task_id": "abc123def456"
  }
}
```

返回状态：
- **pending** — 等待处理
- **processing** — 处理中（含当前阶段和进度百分比）
- **completed** — 已完成（**字幕文本直接返回，无需读文件**）
- **failed** — 失败（含错误信息）
- **expired** — 已过期（默认 1 小时 TTL，需重新提交）

### 进度阶段

处理过程中会更新以下阶段：

| 阶段 | 说明 | 大致进度 |
|------|------|----------|
| `validating` | 检查依赖 & 输入 | 0% |
| `downloading_model` | 下载 ASR 模型（首次运行，~234MB） | 14% |
| `fetching_info` | 获取视频信息 (TikHub) | 28% |
| `downloading` | 下载视频/音频 | 42% |
| `extracting_audio` | ffmpeg 提取音频 | 57% |
| `transcribing` | ASR 转写 | 71% |
| `finalizing` | 生成输出文件 | 85% |
| `completed` | 处理完成 | 100% |

### 典型调用流程

```
submit_video_task(input="...") → task_id
query_video_task(task_id) → processing 33% (downloading)
query_video_task(task_id) → processing 66% (transcribing)
query_video_task(task_id) → completed (含完整字幕文本)
```

---

## 💻 MCP 客户端集成

### Claude Desktop

在 Claude Desktop 配置文件中添加：

```json
{
  "mcpServers": {
    "video-to-subtitle-summary-skill": {
      "command": "uvx",
      "args": ["github.com/ptbsare/video-to-subtitle-summary-skill"]
    }
  }
}
```

### Python MCP 客户端

```python
import asyncio
from mcp.client import MCPClient

async def main():
    client = MCPClient()
    await client.connect("stdio://video-to-subtitle-summary-skill")

    # 列出可用工具
    tools = await client.list_tools()
    print(f"Available tools: {[t.name for t in tools]}")

    # 提交任务
    result = await client.call_tool("submit_video_task", {
        "input": "https://www.bilibili.com/video/BVxxx"
    })
    print(result)

    # 查询结果
    task_id = "从返回结果中提取的 task_id"
    while True:
        status = await client.call_tool("query_video_task", {"task_id": task_id})
        print(status)
        if "completed" in status or "failed" in status:
            break
        await asyncio.sleep(10)

asyncio.run(main())
```

---

## 📺 支持平台

**明确支持（有专门解析逻辑）：**
- 抖音/TikTok (`douyin.com` / `tiktok.com`)
- 小红书 (`xiaohongshu.com` / `xhslink.com`)
- B站 (`bilibili.com` / `b23.tv`)
- YouTube (`youtube.com` / `youtu.be`)

**通用支持（yt-dlp 自动回退）：**
- 微博、知乎、快手、西瓜视频等 **200+ 平台**
- 任何 yt-dlp 能下载的视频链接，自动回退到：下载 → 提取音频 → ASR 转写

**本地文件格式：**
- 视频：`.mp4` `.mov` `.avi` `.mkv` `.webm` `.flv` `.wmv`
- 音频：`.mp3` `.wav` `.m4a` `.flac` `.ogg` `.aac` `.wma`

---

## 📦 依赖

### 必需

```bash
pip install sherpa-onnx numpy yt-dlp mcp
```

```bash
# Ubuntu/Debian
sudo apt install ffmpeg
# macOS
brew install ffmpeg
```

### 依赖清单

| 包 | 用途 | 安装命令 |
|---|---|---|
| `sherpa-onnx` | 离线 ASR 引擎 | `pip install sherpa-onnx` |
| `numpy` | 数组处理 | `pip install numpy` |
| `ffmpeg` | 音视频处理 | `apt install ffmpeg` / `brew install ffmpeg` |
| `yt-dlp` | 在线视频下载 | `pip install yt-dlp` |
| `mcp` | MCP SDK（服务器模式必需） | `pip install mcp` |

---

## 🔧 环境变量

在 `.env` 文件中配置或通过 shell 环境变量传入。MCP 服务器启动时会自动加载 `.env` 文件，同时也支持在 MCP 客户端配置中通过 `env` 字段传递环境变量。

### 完整环境变量列表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ASR_BACKEND` | `sherpa-onnx` | ASR 后端：`sherpa-onnx`（离线）\| `volcengine`（云端） |
| `TIKHUB_TOKEN` | — | TikHub API Token（抖音/小红书/B站需要，YouTube 不需要） |
| `BYTEDANCE_VC_TOKEN` | — | 火山引擎 VC Token（仅 `ASR_BACKEND=volcengine` 时生效） |
| `BYTEDANCE_VC_APPID` | — | 火山引擎 VC AppID（仅 `ASR_BACKEND=volcengine` 时生效） |
| `YTDLP_COOKIE_FILE` | — | YouTube Cookie 文件路径（Netscape 格式），见下方详细说明 |
| `YTDLP_COOKIES` | — | YouTube Cookie 字符串（`key1=val1; key2=val2` 格式），优先级最低 |
| `YTDLP_WORKERS` | `4` | yt-dlp 并发下载线程数 |

### .env 文件示例

```bash
# ASR 后端
ASR_BACKEND=sherpa-onnx

# TikHub API Token
TIKHUB_TOKEN=your_tikhub_token_here

# 火山引擎（可选）
BYTEDANCE_VC_TOKEN=your_vc_token
BYTEDANCE_VC_APPID=your_vc_appid

# YouTube Cookie — 推荐方式：指定文件路径
YTDLP_COOKIE_FILE=/root/.cookies.txt
```

### YouTube Cookie 配置详解

YouTube 经常需要登录验证才能下载。支持**三种方式**（优先级从高到低）：

1. **（推荐）环境变量 `YTDLP_COOKIE_FILE`**：
   ```bash
   export YTDLP_COOKIE_FILE=/path/to/cookies.txt
   ```
   或在 MCP 客户端配置中传递：
   ```json
   {
     "mcpServers": {
       "video-to-subtitle-summary-skill": {
         "command": "uvx",
         "args": ["github.com/ptbsare/video-to-subtitle-summary-skill"],
         "env": {
           "YTDLP_COOKIE_FILE": "/root/.cookies.txt"
         }
       }
     }
   }
   ```

2. **自动检测**：在 skill 根目录下放置 `cookies.txt` 文件（Netscape 格式），脚本自动检测（已加入 `.gitignore`）

3. **环境变量 `YTDLP_COOKIES`**：直接传递 cookie 字符串
   ```bash
   export YTDLP_COOKIES="key1=val1; key2=val2; ..."
   ```

Cookie 导出教程：<https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp>

### TikHub Token 申请

申请地址：<https://tikhub.io/>（免费套餐 100 次/天，付费从 $0.001/次起）

申请步骤：
1. 访问 <https://user.tikhub.io/register?referral_code=2lyqStPc> 注册
2. 登录后进入 **用户中心** → **API Keys** → **创建新 Token**
3. 复制 Token 到 `.env` 文件

---

## 🤖 ASR 后端对比

### sherpa-onnx（默认）

- **模型**：Paraformer 三语（普通话 + 粤语 + 英语），int8 量化 (234MB)
- **首次运行**：自动从 GitHub Releases 下载模型
- **模型加载**：~15 秒，**转写速度**：10x+ 实时（RTF ≈ 0.08）
- **离线运行**，无需 API Key

```bash
# 单独使用转写脚本
python3 scripts/transcribe_sherpa_onnx.py <音频或视频文件> [--output-dir /tmp/out]
```

### volcengine（可选）

- 云端转写，秒级返回
- 需 `BYTEDANCE_VC_TOKEN` + `BYTEDANCE_VC_APPID`

| 后端 | 模型加载 | 转写速度 | 语言 | 依赖 |
|------|----------|----------|------|------|
| **sherpa-onnx** (默认) | ~15s | **10x+ 实时** | 中英粤 | `pip install sherpa-onnx` |
| volcengine | 网络 | 秒级 | 中文 | API Key |

---

## 📁 输出文件

工具生成以下文件到输出目录（默认 `/tmp/video_analysis/<video_id>`）：

- `subtitle.srt` — SRT 字幕文件
- `text.txt` — 纯文本转录
- `result.json` — 完整结果（含 text, video_info, segments, 文件路径）

运行日志自动缓存到 `/tmp/video_analysis/` 目录。

---

## 🎨 效果展示

输入一个视频链接或本地文件路径，自动输出：

```markdown
## 视频分析结果

### 视频信息
| 项目 | 内容 |
|------|------|
| 平台 | B站 |
| 标题 | 说一说起迪max4的使用体验 |
| 作者 | 3D学习小屋屋 |

### AI生成标题
起帝max4 3D打印机深度体验

### AI摘要
本期视频博主详细分享了起帝max4 3D打印机的使用体验...

### 核心要点
1. 散热方案是核心优势：原厂自带机器空调
2. 大型打印无需拼接：一次性打印满板
3. 多色盒子设计可靠：防堵死防跑料
```

---

## ⚠️ 已知陷阱与故障排除

### TikHub API 403

**现象**：`urllib.request` 调用 TikHub API 返回 403，但同一 Token 用 `curl` 正常。

**原因**：`urllib` 默认 UA 被 Cloudflare WAF 拦截。

**状态**：已修复，所有请求携带浏览器 UA。

### TikHub 下载地址为空

**现象**：抖音视频 `play_addr.url_list` 返回空列表。

**原因**：`minimal=true` 参数精简了响应字段。

**状态**：已修复，使用完整响应，优先 `download_addr`（无水印）。

### YouTube "Sign in to confirm you're not a bot"

**现象**：yt-dlp 下载 YouTube 视频时报错需要登录验证。

**解决**：配置 YouTube Cookie（见上方环境变量说明）。

### B站会员画质限制

**现象**：1080P 高码率格式需要会员。

**状态**：yt-dlp 自动降级到 720P，不影响使用。

### sherpa-onnx 模型文件缺失

**现象**：`RuntimeError: Model file not found`。

**解决**：脚本已内置自动下载逻辑。首次运行自动从 GitHub Releases 下载。若自动下载失败，手动下载：
```bash
wget https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-paraformer-trilingual-zh-cantonese-en.tar.bz2
```

### ffmpeg 提取音频超时

**现象**：ffmpeg 提取音频时进程卡住。

**原因**：进度输出阻塞管道。

**状态**：已修复，使用 `capture_output=True` 静默捕获。

### 常见错误速查

| 问题 | 解决方案 |
|------|----------|
| `缺少依赖: sherpa-onnx` | `pip install sherpa-onnx` |
| `缺少依赖: ffmpeg` | `sudo apt install ffmpeg` |
| `缺少依赖: yt-dlp` | `pip install yt-dlp` |
| YouTube "Sign in to confirm" | 配置 Cookie（见上方说明） |
| TikHub API 403 | 检查 Token 是否正确/过期 |
| TikHub API 429 | 超出免费额度，等待次日重置 |

---

## 💰 费用说明

| 服务 | 费用 |
|------|------|
| TikHub API | 免费套餐 100 次/天，付费从 $0.001/次起 |
| sherpa-onnx | 免费，离线运行 |
| yt-dlp | 免费 |
| 火山引擎 VC | 按量计费（仅 volcengine 后端） |

---

## 📂 项目结构

```
video-to-subtitle-summary-skill/
├── README.md                     # 本文档
├── SKILL.md                      # Skill 本体（AI 使用指南）
├── mcp_server.py                 # MCP 服务器实现（异步任务模式）
├── run_mcp_server.py             # uvx 入口点
├── pyproject.toml                # uvx 包配置
├── install_as_uvx.py             # 本地构建安装辅助脚本
├── .env                          # 环境变量配置
├── .gitignore
├── scripts/
│   ├── video_to_summary.py       # 主入口脚本
│   ├── transcribe_sherpa_onnx.py # sherpa-onnx 转写脚本
│   └── download_youtube_subtitles.py
├── sherpa-onnx-paraformer-trilingual-zh-cantonese-en/  # 三语模型（自动下载）
│   ├── model.int8.onnx           # int8 量化模型 (234MB)
│   └── tokens.txt
├── tests/
│   └── test_download_youtube_subtitles.py
├── test_mcp_server.py            # MCP 服务器测试脚本
└── docs/
    └── tikhub-setup.md           # TikHub 申请教程
```

---

## 🧪 测试

```bash
# 运行 MCP 服务器测试
python3 test_mcp_server.py

# 运行单元测试
python3 -m pytest tests/
```

---

## License

[MIT](./LICENSE)
