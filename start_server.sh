#!/bin/bash
# MCP Game Streaming Server 启动脚本 (Linux/macOS)

echo "========================================"
echo "  MCP Game Streaming Server"
echo "  Version 0.2.0"
echo "========================================"
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] Python 3 未安装"
    echo "请安装 Python 3.10 或更高版本"
    exit 1
fi

# 检查 uv
if ! command -v uv &> /dev/null; then
    echo "[警告] uv 未安装，尝试使用 pip 安装..."
    pip3 install uv
fi

# 同步依赖
echo "[1/3] 同步依赖..."
uv sync
if [ $? -ne 0 ]; then
    echo "[错误] 依赖安装失败"
    exit 1
fi

# 检查 windows-capture (降级模式)
echo "[2/3] 检查捕获引擎..."
python3 -c "import pyautogui; print('pyautogui: OK (fallback mode)')" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[警告] pyautogui 未安装，某些功能可能不可用"
    sleep 2
fi

# 启动服务器
echo "[3/3] 启动服务器..."
echo
echo "服务器地址: http://localhost:8000"
echo "健康检查: http://localhost:8000/health"
echo
echo "按 Ctrl+C 停止服务器"
echo "========================================"
echo

uv run python server.py
