"""
MCP stdio 到 HTTP 桥接器
允许 Claude Desktop 通过 stdio 连接到 HTTP 服务器
"""
import asyncio
import json
import sys
import httpx
from typing import Optional

# HTTP 服务器地址
HTTP_SERVER_URL = "http://localhost:8000/mcp"


class StdioToHttpBridge:
    """stdio 到 HTTP 的桥接器"""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self.client = httpx.AsyncClient(timeout=300.0)
        self.session_id: Optional[str] = None

    async def send_request(self, message: dict) -> dict:
        """发送 HTTP 请求"""
        headers = {
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2024-11-05"
        }

        # 如果有会话 ID，添加到头部
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        # 确定 Accept 头
        method = message.get("method")
        if method == "tools/call" and message.get("params", {}).get("name") == "start_game_stream":
            headers["Accept"] = "text/event-stream"
        else:
            headers["Accept"] = "application/json"

        try:
            response = await self.client.post(
                self.server_url,
                json=message,
                headers=headers
            )

            # 保存会话 ID（如果返回）
            if "mcp-session-id" in response.headers:
                self.session_id = response.headers["mcp-session-id"]
                sys.stderr.write(f"[Bridge] Session ID: {self.session_id}\n")

            # 处理 SSE 流式响应
            if response.headers.get("content-type") == "text/event-stream":
                return await self.handle_sse_stream(response)

            # 处理 JSON 响应
            return response.json()

        except Exception as e:
            sys.stderr.write(f"[Bridge] Error: {e}\n")
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Bridge error: {str(e)}"
                }
            }

    async def handle_sse_stream(self, response: httpx.Response) -> dict:
        """处理 SSE 流式响应（转换为单个响应）"""
        sys.stderr.write("[Bridge] Handling SSE stream...\n")

        # 注意：stdio 传输不支持流式，所以我们只返回第一个响应
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]  # 去掉 "data: " 前缀
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    continue

        return {
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": "No data in stream"}
        }

    async def run(self):
        """运行桥接器"""
        sys.stderr.write("[Bridge] Starting stdio to HTTP bridge\n")
        sys.stderr.write(f"[Bridge] Connecting to: {self.server_url}\n")

        try:
            while True:
                # 从 stdin 读取一行
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )

                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                sys.stderr.write(f"[Bridge] Received: {line[:100]}...\n")

                try:
                    # 解析 JSON-RPC 消息
                    message = json.loads(line)

                    # 发送到 HTTP 服务器
                    response = await self.send_request(message)

                    # 写入响应到 stdout
                    response_str = json.dumps(response)
                    sys.stdout.write(response_str + "\n")
                    sys.stdout.flush()

                    sys.stderr.write(f"[Bridge] Sent: {response_str[:100]}...\n")

                except json.JSONDecodeError as e:
                    sys.stderr.write(f"[Bridge] JSON decode error: {e}\n")

        except KeyboardInterrupt:
            sys.stderr.write("[Bridge] Interrupted\n")
        finally:
            await self.client.aclose()
            sys.stderr.write("[Bridge] Closed\n")


async def main():
    """主函数"""
    bridge = StdioToHttpBridge(HTTP_SERVER_URL)
    await bridge.run()


if __name__ == "__main__":
    asyncio.run(main())
