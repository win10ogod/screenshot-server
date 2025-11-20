"""
MCP 游戏串流服务器 (stdio 版本 - 用于 Claude Desktop)

这是一个简化版本，使用 stdio 传输以兼容 Claude Desktop
如果需要网络访问，请使用 server.py (HTTP 版本)
"""
import asyncio
import base64
import io
import logging
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ImageContent

# 尝试导入高性能捕获引擎
try:
    from capture_engine import capture_engine, WINDOWS_CAPTURE_AVAILABLE
except ImportError:
    WINDOWS_CAPTURE_AVAILABLE = False
    capture_engine = None

# 降级到 pyautogui
if not WINDOWS_CAPTURE_AVAILABLE:
    try:
        import pyautogui
        HAS_PYAUTOGUI = True
    except ImportError:
        HAS_PYAUTOGUI = False
        pyautogui = None

from config import config

# 配置日志（输出到 stderr 以避免干扰 stdio 通信）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # stderr
)
logger = logging.getLogger(__name__)

# 创建 MCP 服务器
mcp = FastMCP("mcp-game-streaming")


@mcp.tool()
async def capture_single_frame(window_name: str = None) -> ImageContent:
    """
    捕获单帧游戏画面

    Args:
        window_name: 窗口名称（如 "Elden Ring"），留空则捕获整个屏幕
    """
    logger.info(f"Capturing frame: window={window_name}")

    try:
        if WINDOWS_CAPTURE_AVAILABLE and capture_engine:
            # 使用高性能 DXGI 捕获
            await capture_engine.start_capture(window_name=window_name, fps=1)
            await asyncio.sleep(0.5)  # 等待捕获
            frame = await capture_engine.get_frame()
            await capture_engine.stop_capture()

            if frame:
                return Image(data=frame.data, format="jpeg").to_image_content()
            else:
                raise RuntimeError("Failed to capture frame with DXGI")

        elif HAS_PYAUTOGUI:
            # 降级到 pyautogui
            logger.warning("Using pyautogui fallback (lower performance)")
            buffer = io.BytesIO()
            screenshot = pyautogui.screenshot()
            screenshot.convert("RGB").save(
                buffer,
                format="JPEG",
                quality=config.capture.quality,
                optimize=True
            )
            return Image(data=buffer.getvalue(), format="jpeg").to_image_content()

        else:
            raise RuntimeError("No capture engine available")

    except Exception as e:
        logger.error(f"Capture error: {e}")
        raise


@mcp.tool()
async def start_continuous_capture(
    window_name: str = None,
    fps: int = 10,
    duration: int = 30
) -> str:
    """
    启动连续捕获（简化版）

    注意：由于 stdio 传输限制，这只会捕获多帧并返回统计信息
    如需真正的实时流式传输，请使用 HTTP 服务器版本

    Args:
        window_name: 窗口名称
        fps: 帧率 (1-30, stdio 限制)
        duration: 持续时间（秒）
    """
    logger.info(f"Starting continuous capture: window={window_name}, fps={fps}, duration={duration}")

    if not WINDOWS_CAPTURE_AVAILABLE:
        return "❌ Continuous capture requires windows-capture library. Please use capture_single_frame instead."

    try:
        # 启动捕获
        await capture_engine.start_capture(
            window_name=window_name,
            fps=min(fps, 30),  # stdio 限制
            quality=config.capture.quality
        )

        # 运行指定时间
        await asyncio.sleep(duration)

        # 获取统计
        stats = await capture_engine.get_stats()

        # 停止捕获
        await capture_engine.stop_capture()

        return f"""
✅ 连续捕获完成

窗口: {window_name or '整个屏幕'}
持续时间: {duration}秒
捕获帧数: {stats.get('frame_number', 0)}
实际 FPS: {stats.get('actual_fps', 0):.2f}
丢帧数: {stats.get('dropped_frames', 0)}
缓冲区大小: {stats.get('buffer_size', 0)}

💡 提示：如需实时流式传输，请使用 HTTP 服务器版本:
   uv run python server.py
   然后配置为 streamable-http 类型
        """.strip()

    except Exception as e:
        logger.error(f"Continuous capture error: {e}")
        return f"❌ 捕获失败: {str(e)}"


@mcp.tool()
async def get_capture_stats() -> str:
    """获取捕获引擎统计信息"""
    if not WINDOWS_CAPTURE_AVAILABLE:
        return "❌ Statistics require windows-capture library"

    stats = await capture_engine.get_stats()
    return f"""
📊 捕获引擎状态

状态: {stats.get('status', 'unknown')}
捕获帧数: {stats.get('frame_number', 0)}
实际 FPS: {stats.get('actual_fps', 0):.2f}
目标 FPS: {stats.get('target_fps', 0)}
丢帧数: {stats.get('dropped_frames', 0)}
缓冲区大小: {stats.get('buffer_size', 0)}
窗口: {stats.get('window_name', '未指定')}

引擎: {'DXGI (高性能)' if WINDOWS_CAPTURE_AVAILABLE else 'pyautogui (降级)'}
    """.strip()


@mcp.tool()
async def get_server_info() -> str:
    """获取服务器信息"""
    return f"""
🎮 MCP 游戏串流服务器

版本: 0.2.1
传输: stdio (Claude Desktop)
捕获引擎: {'DXGI (windows-capture)' if WINDOWS_CAPTURE_AVAILABLE else 'pyautogui (fallback)'}

⚠️  stdio 传输限制:
- 无法进行实时流式传输
- 每次请求独立（无状态）
- 建议使用 capture_single_frame

💡 如需 60 FPS 实时流式传输:
1. 启动 HTTP 服务器: uv run python server.py
2. 访问 http://localhost:8000
3. 使用支持 streamable-http 的客户端

可用工具:
✅ capture_single_frame - 捕获单帧（推荐）
✅ start_continuous_capture - 连续捕获（返回统计）
✅ get_capture_stats - 查看统计信息
✅ get_server_info - 服务器信息
    """.strip()


def run():
    """运行 stdio 服务器"""
    logger.info("Starting MCP Game Streaming Server (stdio mode)")
    logger.info(f"Capture engine: {'DXGI' if WINDOWS_CAPTURE_AVAILABLE else 'pyautogui'}")
    logger.info("For real-time streaming, use: uv run python server.py")

    # 使用 stdio 传输
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
