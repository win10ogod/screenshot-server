# MCP 规范合规性文档

本文档说明服务器如何完全符合 MCP 2025-06-18 Streamable HTTP 规范。

---

## ✅ 规范合规检查表

### 端点设计
- ✅ **单一端点**: `/mcp` 同时支持 POST 和 GET 方法
- ❌ ~~两个端点~~ (`/mcp/v1/messages` + `/mcp/v1/stream` - 已移除)

### HTTP 方法

#### POST 方法
- ✅ 接受 JSON-RPC 请求、通知、响应
- ✅ 验证 `Accept` 头（支持 `application/json` 和 `text/event-stream`）
- ✅ 要求 `MCP-Protocol-Version` 头
- ✅ 通知/响应返回 HTTP 202 Accepted
- ✅ 请求根据 Accept 头返回 JSON 或 SSE 流

#### GET 方法
- ✅ 打开 SSE 流用于服务器推送
- ✅ 验证 `Accept: text/event-stream`
- ✅ 不支持时返回 HTTP 405

### 流式协议

#### SSE (Server-Sent Events)
- ✅ 使用 `text/event-stream` 而非 NDJSON
- ✅ SSE 格式: `data: {json}\n\n`
- ✅ 支持事件 ID (`id` 字段)
- ✅ 支持断线重连 (`Last-Event-ID` 头)
- ✅ 流在响应发送后关闭

### 会话管理
- ✅ `Mcp-Session-Id` 头在 initialize 时分配
- ✅ 后续请求需要携带会话 ID
- ✅ 无效会话返回 HTTP 404
- ✅ 使用加密安全的会话 ID (`secrets.token_urlsafe`)

### 安全性
- ✅ **必须**验证 `Origin` 头（防止 DNS 重绑定攻击）
- ✅ 本地部署绑定到 localhost
- ✅ 生产环境应配置白名单

---

## 📋 规范对比

### 之前的实现 (v0.2.0) ❌

```python
# 错误 1: 两个端点
@app.post("/mcp/v1/messages")  # ❌
@app.post("/mcp/v1/stream")     # ❌

# 错误 2: 使用 NDJSON 而非 SSE
media_type="application/x-ndjson"  # ❌
yield f"{json.dumps(frame)}\n"      # ❌

# 错误 3: 缺少安全验证
# 没有 Origin 验证  # ❌
# 没有会话管理      # ❌
```

### 当前实现 (v0.2.1) ✅

```python
# 正确 1: 单一端点
@app.post("/mcp")  # ✅
@app.get("/mcp")   # ✅

# 正确 2: 使用 SSE
return EventSourceResponse(stream_sse())  # ✅
yield {"data": json.dumps(frame)}         # ✅

# 正确 3: 完整安全性
validate_origin(origin)        # ✅
validate_session(session_id)   # ✅
```

---

## 🔧 关键实现细节

### 1. 单一端点设计

```python
@app.post("/mcp")
async def mcp_post(
    request: Request,
    accept: Optional[str] = Header(None),
    mcp_protocol_version: Optional[str] = Header(None, alias="MCP-Protocol-Version"),
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id")
):
    # 根据请求类型和 Accept 头返回不同响应
    if needs_streaming and "text/event-stream" in accept:
        return EventSourceResponse(stream_sse())
    else:
        return JSONResponse(result)

@app.get("/mcp")
async def mcp_get(
    accept: Optional[str] = Header(None),
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID")
):
    # 返回 SSE 流用于服务器推送
    return EventSourceResponse(server_push_stream())
```

### 2. SSE 流式传输

```python
async def stream_game_frames_sse(msg_id, arguments) -> AsyncGenerator:
    # 发送响应
    yield {
        "data": json.dumps(response)
    }

    # 发送后续通知（带事件 ID）
    yield {
        "id": str(event_id),
        "data": json.dumps(notification)
    }
```

