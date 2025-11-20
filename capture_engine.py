"""
基于 windows-capture-python 的高效游戏捕获引擎
使用 DXGI Desktop Duplication API 实现低延迟、高帧率捕获
"""
import asyncio
import time
import io
import logging
from typing import Optional, Callable, List
from collections import deque
from dataclasses import dataclass
from enum import Enum

try:
    from windows_capture import WindowsCapture, Frame, InternalCaptureControl
    WINDOWS_CAPTURE_AVAILABLE = True
except ImportError:
    WINDOWS_CAPTURE_AVAILABLE = False
    logging.warning("windows-capture not available, will use fallback mode")

from PIL import Image
from config import config

logger = logging.getLogger(__name__)


class CaptureStatus(Enum):
    """捕获状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class FrameData:
    """帧数据"""
    frame_number: int
    timestamp: float
    data: bytes
    format: str = "jpeg"
    width: Optional[int] = None
    height: Optional[int] = None


class FrameBuffer:
    """帧缓冲区 - 线程安全的帧队列"""
    def __init__(self, max_size: int = 30):
        self.buffer: deque = deque(maxlen=max_size)
        self.lock = asyncio.Lock()
        self._dropped_frames = 0

    async def push(self, frame: FrameData) -> bool:
        """添加帧到缓冲区"""
        async with self.lock:
            if len(self.buffer) >= self.buffer.maxlen:
                self._dropped_frames += 1
                logger.debug(f"Frame buffer full, dropping frame {frame.frame_number}")
                return False
            self.buffer.append(frame)
            return True

    async def pop(self) -> Optional[FrameData]:
        """从缓冲区取出帧"""
        async with self.lock:
            return self.buffer.popleft() if self.buffer else None

    async def clear(self):
        """清空缓冲区"""
        async with self.lock:
            self.buffer.clear()
            self._dropped_frames = 0

    async def size(self) -> int:
        """获取当前缓冲区大小"""
        async with self.lock:
            return len(self.buffer)

    @property
    def dropped_frames(self) -> int:
        """获取丢帧数"""
        return self._dropped_frames


class StreamController:
    """流控制器 - 管理帧率和背压"""
    def __init__(self, target_fps: int = 30):
        self.target_fps = target_fps
        self.frame_time = 1.0 / target_fps
        self.last_frame_time = time.time()
        self._total_frames = 0
        self._start_time = time.time()

    async def wait_for_next_frame(self):
        """等待到下一帧时间"""
        current_time = time.time()
        elapsed = current_time - self.last_frame_time
        sleep_time = max(0, self.frame_time - elapsed)

        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

        self.last_frame_time = time.time()
        self._total_frames += 1

    @property
    def actual_fps(self) -> float:
        """计算实际FPS"""
        elapsed = time.time() - self._start_time
        return self._total_frames / elapsed if elapsed > 0 else 0

    def reset(self):
        """重置统计"""
        self._total_frames = 0
        self._start_time = time.time()
        self.last_frame_time = time.time()


class GameCaptureEngine:
    """游戏捕获引擎 - 使用 DXGI API"""

    def __init__(self):
        self.status = CaptureStatus.IDLE
        self.frame_buffer = FrameBuffer(max_size=config.stream.buffer_size)
        self.stream_controller: Optional[StreamController] = None
        self.capture: Optional[WindowsCapture] = None
        self._capture_control: Optional[InternalCaptureControl] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_missing_logged = False

        self._frame_number = 0
        self._capture_task: Optional[asyncio.Task] = None
        self._window_name: Optional[str] = None
        self._fps: int = config.capture.default_fps
        self._quality: int = config.capture.quality

        if not WINDOWS_CAPTURE_AVAILABLE:
            logger.error("Windows Capture library not available!")

    def _on_frame_arrived(self, frame: Frame, control: InternalCaptureControl):
        """帧到达回调 (在捕获线程中调用)"""
        try:
            if self.status != CaptureStatus.RUNNING:
                return

            # 保存控制句柄，便于在停止时优雅关闭捕获线程
            if control:
                self._capture_control = control

            if not self._loop or self._loop.is_closed():
                if not self._loop_missing_logged:
                    logger.error("Async event loop not available for frame processing")
                    self._loop_missing_logged = True
                return

            self._loop_missing_logged = False

            # 将帧处理移到主事件循环中执行
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._process_frame(frame))
            )
        except Exception as e:
            logger.error(f"Error in frame callback: {e}")

    async def _process_frame(self, frame: Frame):
        """处理单个帧"""
        try:
            width = frame.width
            height = frame.height

            # 获取帧数据（兼容不同 windows-capture 版本）
            if hasattr(frame, "get_buffer"):
                # 旧版 API
                buffer = frame.get_buffer()
                img = Image.frombytes('RGBA', (width, height), buffer, 'raw', 'BGRA')
            elif hasattr(frame, "frame_buffer"):
                # 新版 API 返回 numpy.ndarray（BGRA）
                np_frame = frame.frame_buffer
                try:
                    img = Image.fromarray(np_frame, mode='BGRA')
                except Exception:
                    img = Image.frombytes('RGBA', (width, height), np_frame.tobytes(), 'raw', 'BGRA')
            else:
                raise AttributeError("Frame does not expose buffer data")

            # 转换为 RGB 并压缩为 JPEG
            img_rgb = img.convert('RGB')
            output = io.BytesIO()
            img_rgb.save(output, format='JPEG', quality=self._quality, optimize=True)
            jpeg_data = output.getvalue()

            # 创建帧数据
            self._frame_number += 1
            frame_data = FrameData(
                frame_number=self._frame_number,
                timestamp=time.time(),
                data=jpeg_data,
                format="jpeg",
                width=width,
                height=height
            )

            # 添加到缓冲区
            await self.frame_buffer.push(frame_data)

            # 控制帧率
            if self.stream_controller:
                await self.stream_controller.wait_for_next_frame()

        except Exception as e:
            logger.error(f"Error processing frame: {e}")

    async def start_capture(
        self,
        window_name: Optional[str] = None,
        monitor_index: Optional[int] = None,
        fps: Optional[int] = None,
        quality: Optional[int] = None
    ) -> bool:
        """
        开始捕获

        Args:
            window_name: 窗口名称
            monitor_index: 显示器索引 (None = 主显示器)
            fps: 目标帧率
            quality: JPEG 质量 (1-100)
        """
        if not WINDOWS_CAPTURE_AVAILABLE:
            logger.error("Cannot start capture: windows-capture not available")
            return False

        if self.status == CaptureStatus.RUNNING:
            logger.warning("Capture already running")
            return False

        try:
            self._window_name = window_name
            self._fps = fps or config.capture.default_fps
            self._quality = quality or config.capture.quality

            # 记录当前事件循环，供回调线程使用
            self._loop = asyncio.get_running_loop()
            self._loop_missing_logged = False

            # 创建流控制器
            self.stream_controller = StreamController(target_fps=self._fps)

            # 清空缓冲区
            await self.frame_buffer.clear()
            self._frame_number = 0

            # 创建捕获实例
            self.capture = WindowsCapture(
                cursor_capture=config.capture.enable_cursor,
                draw_border=config.capture.draw_border,
                monitor_index=monitor_index,
                window_name=window_name
            )

            # 注册回调
            self.capture.frame_handler = self._on_frame_arrived
            self.capture.closed_handler = self._on_capture_closed

            # 在单独的线程中启动捕获
            self._capture_task = asyncio.create_task(self._run_capture())

            self.status = CaptureStatus.RUNNING
            logger.info(f"Started capture: window={window_name}, fps={self._fps}, quality={self._quality}")
            return True

        except Exception as e:
            logger.error(f"Failed to start capture: {e}")
            self.status = CaptureStatus.ERROR
            return False

    async def _run_capture(self):
        """运行捕获循环"""
        try:
            # 启动 DXGI 捕获 (阻塞调用，在后台线程运行)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self.capture.start
            )
        except Exception as e:
            logger.error(f"Capture loop error: {e}")
            self.status = CaptureStatus.ERROR

    def _on_capture_closed(self):
        """捕获会话结束回调"""
        logger.info("Capture closed")
        self.status = CaptureStatus.STOPPED
        self._loop = None
        self._loop_missing_logged = False
        self._capture_control = None

    async def stop_capture(self):
        """停止捕获"""
        if self.status != CaptureStatus.RUNNING:
            logger.warning("Capture not running")
            return

        try:
            self.status = CaptureStatus.STOPPED

            # 优先通过控制句柄请求捕获线程自行退出
            if self._capture_control:
                try:
                    self._capture_control.stop()
                except Exception as e:
                    logger.warning(f"Failed to stop capture via control handle: {e}")

            if self.capture:
                # windows-capture 不提供显式的 stop 方法
                # 通过取消任务来停止
                if self._capture_task:
                    self._capture_task.cancel()
                    try:
                        await self._capture_task
                    except asyncio.CancelledError:
                        pass

                self.capture = None
                # 留待关闭回调清理事件循环引用，避免回调线程记录缺失错误

            await self.frame_buffer.clear()
            self._loop = None
            self._loop_missing_logged = False
            self._capture_control = None
            logger.info("Capture stopped")

        except Exception as e:
            logger.error(f"Error stopping capture: {e}")

    async def get_frame(self) -> Optional[FrameData]:
        """获取一帧 (非阻塞)"""
        return await self.frame_buffer.pop()

    async def get_frame_with_timeout(self, timeout: float = 2.0) -> Optional[FrameData]:
        """等待获取一帧，超时返回 None"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = await self.frame_buffer.pop()
            if frame:
                return frame
            await asyncio.sleep(0.05)
        logger.warning("Timed out waiting for frame")
        return None

    async def capture_single_frame(
        self,
        window_name: Optional[str] = None,
        monitor_index: Optional[int] = None,
        quality: Optional[int] = None,
        timeout: float = 2.0,
    ) -> Optional[FrameData]:
        """一键捕获单帧，负责启动、等待和停止"""
        started = await self.start_capture(
            window_name=window_name,
            monitor_index=monitor_index,
            fps=1,
            quality=quality,
        )
        if not started:
            return None

        try:
            # 等待第一帧到达（带超时）
            frame = await self.get_frame_with_timeout(timeout)
            return frame
        finally:
            await self.stop_capture()

    async def get_stats(self) -> dict:
        """获取捕获统计"""
        return {
            "status": self.status.value,
            "frame_number": self._frame_number,
            "buffer_size": await self.frame_buffer.size(),
            "dropped_frames": self.frame_buffer.dropped_frames,
            "actual_fps": self.stream_controller.actual_fps if self.stream_controller else 0,
            "target_fps": self._fps,
            "window_name": self._window_name,
        }

    @staticmethod
    async def list_windows() -> List[str]:
        """
        列出所有可捕获的窗口
        注意: windows-capture 库可能不直接提供此功能
        这里提供一个占位实现
        """
        # TODO: 实现窗口枚举
        # 可能需要使用 Windows API (pywin32) 来枚举窗口
        return ["Not implemented yet - use Windows Task Manager to find window names"]


