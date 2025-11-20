"""
MCP Streamable HTTP 客户端示例
演示如何连接到游戏串流服务器并接收实时帧
"""
import asyncio
import json
import base64
import logging
from typing import Optional
from pathlib import Path

import httpx
from PIL import Image
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MCPStreamingClient:
    """MCP 流式客户端"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()

    async def list_tools(self):
        """列出所有可用工具"""
        response = await self.client.post(
            f"{self.base_url}/mcp/v1/messages",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {}
            }
        )
        return response.json()

    async def call_tool(self, tool_name: str, arguments: dict):
        """调用工具（非流式）"""
        response = await self.client.post(
            f"{self.base_url}/mcp/v1/messages",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
        )
        return response.json()

    async def capture_single_frame(
        self,
        window_name: Optional[str] = None,
        save_path: Optional[str] = None
    ):
        """捕获单帧并可选保存"""
        logger.info(f"Capturing single frame from window: {window_name or 'screen'}")

        response = await self.call_tool(
            "capture_single_frame",
            {"window_name": window_name} if window_name else {}
        )

        result = response.get("result", {})
        content = result.get("content", [])

        for item in content:
            if item.get("type") == "image":
                image_data = base64.b64decode(item["data"])
                img = Image.open(io.BytesIO(image_data))

                if save_path:
                    img.save(save_path)
                    logger.info(f"Frame saved to {save_path}")
                else:
                    img.show()

                return img

        logger.error("No image in response")
        return None

    async def stream_game(
        self,
        window_name: Optional[str] = None,
        fps: int = 30,
        quality: int = 80,
        duration: Optional[int] = None,
        save_frames: bool = False,
        output_dir: str = "./frames"
    ):
        """
        流式接收游戏画面

        Args:
            window_name: 窗口名称
            fps: 帧率
            quality: 质量
            duration: 持续时间（秒），None = 无限
            save_frames: 是否保存帧
            output_dir: 保存目录
        """
        logger.info(f"Starting game stream: window={window_name}, fps={fps}")

        if save_frames:
            output_path = Path(output_dir)
            output_path.mkdir(exist_ok=True)
            logger.info(f"Frames will be saved to {output_path}")

        # 发起流式请求
        async with self.client.stream(
            "POST",
            f"{self.base_url}/mcp/v1/stream",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "start_game_stream",
                    "arguments": {
                        "window_name": window_name,
                        "fps": fps,
                        "quality": quality
                    }
                }
            }
        ) as response:
            if response.status_code != 200:
                logger.error(f"Stream request failed: {response.status_code}")
                return

            logger.info("Stream started successfully")

            frame_count = 0
            start_time = asyncio.get_event_loop().time()

            # 逐行读取 NDJSON 响应
            async for line in response.aiter_lines():
                if not line.strip():
                    continue

                try:
                    message = json.loads(line)

                    # 检查是否是错误响应
                    if "error" in message:
                        logger.error(f"Stream error: {message['error']}")
                        break

                    # 启动确认消息
                    if "result" in message and message["result"].get("status") == "started":
                        logger.info(f"Stream confirmed: {message['result']}")
                        continue

                    # 帧通知
                    if message.get("method") == "notifications/game_frame":
                        params = message["params"]
                        frame_number = params["frame_number"]
                        frame_data = base64.b64decode(params["data"])

                        frame_count += 1

                        # 每 30 帧显示一次进度
                        if frame_count % 30 == 0:
                            elapsed = asyncio.get_event_loop().time() - start_time
                            actual_fps = frame_count / elapsed if elapsed > 0 else 0
                            logger.info(
                                f"Received frame {frame_number} "
                                f"(total: {frame_count}, actual FPS: {actual_fps:.2f})"
                            )

                        # 保存帧（如果启用）
                        if save_frames:
                            img = Image.open(io.BytesIO(frame_data))
                            img.save(output_path / f"frame_{frame_number:06d}.jpg")

                        # 检查是否达到持续时间
                        if duration and (asyncio.get_event_loop().time() - start_time) >= duration:
                            logger.info(f"Duration limit reached, stopping stream")
                            break

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON: {e}")
                except Exception as e:
                    logger.error(f"Error processing frame: {e}")

            logger.info(f"Stream ended. Total frames received: {frame_count}")

    async def get_stats(self):
        """获取捕获统计"""
        response = await self.call_tool("get_capture_stats", {})
        return response


# ============ 使用示例 ============

async def example_single_frame():
    """示例：捕获单帧"""
    client = MCPStreamingClient()

    try:
        # 捕获单帧并保存
        await client.capture_single_frame(
            window_name=None,  # None = 捕获整个屏幕
            save_path="screenshot.jpg"
        )
    finally:
        await client.close()


async def example_stream_30_seconds():
    """示例：流式传输 30 秒"""
    client = MCPStreamingClient()

    try:
        # 流式传输 30 秒，保存所有帧
        await client.stream_game(
            window_name=None,  # 指定窗口名
            fps=30,
            quality=80,
            duration=30,
            save_frames=True,
            output_dir="./game_frames"
        )
    finally:
        await client.close()


async def example_continuous_stream():
    """示例：持续流式传输（直到手动停止）"""
    client = MCPStreamingClient()

    try:
        # 持续流式传输，不保存帧
        await client.stream_game(
            window_name=None,
            fps=60,
            quality=90,
            duration=None,  # 无限持续
            save_frames=False
        )
    except KeyboardInterrupt:
        logger.info("Stream interrupted by user")
    finally:
        await client.close()


async def example_list_tools():
    """示例：列出所有工具"""
    client = MCPStreamingClient()

    try:
        tools = await client.list_tools()
        print(json.dumps(tools, indent=2))
    finally:
        await client.close()


async def main():
    """主函数 - 选择要运行的示例"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python client_example.py <example>")
        print("Examples:")
        print("  single_frame      - 捕获单帧")
        print("  stream_30s        - 流式传输 30 秒")
        print("  stream_continuous - 持续流式传输")
        print("  list_tools        - 列出工具")
        return

    example = sys.argv[1]

    if example == "single_frame":
        await example_single_frame()
    elif example == "stream_30s":
        await example_stream_30_seconds()
    elif example == "stream_continuous":
        await example_continuous_stream()
    elif example == "list_tools":
        await example_list_tools()
    else:
        print(f"Unknown example: {example}")


if __name__ == "__main__":
    asyncio.run(main())
