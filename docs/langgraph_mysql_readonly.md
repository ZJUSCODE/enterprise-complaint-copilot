# LangGraph 与 MySQL 只读查询说明

## LangGraph 执行流

项目保留原有 `Orchestrator.respond()` 主流程，同时新增一个轻量 LangGraph 版本：

```text
POST /api/langgraph/chat
```

这个接口复用现有权限、Guardrail、Router、Function Calling、RAG、SQL -> RAG、审计和人工复核逻辑，只是把执行过程显式建模为状态图。

当前节点：

```text
START
  -> permission_node
  -> guardrail_node
  -> router_node
  -> execute_node
  -> review_node
  -> audit_node
  -> END
```

典型分支：

- 权限不足：`permission_node -> audit_node`
- 高危请求：`permission_node -> guardrail_node -> review_node -> audit_node`
- 正常请求：`permission_node -> guardrail_node -> router_node -> execute_node -> audit_node`
- 正常请求但需要人工复核：`... -> execute_node -> review_node -> audit_node`

返回字段里会包含：

```json
{
  "graph_engine": "langgraph",
  "graph_trace": ["permission_node", "guardrail_node", "router_node", "execute_node", "audit_node"]
}
```

面试讲法：

> 原项目已经有手写 Agent 工作流。新增 LangGraph 版本后，Permission、Guardrail、Router、Tool/RAG 执行、人工复核和审计都被显式建模为节点和条件边，方便后续扩展 retry、fallback、人审和可视化。

## MySQL 只读查询

项目默认仍使用 SQLite，保证本地演示稳定：

```env
DATA_QUERY_BACKEND=sqlite
```

如果要切换到 MySQL，需要先把 Olist 样本加工成和 SQLite 相同的 `tickets` 宽表。

### 1. 准备 MySQL 数据库

示例 SQL：

```sql
CREATE DATABASE IF NOT EXISTS copilot_db DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'copilot_writer'@'%' IDENTIFIED BY 'writer_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER ON copilot_db.* TO 'copilot_writer'@'%';

CREATE USER IF NOT EXISTS 'copilot_readonly'@'%' IDENTIFIED BY 'readonly_password';
GRANT SELECT ON copilot_db.* TO 'copilot_readonly'@'%';
FLUSH PRIVILEGES;
```

生产里建议导入账号和查询账号分开：

- `MYSQL_USER` / `MYSQL_PASSWORD`：只用于导入 `tickets` 表。
- `MYSQL_READONLY_USER` / `MYSQL_READONLY_PASSWORD`：应用查询使用，只授予 `SELECT`。

### 2. 配置 `.env`

```env
DATA_QUERY_BACKEND=sqlite

MYSQL_USER=copilot_writer
MYSQL_PASSWORD=writer_password
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=copilot_db

MYSQL_READONLY_USER=copilot_readonly
MYSQL_READONLY_PASSWORD=readonly_password
MYSQL_READONLY_HOST=127.0.0.1
MYSQL_READONLY_PORT=3306
MYSQL_READONLY_DATABASE=copilot_db
```

先保持 `DATA_QUERY_BACKEND=sqlite`，等导入完成和只读账号验证后再切 MySQL。

### 3. 同步 tickets 宽表

```powershell
python scripts\sync_tickets_to_mysql.py --if-exists replace
```

脚本会读取：

```text
D:\A_产品\企业级智能客诉预警与数据洞察 Copilot\Try-Code\Olist
```

并生成 MySQL 表：

```text
tickets
```

字段与 Schema Explorer 中的 `tickets` 表保持一致。

### 4. 切换应用查询后端

导入成功后，把 `.env` 改成：

```env
DATA_QUERY_BACKEND=mysql
```

然后重启服务：

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 4261
```

访问：

```text
http://127.0.0.1:4261/api/overview
```

确认：

```json
{
  "data_query_backend": "mysql"
}
```

### 5. 为什么仍保留 SQLite

SQLite 是稳定演示后端，MySQL 是生产迁移适配。不要把求职演示做成强依赖 MySQL，否则现场容易因为数据库服务没启动、账号权限、字符集或端口问题翻车。

推荐口径：

> 本地演示默认用 SQLite，生产迁移可以切换到 MySQL 只读账号。两种后端共用同一套 `tickets` schema、SQL validator、参数化查询和 Schema Explorer，保证模型无法越权写库。

## Tool Registry / MCP

项目新增统一工具注册层，用于说明 Agent 平台里的工具管理能力：

```text
GET  /api/tools/registry
POST /api/tools/invoke
POST /api/mcp
```

`/api/tools/registry` 返回工具目录、input schema、所需权限、read-only 安全标记和 MCP-style 描述。`/api/tools/invoke` 复用后端 Pydantic 参数校验、RBAC 和工具执行逻辑。`/api/mcp` 提供 HTTP JSON-RPC 风格的 `tools/list` 与 `tools/call`，`scripts/mcp_stdio_server.py` 提供 stdio MCP server。

当前登记工具：

```text
get_user_risk
query_refund_cases
search_policy_docs
query_order_status
query_logistics_status
query_refund_eligibility
query_policy_by_market
```

面试讲法：

> 我没有把工具调用写死在一个 if/else 里，而是新增 Tool Registry。它能统一暴露工具 schema、权限、只读安全标记和调用轨迹，同时通过 HTTP JSON-RPC 和 stdio MCP server 暴露给外部 Agent/IDE 客户端。

## Redis 与长期 Memory 边界

短期 Redis runtime 已实现，用于：

- session memory
- rate limit
- 热点接口缓存
- eval 任务状态
- 事件队列

没有 Redis 时会降级到内存，保证本地演示稳定。

长期语义 Memory 仍保留在 Roadmap。原因是长期 Memory 不是简单缓存，还涉及 TTL、用户隔离、敏感字段最小化、Prompt Injection 持久化污染和审计。当前项目只保留短期 session memory 和多轮订单 follow-up，避免把半成品长期记忆包装成生产能力。
