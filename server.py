"""
MCP Streamable HTTP 服务器 (符合 MCP 2025-06-18 规范)
使用 SSE (Server-Sent Events) 实现实时双向通信
"""
import asyncio
import json
import logging
import base64
import secrets
from typing import AsyncGenerator, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from capture_engine import capture_engine, FrameData
from config import config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MCP 协议版本
MCP_PROTOCOL_VERSION = "2024-11-05"

# 会话管理
sessions: Dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting MCP Game Streaming Server...")
    logger.info(f"Server config: {config.server.host}:{config.server.port}")
    logger.info(f"MCP Protocol Version: {MCP_PROTOCOL_VERSION}")

    yield

    # 清理
    logger.info("Shutting down server...")
    await capture_engine.stop_capture()


# 创建 FastAPI 应用
app = FastAPI(
    title="MCP Game Streaming Server",
    description="Real-time game streaming server using DXGI capture and MCP Streamable HTTP transport",
    version="0.2.1",
    lifespan=lifespan
)

# 注意：不使用全局 CORS，改用 Origin 验证
# 官方规范要求：Servers MUST validate the Origin header to prevent DNS rebinding attacks


def validate_origin(origin: Optional[str]) -> bool:
    """
    验证 Origin 头（安全要求）

    对于本地开发，允许 localhost 和 127.0.0.1
    对于生产环境，应该配置白名单
    """
    if not origin:
        return True  # 允许无 Origin 的请求（如 curl）

    allowed_origins = [
        "http://localhost",
        "http://127.0.0.1",
        "https://localhost",
        "https://127.0.0.1",
    ]

    # 检查是否匹配任何允许的源
    return any(origin.startswith(allowed) for allowed in allowed_origins)


def create_session() -> str:
    """创建新会话"""
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = {
        "created_at": asyncio.get_event_loop().time(),
        "stream_active": False
    }
    logger.info(f"Created session: {session_id}")
    return session_id


def validate_session(session_id: Optional[str]) -> bool:
    """验证会话是否存在"""
    return session_id in sessions if session_id else False


def create_jsonrpc_response(id: Any, result: Any = None, error: Optional[Dict] = None) -> Dict:
    """创建 JSON-RPC 2.0 响应"""
    response = {
        "jsonrpc": "2.0",
        "id": id
    }
    if error:
        response["error"] = error
    else:
        response["result"] = result
    return response


def create_jsonrpc_error(code: int, message: str, data: Any = None) -> Dict:
    """创建 JSON-RPC 错误对象"""
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return error


def format_sse_event(data: str, event_id: Optional[str] = None, event_type: Optional[str] = None) -> str:
    """
    格式化 SSE 事件

    SSE 格式:
    id: <id>
    event: <event_type>
    data: <data>
    <blank line>
    """
    lines = []

    if event_id:
        lines.append(f"id: {event_id}")

    if event_type:
        lines.append(f"event: {event_type}")

    # 确保数据不为空
    if data:
        lines.append(f"data: {data}")
    else:
        # 发送注释行保持连接
        return ": keepalive\n\n"

    # SSE 事件以双换行符结束
    return "\n".join(lines) + "\n\n"


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "MCP Game Streaming Server",
        "version": "0.2.1",
        "protocol": "streamable-http",
        "mcp_version": MCP_PROTOCOL_VERSION,
        "endpoint": "/mcp"
    }


@app.get("/health")
async def health():
    """健康检查"""
    stats = await capture_engine.get_stats()
    return {
        "status": "healthy",
        "capture_engine": stats,
        "active_sessions": len(sessions)
    }


