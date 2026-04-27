# Deployment Blueprints

这个目录放公开演示部署用的最小配置，不绑定具体生产环境。

## Render

`render.yaml` 使用 Dockerfile 部署单 Web 服务：

- 云平台通过 `PORT` 注入监听端口，Dockerfile 已支持 `${PORT:-8000}`。
- 默认 `AUTH_ENFORCED=true`。
- 默认 `REDIS_ENABLED=false`，避免演示环境强依赖外部 Redis。
- 默认 `DATA_QUERY_BACKEND=sqlite` 和 `USE_LANGCHAIN_RAG=false`，没有 API Key 也可以演示。
- 健康检查走 `/api/health`。

部署后建议直接打开：

```text
/public
/login
/
/copilot
/audit
/review
```

如果要接真实 Redis、MySQL、LLM Key，应在平台控制台用 secret/env var 配置，不要写入仓库。
