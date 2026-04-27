# 部署与 CI 说明

## 本地单端口运行

先构建 Vue 前端：

```powershell
cd frontend
npm install
npm run build
cd ..
```

启动 FastAPI。FastAPI 会服务 `frontend/dist`，并对 Vue Router 做 history fallback：

```powershell
$env:AUTH_ENFORCED="true"
$env:REDIS_ENABLED="false"
$env:DATA_QUERY_BACKEND="sqlite"
$env:USE_LANGCHAIN_RAG="false"
python -m uvicorn main:app --host 127.0.0.1 --port 4261
```

访问：

```text
http://127.0.0.1:4261/public
http://127.0.0.1:4261/login
http://127.0.0.1:4261
http://127.0.0.1:4261/copilot
http://127.0.0.1:4261/audit
http://127.0.0.1:4261/eval
http://127.0.0.1:4261/review
```

旧静态演示入口保留：

```text
http://127.0.0.1:4261/legacy
http://127.0.0.1:4261/legacy-review
```

## 开发模式

脚本默认使用前端 `4261`、后端 `8029`。如果端口被占用，会寻找后续可用端口并打印真实地址：

```powershell
node scripts\start_real_dev.js
```

## Docker 本地运行

Dockerfile 会先构建 Vue，再把 `frontend/dist` 复制到 Python 镜像里。

```powershell
docker build -t complaint-copilot .
docker run --rm -p 4261:8000 complaint-copilot
```

访问：

```text
http://127.0.0.1:4261
```

Dockerfile 支持云平台注入端口，例如：

```text
PORT=10000
```

Docker Compose：

```powershell
docker compose config
docker compose up --build
```

Compose 默认暴露：

```text
FastAPI: http://127.0.0.1:8000
Nginx:   http://127.0.0.1:8080
Redis:   127.0.0.1:6379
```

说明：如果本机 Docker Desktop 未启动，`docker build` 会因为连接 Docker daemon 失败而不可验证，这不是代码构建错误。

## 线上部署蓝图

Render 示例配置：

```text
deploy/render.yaml
```

它使用 Dockerfile 单服务部署，默认开启登录、关闭 Redis 强依赖、使用 SQLite/fallback，适合公开演示页和面试投递链接。真实生产接入 Redis、MySQL、LLM Key 时，应在平台控制台配置 secret/env var，不写入仓库。

## GitHub Actions

`.github/workflows/ci.yml` 包含两个 job：

- `test`：安装 Python 和 Node 依赖，执行 Python/JS 语法检查、`pytest`、Vue build、Playwright Chromium 验收测试。
- `docker`：执行 `docker build`，验证容器镜像可构建。

CI 不需要真实 LLM Key。未配置 API Key 时，系统会走本地规则、只读 SQL 和 RAG fallback。

## MCP Server

stdio MCP server：

```powershell
python scripts\mcp_stdio_server.py --role analyst
```

自检：

```powershell
python -m pytest tests\test_mcp_stdio_server.py -q
```

HTTP 调试入口仍保留：

```text
POST http://127.0.0.1:4261/api/mcp
```

## 每日异常播报 Mock

接口：

```text
GET /api/reports/daily-risk
```

脚本：

```powershell
python scripts/generate_daily_report.py --format markdown
python scripts/generate_daily_report.py --format json
```

当前只生成可发送内容，不调用真实飞书或企业微信 webhook。