@app.post("/mcp")
async def mcp_post(
    request: Request,
    accept: Optional[str] = Header(None),
    origin: Optional[str] = Header(None),
    mcp_protocol_version: Optional[str] = Header(None, alias="MCP-Protocol-Version"),
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id")
):
    """
    MCP Streamable HTTP 端点 (POST)

    符合 MCP 2025-06-18 规范：
    - 验证 Origin 头（安全要求）
    - 验证 MCP-Protocol-Version 头
    - 支持会话管理 (Mcp-Session-Id)
    - 根据请求类型返回 JSON 或 SSE 流
    """
    # 1. 验证 Origin（安全要求）
    if not validate_origin(origin):
        logger.warning(f"Rejected request from invalid origin: {origin}")
        raise HTTPException(status_code=403, detail="Invalid origin")

    # 2. 验证协议版本
    if mcp_protocol_version and mcp_protocol_version != MCP_PROTOCOL_VERSION:
        logger.warning(f"Protocol version mismatch: {mcp_protocol_version} != {MCP_PROTOCOL_VERSION}")
        # 注意：这里可以选择拒绝或接受

    # 3. 解析请求体
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
        return JSONResponse(
            create_jsonrpc_response(
                None,
                error=create_jsonrpc_error(-32700, "Parse error")
            ),
            status_code=400
        )

    logger.info(f"MCP POST: method={body.get('method')}, id={body.get('id')}")

    method = body.get("method")
    params = body.get("params", {})
    msg_id = body.get("id")

    # 4. 处理 initialize 请求（创建会话）
    if method == "initialize":
        session_id = create_session()
        result = await handle_initialize(params)

        response = JSONResponse(create_jsonrpc_response(msg_id, result))
        response.headers["Mcp-Session-Id"] = session_id
        return response

    # 5. 验证会话（initialize 之后的所有请求都需要会话）
    if not validate_session(mcp_session_id):
        logger.error(f"Invalid session: {mcp_session_id}")
        return JSONResponse(
            create_jsonrpc_response(
                msg_id,
                error=create_jsonrpc_error(-32001, "Invalid session")
            ),
            status_code=404
        )

    # 6. 处理通知和响应（返回 202 Accepted）
    if not msg_id:
        # 这是一个通知（notification），没有 id
        await handle_notification(method, params)
        return Response(status_code=202)

    # 7. 处理需要流式响应的请求
    if method == "tools/call" and params.get("name") == "start_game_stream":
        # 检查 Accept 头
        if accept and "text/event-stream" in accept:
            # 返回 SSE 流
            return StreamingResponse(
                stream_game_frames_sse(msg_id, params.get("arguments", {})),
                media_type="text/event-stream",
                headers={
                    "Mcp-Session-Id": mcp_session_id,
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no"
                }
            )
        else:
            # 客户端不接受 SSE，返回错误
            return JSONResponse(
                create_jsonrpc_response(
                    msg_id,
                    error=create_jsonrpc_error(
                        -32000,
                        "Streaming requires Accept: text/event-stream"
                    )
                )
            )

    # 8. 处理其他请求（返回 JSON）
    result = await handle_jsonrpc_request(method, params)
    return JSONResponse(
        create_jsonrpc_response(msg_id, result),
        headers={"Mcp-Session-Id": mcp_session_id}
    )


