# MCP 游戏串流服务器架构分析与改进方案

## 📋 目录
1. [当前架构分析](#当前架构分析)
2. [核心限制与问题](#核心限制与问题)
3. [改进需求](#改进需求)
4. [新架构设计](#新架构设计)
5. [技术选型](#技术选型)
6. [实现路线图](#实现路线图)

---

## 当前架构分析

### 现有实现概述
```
┌─────────────────┐
│  MCP Client     │  (本地客户端)
│   (clint.py)    │
└────────┬────────┘
         │ stdio (子进程)
         ▼
┌─────────────────┐
│  MCP Server     │  (本地进程)
│ (screenshot.py) │
└────────┬────────┘
         │
         ▼
   pyautogui.screenshot()
   (低效的屏幕捕获)
```

### 当前技术栈
- **传输层**: stdio（标准输入/输出）
- **捕获方式**: pyautogui（基于 PIL/Pillow）
- **工作模式**: 按需单次截图
- **部署方式**: 本地子进程
- **连接方式**: 仅限本地客户端

---

## 核心限制与问题

### 🚫 1. 传输层限制
| 问题 | 描述 | 影响 |
|-----|------|------|
| **stdio 只支持本地** | 需要在同一台机器上启动子进程 | ❌ 无法远程访问 |
| **无网络服务** | 不监听网络端口 | ❌ 其他机器无法连接 |
| **子进程依赖** | 每个客户端需要启动新进程 | ❌ 资源浪费 |

### 🐌 2. 性能问题
| 问题 | 描述 | 影响 |
|-----|------|------|
| **pyautogui 低效** | 基于 PIL，CPU 密集型 | ⚠️ 无法实现高帧率 |
| **无硬件加速** | 不使用 GPU/DXGI | ⚠️ 游戏捕获卡顿 |
| **单次截图模式** | 每次都重新捕获整个屏幕 | ⚠️ 无法流式传输 |

### 🎮 3. 游戏串流不可行
| 问题 | 描述 | 影响 |
|-----|------|------|
| **无实时流式传输** | 只能单帧截图 | ❌ 无法实现实时游戏串流 |
| **无帧率控制** | 没有 FPS 限制机制 | ❌ 无法稳定输出 |
| **高延迟** | CPU 捕获 + JPEG 编码慢 | ❌ 游戏体验差 |

---

## 改进需求

### ✅ 核心需求
1. **网络访问能力**
   - 任何 MCP 客户端可以通过网络连接
   - 支持远程访问游戏画面

2. **高效屏幕捕获**
   - 使用 `windows-capture-python`（DXGI API）
   - 硬件加速，低延迟
   - 适合游戏高帧率捕获

3. **Streamable HTTP 传输**
   - 符合 MCP 2025-06-18 规范
   - 支持双向流式通信
   - HTTP/2 多路复用

4. **实时游戏串流**
   - 持续帧流传输
   - 可配置帧率（30/60 FPS）
   - 低延迟编码

---

## 新架构设计

### 🏗️ 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    任何 MCP 客户端                        │
│  (Claude Desktop / 自定义客户端 / Web 应用)               │
└───────────────┬─────────────────────────────────────────┘
                │
                │ HTTP/2 (Streamable HTTP)
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│              MCP Streamable HTTP Server                  │
│                  (FastAPI + httpx)                       │
├─────────────────────────────────────────────────────────┤
│  Endpoints:                                              │
│  - POST /mcp/v1/messages (请求-响应)                     │
│  - POST /mcp/v1/stream   (双向流式)                      │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│              MCP Tools & Resources                       │
├─────────────────────────────────────────────────────────┤
│  Tools:                                                  │
│  - start_game_stream(window_name, fps)                   │
│  - stop_game_stream()                                    │
│  - capture_single_frame()                                │
│  - list_capturable_windows()                             │
│                                                          │
│  Resources:                                              │
│  - game://stream/live (实时流资源)                       │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│         Windows Capture Engine                           │
│         (windows-capture-python)                         │
├─────────────────────────────────────────────────────────┤
│  • DXGI Desktop Duplication API                          │
│  • 硬件加速捕获                                           │
│  • 低 CPU 占用 (<5%)                                     │
│  • 高帧率支持 (60+ FPS)                                  │
└───────────────┬─────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│            Frame Processing Pipeline                     │
├─────────────────────────────────────────────────────────┤
│  1. DXGI 捕获 (GPU)                                      │
│  2. 格式转换 (RGB/YUV)                                   │
│  3. 视频编码 (H.264/JPEG)                                │
│  4. 流式传输 (Chunked Transfer)                          │
└─────────────────────────────────────────────────────────┘
```

### 🔄 数据流图

```
游戏窗口
   │
   ▼
[DXGI 捕获] ──→ GPU Frame Buffer
   │                    │
   │                    ▼
   │              [格式转换]
   │                    │
   │                    ▼
   │              [视频编码]
   │                    │
   │                    ▼
   └──────────→ [帧队列缓冲区]
                      │
                      ▼
              [HTTP 流式传输]
                      │
                      ▼
               MCP 客户端
```

---

## 技术选型

### 1️⃣ 屏幕捕获：windows-capture-python

#### 为什么选择？
| 特性 | pyautogui | windows-capture-python |
|-----|-----------|------------------------|
| **API** | PIL Screenshot | DXGI Desktop Duplication |
| **性能** | CPU 密集型 | GPU 加速 |
| **延迟** | 50-100ms | 5-15ms |
| **CPU 占用** | 20-40% | <5% |
| **帧率** | ~10 FPS | 60+ FPS |
| **游戏兼容性** | ❌ 黑屏/卡顿 | ✅ 完美支持 |

#### 核心优势
```python
# DXGI API 的优势：
✅ 直接访问 GPU 帧缓冲区
✅ 零拷贝技术（Zero-Copy）
✅ 硬件加速编码
✅ 窗口级别捕获（无需全屏）
✅ 支持多显示器
✅ 游戏反作弊友好
```

#### 示例代码
```python
from windows_capture import WindowsCapture, Frame, InternalCaptureControl

class GameCapture:
    def __init__(self):
        self.frames = []

    def on_frame_arrived(self, frame: Frame, control: InternalCaptureControl):
        # 每帧回调，低延迟
        frame_data = frame.get_buffer()  # 零拷贝获取
        self.frames.append(frame_data)

    def start_capture(self, window_name: str):
        capture = WindowsCapture(
            cursor_capture=True,
            draw_border=False,
            monitor_index=None,
            window_name=window_name
        )
        capture.start(self.on_frame_arrived)
```

### 2️⃣ 传输层：Streamable HTTP

#### MCP Streamable HTTP 规范 (2025-06-18)

##### 端点设计
```
POST /mcp/v1/messages
- Content-Type: application/json
- 单次请求-响应
- 用于：工具调用、资源获取

POST /mcp/v1/stream
- Content-Type: application/x-ndjson
- Transfer-Encoding: chunked
- 双向流式传输
- 用于：实时游戏流
```

##### 消息格式（NDJSON）
```json
// 客户端请求
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"start_game_stream","arguments":{"window":"<窗口名称>","fps":60}}}

// 服务器流式响应
{"jsonrpc":"2.0","id":1,"result":{"frame":1,"data":"base64..."}}
{"jsonrpc":"2.0","id":1,"result":{"frame":2,"data":"base64..."}}
{"jsonrpc":"2.0","id":1,"result":{"frame":3,"data":"base64..."}}
```

#### 为什么不用 SSE？
| 特性 | SSE | Streamable HTTP |
|-----|-----|-----------------|
| **方向** | 单向（服务器→客户端） | 双向 |
| **协议** | HTTP/1.1 | HTTP/2 推荐 |
| **控制** | 无客户端控制 | 客户端可发送命令 |
| **标准** | ❌ 非 MCP 标准 | ✅ MCP 2025 规范 |

### 3️⃣ Web 框架：FastAPI

#### 选择理由
```python
✅ 原生 async/await 支持
✅ 流式响应内置支持
✅ 自动 OpenAPI 文档
✅ 高性能（基于 Starlette）
✅ 类型提示友好
```

#### 实现示例
```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/mcp/v1/stream")
async def mcp_stream(request: Request):
    async def frame_generator():
        async for frame in capture_frames():
            yield f"{json.dumps(frame)}\n"

    return StreamingResponse(
        frame_generator(),
        media_type="application/x-ndjson"
    )
```

---

## 实现路线图

### Phase 1: 基础设施 (Week 1)
- [ ] 安装 `windows-capture-python` 依赖
- [ ] 创建 FastAPI 服务器框架
- [ ] 实现 Streamable HTTP 端点
- [ ] 基础 MCP 协议处理

### Phase 2: 捕获引擎 (Week 1-2)
- [ ] 集成 DXGI 捕获
- [ ] 窗口枚举和选择
- [ ] 帧率控制（30/60 FPS）
- [ ] 多显示器支持

### Phase 3: 流式传输 (Week 2)
- [ ] 实时帧队列管理
- [ ] NDJSON 流式编码
- [ ] 背压控制（Backpressure）
- [ ] 客户端暂停/恢复

### Phase 4: 优化与测试 (Week 3)
- [ ] 性能优化（延迟 <50ms）
- [ ] 内存管理（防止泄漏）
- [ ] 错误处理和重连
- [ ] 压力测试（多客户端）

---

## 关键实现细节

### 1. 帧捕获线程
```python
import asyncio
from collections import deque

class FrameBuffer:
    def __init__(self, max_size=30):
        self.buffer = deque(maxlen=max_size)
        self.lock = asyncio.Lock()

    async def push(self, frame):
        async with self.lock:
            self.buffer.append(frame)

    async def pop(self):
        async with self.lock:
            return self.buffer.popleft() if self.buffer else None
```

### 2. 背压控制
```python
class StreamController:
    def __init__(self, target_fps=60):
        self.target_fps = target_fps
        self.frame_time = 1.0 / target_fps
        self.last_frame_time = time.time()

    async def wait_for_next_frame(self):
        elapsed = time.time() - self.last_frame_time
        sleep_time = max(0, self.frame_time - elapsed)
        await asyncio.sleep(sleep_time)
        self.last_frame_time = time.time()
```

### 3. MCP 工具注册
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("game-streaming-server")

@mcp.tool()
async def start_game_stream(
    window_name: str,
    fps: int = 30,
    quality: int = 80
) -> dict:
    """启动游戏窗口的实时流式传输"""
    stream_id = await game_capture.start(window_name, fps, quality)
    return {
        "stream_id": stream_id,
        "status": "streaming",
        "fps": fps
    }
```

---

## 预期性能指标

| 指标 | 当前 (pyautogui) | 改进后 (DXGI) |
|-----|-----------------|--------------|
| **帧率** | ~10 FPS | 60 FPS |
| **延迟** | 80-150ms | 15-30ms |
| **CPU 占用** | 30-50% | 3-8% |
| **内存占用** | ~200MB | ~150MB |
| **网络带宽** | N/A | 2-8 Mbps |

---

## 配置示例

### Claude Desktop 配置
```json
{
  "mcpServers": {
    "game-streaming": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp",
      "description": "实时游戏串流服务器"
    }
  }
}
```

### 服务器配置文件
```yaml
# config.yaml
server:
  host: 0.0.0.0
  port: 8000

capture:
  default_fps: 30
  max_fps: 60
  quality: 80

stream:
  buffer_size: 30
  max_clients: 5
```

---

## 总结

### 核心改进
1. ✅ **传输层**: stdio → Streamable HTTP
2. ✅ **捕获方式**: pyautogui → windows-capture-python (DXGI)
3. ✅ **工作模式**: 单次截图 → 实时流式传输
4. ✅ **部署方式**: 本地子进程 → 网络服务器

### 预期收益
- 🚀 **60 FPS** 游戏串流
- 🌐 **远程访问**能力
- ⚡ **低延迟** (<30ms)
- 💪 **低 CPU 占用** (<5%)
- 🔧 **任何 MCP 客户端**都能连接

---

## 下一步
开始实现 Phase 1：搭建 FastAPI + Streamable HTTP 基础架构
