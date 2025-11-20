# 部署指南

本指南详细说明如何部署 MCP 游戏串流服务器到各种环境。

---

## 📦 部署选项

### 选项 1: 本地开发环境

**适用场景**: 开发、测试、个人使用

#### 步骤
```bash
# 1. 安装依赖
uv sync

# 2. 启动服务器
uv run python server.py

# 3. 测试
curl http://localhost:8000/health
```

**优点**:
- ✅ 快速启动
- ✅ 易于调试
- ✅ 无需额外配置

**缺点**:
- ❌ 不适合生产环境
- ❌ 无自动重启
- ❌ 单进程

---

### 选项 2: 使用 systemd (Linux)

**注意**: 虽然服务器代码可以跨平台，但 `windows-capture` 仅支持 Windows。此选项仅适用于使用 fallback 捕获引擎的场景。

#### 创建 systemd 服务

1. 创建服务文件:
```bash
sudo nano /etc/systemd/system/mcp-game-streaming.service
```

2. 添加以下内容:
```ini
[Unit]
Description=MCP Game Streaming Server
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/screenshot-server
Environment="PATH=/home/your-username/.local/bin:$PATH"
ExecStart=/home/your-username/.local/bin/uv run python server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. 启动服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-game-streaming
sudo systemctl start mcp-game-streaming

# 查看状态
sudo systemctl status mcp-game-streaming

# 查看日志
sudo journalctl -u mcp-game-streaming -f
```

---

### 选项 3: 使用 Docker (跨平台)

**注意**: Windows 容器需要 Windows Server 或 Windows 10/11 Pro with Docker Desktop。

#### Dockerfile
创建 `Dockerfile`:

```dockerfile
FROM python:3.11-windowsservercore

WORKDIR /app

# 安装 uv
RUN pip install uv

# 复制项目文件
COPY . .

# 安装依赖
RUN uv sync

# 暴露端口
EXPOSE 8000

# 启动服务器
CMD ["uv", "run", "python", "server.py"]
```

#### 构建和运行
```bash
# 构建镜像
docker build -t mcp-game-streaming .

# 运行容器
docker run -d \
  --name game-streaming \
  -p 8000:8000 \
  -e CAPTURE_DEFAULT_FPS=60 \
  mcp-game-streaming

# 查看日志
docker logs -f game-streaming
```

---

### 选项 4: Windows 服务 (NSSM)

**适用场景**: Windows 生产环境

#### 使用 NSSM 创建 Windows 服务