@app.get("/mcp")
async def mcp_get(
    accept: Optional[str] = Header(None),
    origin: Optional[str] = Header(None),
    mcp_session_id: Optional[str] = Header(None, alias="Mcp-Session-Id"),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID")
):
    """
    MCP Streamable HTTP 端点 (GET)

    打开 SSE 流以接收服务器推送的消息
    支持断线重连（Last-Event-ID）
    """
    # 1. 验证 Origin
    if not validate_origin(origin):
        raise HTTPException(status_code=403, detail="Invalid origin")

    # 2. 验证会话
    if not validate_session(mcp_session_id):
        raise HTTPException(status_code=404, detail="Invalid session")

    # 3. 检查 Accept 头
    if not accept or "text/event-stream" not in accept:
        raise HTTPException(
            status_code=405,
            detail="GET method requires Accept: text/event-stream"
        )

    # 4. 返回 SSE 流（用于服务器推送）
    return StreamingResponse(
        server_push_stream(mcp_session_id, last_event_id),
        media_type="text/event-stream",
        headers={
            "Mcp-Session-Id": mcp_session_id,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )


# ============ SSE 流生成器 ============

async def stream_game_frames_sse(msg_id: Any, arguments: Dict) -> AsyncGenerator[str, None]:
    """
    使用 SSE 格式流式传输游戏帧

    Yields SSE 格式化的字符串
    """
    window_name = arguments.get("window_name")
    fps = arguments.get("fps", config.capture.default_fps)
    quality = arguments.get("quality", config.capture.quality)
    monitor_index = arguments.get("monitor_index")

    logger.info(f"Starting SSE game stream: window={window_name}, fps={fps}")

    try:
        # 启动捕获
        success = await capture_engine.start_capture(
            window_name=window_name,
            monitor_index=monitor_index,
            fps=fps,
            quality=quality
        )

        if not success:
            error_response = create_jsonrpc_response(
                msg_id,
                error=create_jsonrpc_error(-32000, "Failed to start capture")
            )
            yield format_sse_event(json.dumps(error_response))
            return

        # 发送启动成功响应
        start_response = create_jsonrpc_response(
            msg_id,
            result={
                "status": "started",
                "window_name": window_name,
                "fps": fps,
                "quality": quality
            }
        )
        yield format_sse_event(json.dumps(start_response))

        # 流式传输帧（作为通知）
        frame_count = 0
        event_id = 0
        max_empty_polls = 10
        empty_polls = 0

        while True:
            frame = await capture_engine.get_frame()

            if frame is None:
                empty_polls += 1
                if empty_polls > max_empty_polls:
                    logger.warning("No frames available, stopping stream")
                    break
                await asyncio.sleep(0.01)
                continue

            empty_polls = 0
            frame_count += 1
            event_id += 1

            # 编码帧为 base64
            frame_b64 = base64.b64encode(frame.data).decode('utf-8')

            # 创建帧通知（JSON-RPC notification）
            # 使用 MCP 原生的 image 类型，而不是将 base64 放在 text 中
            frame_notification = {
                "jsonrpc": "2.0",
                "method": "notifications/game_frame",
                "params": {
                    "frame_number": frame.frame_number,
                    "timestamp": frame.timestamp,
                    "width": frame.width,
                    "height": frame.height,
                    "content": [
                        {
                            "type": "image",
                            "data": frame_b64,
                            "mimeType": f"image/{frame.format}"
                        }
                    ]
                }
            }

            # 格式化为 SSE 事件
            yield format_sse_event(
                json.dumps(frame_notification),
                event_id=str(event_id)
            )

            # 定期记录统计
            if frame_count % 100 == 0:
                stats = await capture_engine.get_stats()
                logger.info(f"SSE streamed {frame_count} frames, stats: {stats}")

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled by client")
    except Exception as e:
        logger.error(f"Error in SSE stream: {e}")
        error_response = create_jsonrpc_response(
            msg_id,
            error=create_jsonrpc_error(-32000, f"Stream error: {str(e)}")
        )
        yield format_sse_event(json.dumps(error_response))
    finally:
        await capture_engine.stop_capture()
        logger.info(f"SSE stream ended, total frames: {frame_count}")


async def server_push_stream(session_id: str, last_event_id: Optional[str]) -> AsyncGenerator[str, None]:
    """
    服务器推送流（GET 方法）

    用于服务器主动向客户端发送消息
    支持断线重连（从 last_event_id 开始）
    """
    logger.info(f"Opening server push stream for session {session_id}")

    if last_event_id:
        logger.info(f"Resuming from event ID: {last_event_id}")

    try:
        # 发送心跳以保持连接
        event_id = int(last_event_id) if last_event_id else 0

        while True:
            # 这里可以实现服务器推送逻辑
            # 例如：状态更新、警告、系统消息等

            await asyncio.sleep(30)  # 每 30 秒发送心跳

            event_id += 1
            heartbeat = {
                "jsonrpc": "2.0",
                "method": "notifications/heartbeat",
                "params": {
                    "timestamp": asyncio.get_event_loop().time()
                }
            }

            yield format_sse_event(
                json.dumps(heartbeat),
                event_id=str(event_id),
                event_type="heartbeat"
            )

    except asyncio.CancelledError:
        logger.info(f"Server push stream closed for session {session_id}")


# ============ MCP 处理器 ============

async def handle_initialize(params: Dict) -> Dict:
    """处理 initialize 请求"""
    logger.info(f"Initializing MCP session: {params}")

    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {
            "name": "mcp-game-streaming",
            "version": "0.2.1"
        },
        "capabilities": {
            "tools": {},
            "resources": {}
        }
    }