class FallbackCaptureEngine:
    """
    降级捕获引擎 - 当 windows-capture 不可用时使用 pyautogui
    仅用于开发/测试，不建议生产使用
    """
    def __init__(self):
        try:
            import pyautogui
            self.pyautogui = pyautogui
        except ImportError:
            self.pyautogui = None

        self.frame_buffer = FrameBuffer()
        self.status = CaptureStatus.IDLE
        self._capture_task: Optional[asyncio.Task] = None

    async def start_capture(self, **kwargs) -> bool:
        """使用 pyautogui 开始捕获"""
        if not self.pyautogui:
            logger.error("pyautogui not available")
            return False

        self.status = CaptureStatus.RUNNING
        self._capture_task = asyncio.create_task(self._capture_loop(kwargs.get('fps', 10)))
        return True

    async def _capture_loop(self, fps: int):
        """捕获循环"""
        frame_number = 0
        while self.status == CaptureStatus.RUNNING:
            try:
                screenshot = self.pyautogui.screenshot()
                buffer = io.BytesIO()
                screenshot.convert("RGB").save(buffer, format="JPEG", quality=60, optimize=True)

                frame_data = FrameData(
                    frame_number=frame_number,
                    timestamp=time.time(),
                    data=buffer.getvalue(),
                    format="jpeg"
                )

                await self.frame_buffer.push(frame_data)
                frame_number += 1

                await asyncio.sleep(1.0 / fps)
            except Exception as e:
                logger.error(f"Fallback capture error: {e}")

    async def stop_capture(self):
        """停止捕获"""
        self.status = CaptureStatus.STOPPED
        if self._capture_task:
            self._capture_task.cancel()

    async def get_frame(self) -> Optional[FrameData]:
        """获取帧"""
        return await self.frame_buffer.pop()

    async def capture_single_frame(
        self,
        window_name: Optional[str] = None,
        monitor_index: Optional[int] = None,
        quality: Optional[int] = None,
        timeout: float = 2.0,
    ) -> Optional[FrameData]:
        """简单的单帧捕获实现（不区分窗口/显示器）"""
        if not self.pyautogui:
            logger.error("pyautogui not available")
            return None

        buffer = io.BytesIO()
        screenshot = self.pyautogui.screenshot()
        screenshot.convert("RGB").save(
            buffer,
            format="JPEG",
            quality=quality or 60,
            optimize=True,
        )
        return FrameData(
            frame_number=0,
            timestamp=time.time(),
            data=buffer.getvalue(),
            format="jpeg",
        )

    async def get_stats(self) -> dict:
        """获取统计"""
        return {"status": self.status.value, "engine": "fallback"}


# 创建全局实例
if WINDOWS_CAPTURE_AVAILABLE:
    capture_engine = GameCaptureEngine()
else:
    logger.warning("Using fallback capture engine (pyautogui)")
    capture_engine = FallbackCaptureEngine()
