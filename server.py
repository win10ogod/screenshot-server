"""
MCP Streamable HTTP 服务器
实现 MCP 2025-06-18 规范的 Streamable HTTP 传输
"""
import asyncio
import json
import logging
import base64
from typing import AsyncGenerator, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
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


# 活动流会话管理
active_streams: Dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting MCP Game Streaming Server...")
    logger.info(f"Server config: {config.server.host}:{config.server.port}")
    logger.info(f"Capture config: FPS={config.capture.default_fps}, Quality={config.capture.quality}")

    yield

    # 清理
    logger.info("Shutting down server...")
    await capture_engine.stop_capture()


# 创建 FastAPI 应用
app = FastAPI(
    title="MCP Game Streaming Server",
    description="Real-time game streaming server using DXGI capture and MCP Streamable HTTP transport",
    version="0.2.0",
    lifespan=lifespan
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "MCP Game Streaming Server",
        "version": "0.2.0",
        "transport": "streamable-http",
        "endpoints": {
            "messages": "/mcp/v1/messages",
            "stream": "/mcp/v1/stream"
        }
    }


@app.get("/health")
async def health():
    """健康检查"""
    stats = await capture_engine.get_stats()
    return {
        "status": "healthy",
        "capture_engine": stats
    }


@app.post("/mcp/v1/messages")
async def mcp_messages(request: Request):
    """
    MCP 标准消息端点 (请求-响应模式)
    用于工具调用、资源获取等
    """
    try:
        body = await request.json()
        logger.info(f"Received MCP message: {body.get('method')}")

        method = body.get("method")
        params = body.get("params", {})
        msg_id = body.get("id")

        # 路由到对应的处理器
        if method == "tools/list":
            result = await handle_tools_list()
        elif method == "tools/call":
            result = await handle_tool_call(params)
        elif method == "resources/list":
            result = await handle_resources_list()
        elif method == "resources/read":
            result = await handle_resource_read(params)
        else:
            return JSONResponse(
                create_jsonrpc_response(
                    msg_id,
                    error=create_jsonrpc_error(-32601, f"Method not found: {method}")
                )
            )

        return JSONResponse(create_jsonrpc_response(msg_id, result))

    except Exception as e:
        logger.error(f"Error handling MCP message: {e}")
        return JSONResponse(
            create_jsonrpc_response(
                body.get("id"),
                error=create_jsonrpc_error(-32603, f"Internal error: {str(e)}")
            ),
            status_code=500
        )


@app.post("/mcp/v1/stream")
async def mcp_stream(request: Request):
    """
    MCP 流式端点 (双向流式传输)
    使用 NDJSON (Newline Delimited JSON) 格式
    用于实时游戏画面流式传输
    """
    try:
        body = await request.json()
        logger.info(f"Starting MCP stream: {body.get('method')}")

        method = body.get("method")
        params = body.get("params", {})
        msg_id = body.get("id")

        if method == "tools/call" and params.get("name") == "start_game_stream":
            # 启动流式传输
            return StreamingResponse(
                stream_game_frames(msg_id, params.get("arguments", {})),
                media_type="application/x-ndjson"
            )
        else:
            # 非流式请求，返回错误
            error_response = create_jsonrpc_response(
                msg_id,
                error=create_jsonrpc_error(
                    -32600,
                    "Stream endpoint only supports start_game_stream tool"
                )
            )
            return JSONResponse(error_response)

    except Exception as e:
        logger.error(f"Error in stream endpoint: {e}")
        error_response = create_jsonrpc_response(
            None,
            error=create_jsonrpc_error(-32603, f"Internal error: {str(e)}")
        )
        return JSONResponse(error_response, status_code=500)


async def stream_game_frames(msg_id: Any, arguments: Dict) -> AsyncGenerator[str, None]:
    """
    流式传输游戏帧
    生成 NDJSON 格式的帧数据
    """
    window_name = arguments.get("window_name")
    fps = arguments.get("fps", config.capture.default_fps)
    quality = arguments.get("quality", config.capture.quality)
    monitor_index = arguments.get("monitor_index")

    logger.info(f"Starting game stream: window={window_name}, fps={fps}")

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
            yield json.dumps(error_response) + "\n"
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
        yield json.dumps(start_response) + "\n"

        # 流式传输帧
        frame_count = 0
        max_empty_polls = 10
        empty_polls = 0

        while True:
            frame = await capture_engine.get_frame()

            if frame is None:
                # 缓冲区为空，短暂等待
                empty_polls += 1
                if empty_polls > max_empty_polls:
                    logger.warning("No frames available for too long, stopping stream")
                    break
                await asyncio.sleep(0.01)
                continue

            empty_polls = 0
            frame_count += 1

            # 编码帧为 base64
            frame_b64 = base64.b64encode(frame.data).decode('utf-8')

            # 创建帧消息 (使用 MCP notification 格式)
            frame_message = {
                "jsonrpc": "2.0",
                "method": "notifications/game_frame",
                "params": {
                    "frame_number": frame.frame_number,
                    "timestamp": frame.timestamp,
                    "format": frame.format,
                    "width": frame.width,
                    "height": frame.height,
                    "data": frame_b64
                }
            }

            yield json.dumps(frame_message) + "\n"

            # 每 100 帧记录一次
            if frame_count % 100 == 0:
                stats = await capture_engine.get_stats()
                logger.info(f"Streamed {frame_count} frames, stats: {stats}")

    except asyncio.CancelledError:
        logger.info("Stream cancelled by client")
    except Exception as e:
        logger.error(f"Error streaming frames: {e}")
        error_response = create_jsonrpc_response(
            msg_id,
            error=create_jsonrpc_error(-32000, f"Stream error: {str(e)}")
        )
        yield json.dumps(error_response) + "\n"
    finally:
        # 停止捕获
        await capture_engine.stop_capture()
        logger.info(f"Stream ended, total frames: {frame_count}")


# ============ MCP 处理器 ============

async def handle_tools_list() -> Dict:
    """列出所有可用工具"""
    return {
        "tools": [
            {
                "name": "start_game_stream",
                "description": "启动游戏窗口的实时流式传输（使用 /mcp/v1/stream 端点）",
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
                "name": "list_capturable_windows",
                "description": "列出所有可捕获的窗口",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
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
        # 临时启动捕获，获取一帧，然后停止
        window_name = arguments.get("window_name")
        await capture_engine.start_capture(window_name=window_name, fps=1)
        await asyncio.sleep(0.5)  # 等待捕获
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

    elif tool_name == "list_capturable_windows":
        windows = await capture_engine.list_windows()
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Available windows:\n" + "\n".join(f"- {w}" for w in windows)
                }
            ]
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
                "uri": "game://stream/live",
                "name": "Live Game Stream",
                "description": "实时游戏画面流",
                "mimeType": "application/x-ndjson"
            }
        ]
    }


async def handle_resource_read(params: Dict) -> Dict:
    """读取资源"""
    uri = params.get("uri")

    if uri == "game://stream/live":
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