async def handle_notification(method: str, params: Dict):
    """处理通知（无需响应）"""
    logger.info(f"Received notification: {method}")

    if method == "notifications/cancelled":
        # 处理取消请求
        logger.info("Request cancelled by client")
        await capture_engine.stop_capture()


async def handle_jsonrpc_request(method: str, params: Dict) -> Dict:
    """处理 JSON-RPC 请求"""

    if method == "tools/list":
        return await handle_tools_list()

    elif method == "tools/call":
        return await handle_tool_call(params)

    elif method == "resources/list":
        return await handle_resources_list()

    elif method == "resources/read":
        return await handle_resource_read(params)

    else:
        raise ValueError(f"Unknown method: {method}")


async def handle_tools_list() -> Dict:
    """列出所有可用工具"""
    return {
        "tools": [
            {
                "name": "start_game_stream",
                "description": "启动游戏窗口的实时流式传输（需要 Accept: text/event-stream）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "window_name": {
                            "type": "string",
                            "description": "要捕获的窗口名称（如 'Elden Ring'），留空则捕获整个屏幕"
                        },
                        "fps": {
                            "type": "integer",
                            "description": f"目标帧率 (1-{config.capture.max_fps})",
                            "default": config.capture.default_fps
                        },
                        "quality": {
                            "type": "integer",
                            "description": "JPEG 质量 (1-100)",
                            "default": config.capture.quality
                        },
                        "monitor_index": {
                            "type": "integer",
                            "description": "显示器索引（None = 主显示器）"
                        }
                    }
                }
            },
            {
                "name": "stop_game_stream",
                "description": "停止当前的游戏流式传输",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "capture_single_frame",
                "description": "捕获单帧截图",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "window_name": {
                            "type": "string",
                            "description": "窗口名称"
                        }
                    }
                }
            },
            {
                "name": "get_capture_stats",
                "description": "获取捕获引擎统计信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    }


async def handle_tool_call(params: Dict) -> Dict:
    """处理工具调用"""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if tool_name == "stop_game_stream":
        await capture_engine.stop_capture()
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Game stream stopped successfully"
                }
            ]
        }

    elif tool_name == "capture_single_frame":
        window_name = arguments.get("window_name")
        await capture_engine.start_capture(window_name=window_name, fps=1)
        await asyncio.sleep(0.5)
        frame = await capture_engine.get_frame()
        await capture_engine.stop_capture()

        if frame:
            frame_b64 = base64.b64encode(frame.data).decode('utf-8')
            return {
                "content": [
                    {
                        "type": "image",
                        "data": frame_b64,
                        "mimeType": "image/jpeg"
                    }
                ]
            }
        else:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Failed to capture frame"
                    }
                ],
                "isError": True
            }

    elif tool_name == "get_capture_stats":
        stats = await capture_engine.get_stats()
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Capture Statistics:\n{json.dumps(stats, indent=2)}"
                }
            ]
        }

    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Unknown tool: {tool_name}"
                }
            ],
            "isError": True
        }


async def handle_resources_list() -> Dict:
    """列出所有可用资源"""
    return {
        "resources": [
            {
                "uri": "game://stream/stats",
                "name": "Capture Statistics",
                "description": "实时捕获统计信息",
                "mimeType": "application/json"
            }
        ]
    }


async def handle_resource_read(params: Dict) -> Dict:
    """读取资源"""
    uri = params.get("uri")

    if uri == "game://stream/stats":
        stats = await capture_engine.get_stats()
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(stats, indent=2)
                }
            ]
        }
    else:
        return {
            "contents": [],
            "isError": True
        }


def run_server():
    """启动服务器"""
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
