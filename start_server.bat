@echo off
REM MCP Game Streaming Server 启动脚本 (Windows)

echo ========================================
echo   MCP Game Streaming Server
echo   Version 0.2.0
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] Python 未安装或未添加到 PATH
    echo 请从 https://www.python.org/ 下载并安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查 uv
uv --version >nul 2>&1
if errorlevel 1 (
    echo [警告] uv 未安装，尝试使用 pip 安装...
    pip install uv
)

REM 同步依赖
echo [1/3] 同步依赖...
uv sync
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM 检查 windows-capture
echo [2/3] 检查 windows-capture...
python -c "import windows_capture; print('windows-capture: OK')" 2>nul
if errorlevel 1 (
    echo [警告] windows-capture 未正确安装，将使用降级模式
    echo 性能将会降低，建议重新安装: pip install windows-capture --no-cache-dir
    timeout /t 3 >nul
)

REM 启动服务器
echo [3/3] 启动服务器...
echo.
echo 服务器地址: http://localhost:8000
echo 健康检查: http://localhost:8000/health
echo.
echo 按 Ctrl+C 停止服务器
echo ========================================
echo.

uv run python server.py

pause
