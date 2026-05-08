# video-to-subtitle-summary

一个 Claude Code Skill，自动将视频平台视频或本地视频/音频文件转换为字幕文本并生成 AI 摘要。

**核心流程：**
- **在线视频：** 提供视频链接 → 自动下载视频或直接抓字幕 → 生成字幕 → AI 总结
- **本地文件：** 提供本地视频/音频路径 → 提取音频（如需）→ ASR 转写 → 生成字幕 → AI 总结

默认 ASR 后端是本地 **sherpa-onnx**（Paraformer 三语模型，中英粤，int8 量化），也支持切换到火山引擎 VC。

## 支持平台

**明确支持：**
- 抖音/TikTok (`douyin.com` / `tiktok.com`)
- 小红书 (`xiaohongshu.com` / `xhslink.com`)
- B站 (`bilibili.com` / `b23.tv`)
- YouTube (`youtube.com` / `youtu.be`)

**通用支持（yt-dlp 兼容）：**
- 微博、知乎、快手、西瓜视频、小红书等 **200+ 平台**
- 任何 yt-dlp 能下载的视频链接，都会自动回退到：下载 → 提取音频 → ASR 转写

## 效果展示

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

## 前置条件

### 必需依赖

```bash
# 1. sherpa-onnx（离线 ASR 引擎）
pip install sherpa-onnx

# 2. numpy（sherpa-onnx 依赖）
pip install numpy

# 3. ffmpeg（音视频处理）
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
```

### 可选依赖

```bash
# yt-dlp（B站/YouTube 等在线视频下载）
pip install yt-dlp
```

### TikHub Token（抖音/小红书/B站需要）

申请地址：https://tikhub.io/

免费套餐 100 次/天，付费从 $0.001/次起。

## 快速安装

### 1. 安装 Python 依赖

```bash
pip install sherpa-onnx numpy yt-dlp
```

### 2. 安装 ffmpeg

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件填入你的 TikHub Token
```

### 4. 运行

```bash
# 在线视频
python3 scripts/video_to_summary.py "https://www.bilibili.com/video/BVxxx"
python3 scripts/video_to_summary.py "https://v.douyin.com/xxx"

# 本地文件
python3 scripts/video_to_summary.py /path/to/video.mp4
python3 scripts/video_to_summary.py /path/to/audio.mp3
```

## 模型

### 三语模型（默认，自动下载）

- **语言**：普通话 + 粤语 + 英语
- **格式**：int8 量化，234MB
- **首次运行**：自动从 GitHub Releases 下载并解压
- **RTF**：≈ 0.08（12x 实时）

### 中文模型（备选）

- **语言**：普通话
- **格式**：int8 量化，214MB
- **RTF**：≈ 0.09

## ASR 后端对比

| 后端 | 模型加载 | 转写速度 | 语言 | 依赖 |
|------|----------|----------|------|------|
| **sherpa-onnx** (默认) | ~15s | **10x+ 实时** | 中英粤 | `pip install sherpa-onnx` |
| volcengine | 网络 | 秒级 | 中文 | API Key |

## 日志

运行日志自动缓存到 `/tmp/video_analysis/` 目录：
- `video_to_summary_<timestamp>.log` — 主脚本日志
- `transcribe_<timestamp>.log` — 转写脚本日志

## 项目结构

```text
video-to-subtitle-summary/
├── README.md
├── SKILL.md                      # Skill 本体
├── .env                          # 环境变量（已配置）
├── .gitignore
├── scripts/
│   ├── video_to_summary.py       # 主入口脚本
│   ├── transcribe_sherpa_onnx.py # sherpa-onnx 转写脚本
│   └── download_youtube_subtitles.py
├── sherpa-onnx-paraformer-trilingual-zh-cantonese-en/  # 三语模型（自动下载）
│   ├── model.int8.onnx           # int8 量化模型 (234MB)
│   └── tokens.txt
└── docs/
    └── tikhub-setup.md
```

## 费用说明

| 服务 | 费用 |
|------|------|
| TikHub API | 免费套餐 100 次/天，付费从 $0.001/次起 |
| sherpa-onnx | 免费，离线运行 |
| yt-dlp | 免费 |
| 火山引擎 VC | 按量计费（仅 volcengine 后端） |

## License

[MIT](./LICENSE)
