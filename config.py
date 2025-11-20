"""
配置管理模块
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class ServerConfig(BaseSettings):
    """服务器配置"""
    host: str = Field(default="0.0.0.0", description="服务器监听地址")
    port: int = Field(default=8000, description="服务器端口")

    class Config:
        env_prefix = "SERVER_"


class CaptureConfig(BaseSettings):
    """捕获配置"""
    default_fps: int = Field(default=30, description="默认帧率", ge=1, le=120)
    max_fps: int = Field(default=60, description="最大帧率", ge=1, le=120)
    quality: int = Field(default=80, description="JPEG质量", ge=1, le=100)
    enable_cursor: bool = Field(default=True, description="是否捕获鼠标光标")
    draw_border: bool = Field(default=False, description="是否绘制边框")

    class Config:
        env_prefix = "CAPTURE_"


class StreamConfig(BaseSettings):
    """流配置"""
    buffer_size: int = Field(default=30, description="帧缓冲区大小")
    max_clients: int = Field(default=5, description="最大客户端数量")
    timeout: int = Field(default=300, description="流超时时间（秒）")

    class Config:
        env_prefix = "STREAM_"


class AppConfig:
    """应用配置聚合"""
    def __init__(self):
        self.server = ServerConfig()
        self.capture = CaptureConfig()
        self.stream = StreamConfig()


# 全局配置实例
config = AppConfig()
