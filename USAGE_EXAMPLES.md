# 使用示例

## 1. 使用 uvx 直接运行 MCP 服务器（推荐）

```bash
# 启动 MCP 服务器
uvx github.com/ptbsare/video-to-subtitle-summary-skill
```

服务器启动后，可以通过任何 MCP 客户端发送请求。

## 2. MCP 客户端示例

### 使用 Python MCP 客户端

```python
import asyncio
from mcp.client import MCPClient

async def main():
    # 连接到 MCP 服务器
    client = MCPClient()
    await client.connect("stdio://video-to-subtitle-summary-skill")
    
    # 列出可用工具
    tools = await client.list_tools()
    print(f"Available tools: {[tool.name for tool in tools]}")
    
    # 调用工具
    result = await client.call_tool(
        name="video_to_subtitle_summary",
        arguments={
            "input": "https://www.bilibili.com/video/BVxxx",
            "output_dir": "/tmp/my_analysis"
        }
    )
    
    print(f"Result: {result}")

asyncio.run(main())
```

### 使用 Claude Desktop

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

然后在 Claude Desktop 中使用 `video_to_subtitle_summary` 工具。

## 3. 独立脚本模式

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

## 4. 工具参数

### video_to_subtitle_summary

提取视频字幕并生成 AI 摘要。

**参数：**
- `input` (必需): 视频 URL 或本地文件路径
  - 支持平台: douyin.com, xiaohongshu.com, bilibili.com, youtube.com
  - 支持格式: .mp4, .mp3, .wav, .m4a, .flac, .ogg, .aac, .wma
- `output_dir` (可选): 输出目录，默认为 `/tmp/video_analysis/<video_id>`

**返回值：**
- 格式化的文本，包含：
  - 视频信息（平台、标题、作者）
  - 字幕文本（前500字）
  - 生成的文件列表
  - 完整结果路径

## 5. 输出文件

工具生成以下文件到输出目录：

- `subtitle.srt` — SRT 字幕文件
- `text.txt` — 纯文本转录
- `result.json` — 完整结果（包含元数据）

## 6. 示例输出

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