1. 下载 [NSSM](https://nssm.cc/download)

2. 安装服务:
```cmd
nssm install MCPGameStreaming "C:\Python311\python.exe" "C:\path\to\screenshot-server\server.py"

nssm set MCPGameStreaming AppDirectory "C:\path\to\screenshot-server"
nssm set MCPGameStreaming DisplayName "MCP Game Streaming Server"
nssm set MCPGameStreaming Description "Real-time game streaming with DXGI and MCP"
nssm set MCPGameStreaming Start SERVICE_AUTO_START

# 设置环境变量
nssm set MCPGameStreaming AppEnvironmentExtra SERVER_PORT=8000 CAPTURE_DEFAULT_FPS=60

# 启动服务
nssm start MCPGameStreaming
```

3. 管理服务:
```cmd
# 查看状态
nssm status MCPGameStreaming

# 停止服务
nssm stop MCPGameStreaming

# 重启服务
nssm restart MCPGameStreaming

# 卸载服务
nssm remove MCPGameStreaming confirm
```

---

## 🌐 网络配置

### 局域网访问

#### 防火墙配置 (Windows)
```cmd
# 添加防火墙规则
netsh advfirewall firewall add rule ^
  name="MCP Game Streaming" ^
  dir=in ^
  action=allow ^
  protocol=TCP ^
  localport=8000

# 查看规则
netsh advfirewall firewall show rule name="MCP Game Streaming"
```

#### 测试访问
```bash
# 从其他机器测试
curl http://192.168.1.100:8000/health
```

### 互联网访问

#### 使用反向代理 (Nginx)

1. 安装 Nginx:
```bash
# Windows: 下载 https://nginx.org/en/download.html
# Linux: sudo apt install nginx
```

2. 配置 Nginx:
```nginx
# /etc/nginx/sites-available/mcp-game-streaming
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时配置（流式传输）
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

3. 启用配置:
```bash
sudo ln -s /etc/nginx/sites-available/mcp-game-streaming /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 使用 Cloudflare Tunnel

```bash
# 安装 cloudflared
# Windows: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

# 登录
cloudflared tunnel login

# 创建隧道
cloudflared tunnel create mcp-game-streaming

# 配置路由
cloudflared tunnel route dns mcp-game-streaming game-streaming.your-domain.com

# 启动隧道
cloudflared tunnel run mcp-game-streaming --url http://localhost:8000
```

---

## 🔒 安全配置

### 1. 启用 HTTPS

#### 使用 Let's Encrypt (with Nginx)
```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo certbot renew --dry-run
```

### 2. 添加身份验证

创建 `auth.py`:
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

API_KEY = "your-secret-api-key"

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    return credentials.credentials
```

在 `server.py` 中使用:
```python
from auth import verify_api_key

@app.post("/mcp/v1/stream")
async def mcp_stream(request: Request, api_key: str = Depends(verify_api_key)):
    # ... 现有代码
```

客户端使用:
```bash
curl -H "Authorization: Bearer your-secret-api-key" \
  http://localhost:8000/mcp/v1/messages
```

### 3. 限流

安装限流库:
```bash
pip install slowapi
```

添加到 `server.py`:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/mcp/v1/stream")
@limiter.limit("5/minute")  # 每分钟最多 5 个流
async def mcp_stream(request: Request):
    # ... 现有代码
```

---

## 📊 监控和日志

### 日志配置

创建 `logging_config.py`:
```python
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 文件处理器（自动轮转）
    file_handler = RotatingFileHandler(
        'mcp_server.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)

    # 格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
```

在 `server.py` 中使用:
```python
from logging_config import setup_logging

setup_logging()
```

### Prometheus 监控

安装依赖:
```bash
pip install prometheus-fastapi-instrumentator
```

添加到 `server.py`:
```python
from prometheus_fastapi_instrumentator import Instrumentator

instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app)
```

访问指标:
```bash
curl http://localhost:8000/metrics
```

---

## 🧪 性能优化

### 1. 使用多进程

```bash
# 使用 Gunicorn (Linux)
pip install gunicorn
gunicorn server:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# 使用 Uvicorn 多进程 (跨平台)
uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
```

### 2. 优化捕获参数

```bash
# 降低帧率和质量以节省 CPU/带宽
export CAPTURE_DEFAULT_FPS=30
export CAPTURE_QUALITY=70
```

### 3. 启用 HTTP/2

Uvicorn 本身不直接支持 HTTP/2，需要通过反向代理：

```nginx
# Nginx 配置
server {
    listen 443 ssl http2;
    # ... 其他配置
}
```

---

## 🚀 生产环境清单

- [ ] 使用 systemd/NSSM 设置自动启动
- [ ] 配置防火墙规则
- [ ] 启用 HTTPS
- [ ] 添加身份验证
- [ ] 配置限流
- [ ] 设置日志轮转
- [ ] 添加监控（Prometheus/Grafana）
- [ ] 配置自动重启
- [ ] 设置备份策略
- [ ] 测试故障恢复
- [ ] 文档化运维流程

---

## 📞 故障恢复

### 自动重启脚本 (Windows)

创建 `watchdog.ps1`:
```powershell
while ($true) {
    $process = Get-Process -Name python -ErrorAction SilentlyContinue |
               Where-Object { $_.CommandLine -like "*server.py*" }

    if (-not $process) {
        Write-Host "Server not running, starting..."
        Start-Process python -ArgumentList "server.py" -WorkingDirectory "C:\path\to\screenshot-server"
    }

    Start-Sleep -Seconds 30
}
```

运行:
```powershell
powershell -File watchdog.ps1
```

---

## 🎯 总结

选择合适的部署方式：

| 场景 | 推荐方式 | 难度 |
|-----|---------|------|
| **开发/测试** | 直接运行 | ⭐ |
| **个人使用** | NSSM 服务 | ⭐⭐ |
| **小型团队** | Nginx + Let's Encrypt | ⭐⭐⭐ |
| **生产环境** | Docker + 监控 + 身份验证 | ⭐⭐⭐⭐ |
| **全球访问** | Cloudflare Tunnel | ⭐⭐⭐⭐⭐ |

根据您的需求和技术栈选择最合适的部署方式！
