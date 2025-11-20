# Claude Desktop 配置指南

由于 Claude Desktop 目前**只支持 stdio 传输**，我们提供了两种使用方式。

---

## 🎯 快速配置（推荐）

### 步骤 1: 找到配置文件

**Windows**:
```
%APPDATA%\Claude\claude_desktop_config.json
```

**macOS**:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

**Linux**:
```
~/.config/Claude/claude_desktop_config.json
```

### 步骤 2: 添加服务器配置

编辑 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "game-streaming": {
      "command": "uv",
      "args": [
        "--directory",
        "C:/path/to/screenshot-server",
        "run",
        "server_stdio.py"
      ]
    }
  }
}
```

**重要**：将 `C:/path/to/screenshot-server` 替换为您的实际路径！

**macOS/Linux 示例**:
```json
{
  "mcpServers": {
    "game-streaming": {
      "command": "uv",
      "args": [
        "--directory",
        "/home/user/screenshot-server",
        "run",
        "server_stdio.py"
      ]
    }
  }
}
```

### 步骤 3: 重启 Claude Desktop

配置修改后需要重启 Claude Desktop 才能生效。

### 步骤 4: 测试

在 Claude Desktop 中输入：
```
请帮我截取当前屏幕
```

或查看服务器信息：
```
请调用 get_server_info 工具
```

---

## 📊 两种模式对比

我们提供了两个服务器版本：

### 1. stdio 模式（用于 Claude Desktop）

**文件**: `server_stdio.py`

✅ **优点**:
- 直接兼容 Claude Desktop
- 配置简单
- 无需额外端口

❌ **限制**:
- 无法实时流式传输
- 每次请求独立
- 性能受限

**可用功能**:
- ✅ 单帧截图 (`capture_single_frame`)
- ✅ 连续捕获统计 (`start_continuous_capture`)
- ⚠️ 不支持 60 FPS 实时流

### 2. HTTP 模式（用于其他客户端）

**文件**: `server.py`

✅ **优点**:
- 60 FPS 实时流式传输
- 网络访问
- 多客户端并发
- 完全符合 MCP 规范

❌ **限制**:
- Claude Desktop 不直接支持
- 需要桥接器或等待官方支持

**适用场景**:
- 自定义客户端
- Web 应用
- 未来版本的 Claude Desktop

---

## 🛠️ 可用工具

### stdio 模式工具

#### 1. `capture_single_frame`
捕获单帧游戏画面

**参数**:
- `window_name` (可选): 窗口名称（指定要捕获的窗口）

**示例**:
```
请截取整个屏幕
请截取 "原神" 窗口的画面
```

#### 2. `start_continuous_capture`
启动连续捕获（返回统计信息）

**参数**:
- `window_name` (可选): 窗口名称
- `fps` (默认 10): 帧率 (1-30)
- `duration` (默认 30): 持续时间（秒）

**示例**:
```
请以 30 FPS 连续捕获 60 秒
```

**注意**: 这不会返回实时视频，只返回统计信息。

#### 3. `get_capture_stats`
查看捕获引擎统计

**示例**:
```
显示捕获统计信息
```

#### 4. `get_server_info`
查看服务器信息和使用提示

**示例**:
```
显示服务器信息
```

---

## 🔧 故障排除

### 问题 1: "Unsupported transport type 'streamable-http'"

**原因**: Claude Desktop 不支持 streamable-http

**解决**: 使用 stdio 配置（见上方）

### 问题 2: 工具未出现

**检查**:
1. 配置文件路径是否正确
2. JSON 格式是否有效
3. 路径是否使用绝对路径
4. 是否重启 Claude Desktop

**验证配置**:
```bash
# 在项目目录运行
uv run server_stdio.py
# 应该启动而不报错
```

### 问题 3: "windows-capture not available"

**原因**: 仅限 Windows 平台

**解决**:
- Windows: 安装 `pip install windows-capture`
- 其他平台: 自动降级到 pyautogui

### 问题 4: 找不到窗口

**原因**: 窗口名称不正确

**解决**:
1. 打开任务管理器查看准确的窗口标题
2. 或留空捕获整个屏幕

---

## 💡 最佳实践

### 1. 单帧截图（推荐）
```
请截取当前桌面
请帮我看看这个游戏画面
```

### 2. 连续捕获（统计）
```
请以 20 FPS 捕获 10 秒，然后告诉我统计信息
```

### 3. 查看状态
```
显示捕获统计
显示服务器信息
```

---

## 🚀 高级：使用 HTTP 服务器

如果您需要真正的 60 FPS 实时流式传输：

### 1. 启动 HTTP 服务器
```bash
uv run python server.py
```

服务器将在 `http://localhost:8000` 运行

### 2. 使用客户端示例
```bash
# 捕获单帧
uv run python client_example.py single_frame

# 流式传输 30 秒
uv run python client_example.py stream_30s

# 持续流式传输
uv run python client_example.py stream_continuous
```

### 3. 等待 Claude Desktop 支持

Claude Desktop 未来版本可能会支持 streamable-http。届时可直接配置：

```json
{
  "mcpServers": {
    "game-streaming": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

---

## 📚 相关文档

- [README_NEW.md](./README_NEW.md) - 完整功能文档
- [MCP_COMPLIANCE.md](./MCP_COMPLIANCE.md) - MCP 规范符合性
- [server_stdio.py](./server_stdio.py) - stdio 服务器源码
- [server.py](./server.py) - HTTP 服务器源码

---

## ❓ 常见问题

### Q: 为什么有两个服务器文件？

**A**:
- `server_stdio.py` - Claude Desktop 使用（当前）
- `server.py` - 网络客户端使用 / 未来 Claude Desktop 支持

### Q: stdio 模式能实现 60 FPS 流式传输吗？

**A**: 不能。stdio 协议是请求-响应模式，不支持持续流。

### Q: 什么时候能用 streamable-http？

**A**: 等待 Claude Desktop 官方支持，或使用自定义客户端。

### Q: 如何获取窗口名称？

**A**:
1. Windows 任务管理器 → 详细信息 → 查看窗口标题
2. 或直接留空捕获整个屏幕

---

**开始使用吧！** 🎮✨