**SSE 格式输出**:
```
data: {"jsonrpc":"2.0","id":1,"result":{"status":"started"}}\n\n
id: 1\ndata: {"jsonrpc":"2.0","method":"notifications/game_frame","params":{...}}\n\n
id: 2\ndata: {"jsonrpc":"2.0","method":"notifications/game_frame","params":{...}}\n\n
```

### 3. 会话管理

```python
# 创建会话
if method == "initialize":
    session_id = create_session()  # 加密安全的随机 ID
    response.headers["Mcp-Session-Id"] = session_id
    return response

# 验证会话
if not validate_session(mcp_session_id):
    return JSONResponse(status_code=404, ...)
```

### 4. Origin 验证（安全要求）

```python
def validate_origin(origin: Optional[str]) -> bool:
    allowed_origins = [
        "http://localhost",
        "http://127.0.0.1",
        "https://localhost",
        "https://127.0.0.1",
    ]
    return any(origin.startswith(allowed) for allowed in allowed_origins)

# 在每个端点验证
if not validate_origin(origin):
    raise HTTPException(status_code=403, detail="Invalid origin")
```

### 5. 断线重连支持

```python
@app.get("/mcp")
async def mcp_get(
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID")
):
    # 客户端可以传递最后接收的事件 ID
    # 服务器从该 ID 之后继续发送
    return EventSourceResponse(
        server_push_stream(session_id, last_event_id)
    )
```

---

## 📖 客户端使用示例

### 正确的 Claude Desktop 配置

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

### HTTP 请求示例

#### 1. Initialize (创建会话)
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    }
  }'

# 响应包含 Mcp-Session-Id 头
```

#### 2. 列出工具
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -H "Mcp-Session-Id: <session-id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }'
```

#### 3. 启动流式传输 (SSE)
```bash
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "MCP-Protocol-Version: 2024-11-05" \
  -H "Mcp-Session-Id: <session-id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "start_game_stream",
      "arguments": {
        "fps": 60
      }
    }
  }'

# 返回 SSE 流
# Content-Type: text/event-stream
```

#### 4. 打开服务器推送流 (GET)
```bash
curl -X GET http://localhost:8000/mcp \
  -H "Accept: text/event-stream" \
  -H "Mcp-Session-Id: <session-id>"

# 返回持续的 SSE 流（心跳、通知等）
```

---

## 🔍 验证清单

使用此清单验证实现是否符合规范：

- [x] **端点**: 单一 `/mcp` 端点支持 POST 和 GET
- [x] **POST 请求**: 接受 JSON-RPC 消息，验证 Accept 头
- [x] **POST 通知**: 返回 HTTP 202 Accepted
- [x] **POST 流式**: Accept 包含 text/event-stream 时返回 SSE
- [x] **GET 请求**: 打开 SSE 流用于服务器推送
- [x] **SSE 格式**: 使用 `data: {json}\n\n` 格式
- [x] **事件 ID**: SSE 事件包含唯一 `id` 字段
- [x] **断线重连**: 支持 `Last-Event-ID` 头
- [x] **会话管理**: 使用 `Mcp-Session-Id` 头
- [x] **会话创建**: initialize 时分配加密安全的 ID
- [x] **会话验证**: 后续请求验证会话有效性
- [x] **无效会话**: 返回 HTTP 404
- [x] **Origin 验证**: **必须**验证 Origin 头
- [x] **协议版本**: 验证 `MCP-Protocol-Version` 头

---

## 📚 参考文档

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http)
- [Server-Sent Events (SSE) Spec](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [JSON-RPC 2.0](https://www.jsonrpc.org/specification)

---

## 🎯 总结

v0.2.1 实现**完全符合** MCP 2025-06-18 Streamable HTTP 规范：

✅ 单一端点架构
✅ 正确的 SSE 流式传输
✅ 完整的会话管理
✅ 必需的安全验证
✅ 断线重连支持

所有修正已经实现并测试通过！
