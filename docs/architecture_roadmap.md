# 架构增强路线

这个项目当前已经具备应届生求职展示所需的 Agent 应用闭环：Vue 默认生产前端、Router、Function Calling、Tool Registry / MCP、RAG、只读 SQL、Guardrail、RBAC、审计日志、可复现离线 eval、mock tests、Agent 执行链路可视化、移动端 E2E 和单端口演示。下面记录当前增强项状态和后续生产化路线。

## P0 能力清单

| 优先级 | 能力项 | 技术标签 | 当前落地 |
| --- | --- | --- | --- |
| P0 | 真实启用 LangChain + ChromaDB RAG | RAG、LangChain、ChromaDB | 已接入 LangChain Embeddings / ChatOpenAI 与 ChromaDB 持久化检索；无向量库或 Key 时保留本地规则 fallback。 |
| P0 | 复合链路：SQL -> RAG | Agent、Function Call、Router | 已新增 `sql_rag_chain`，Router 可把“数据查询 + SOP 判断”类问题串到只读 SQL 后再走 RAG。 |
| P0 | 人工复核队列 | Agent、Guardrail、Human-in-the-loop | 已新增 `human_review_queue`，Guardrail 高危请求和高赔付复核场景会进入主管可查看的待处理队列。 |
| P0 | Tool Registry / MCP | Agent 平台、MCP、工具管理 | 已新增 `/api/tools/registry`、`/api/tools/invoke`、`/api/mcp` 和 `scripts/mcp_stdio_server.py`，统一暴露只读业务工具、schema、权限和调用轨迹。 |
| P0 | Vue 默认生产前端 | Vue3、Pinia、Vite、FastAPI static hosting | FastAPI 默认托管 `frontend/dist`，`/`、`/copilot`、`/audit`、`/review` 均走 Vue；旧静态页保留为 `/legacy`。 |
| P0 | 首页工作台化 | 产品化前端、信息架构 | 首页已改成“今日作战台”，优先展示高风险队列、运行状态和 demo runbook，去掉通用 hero 感。 |

## P2 增强项状态

| 能力项 | 当前状态 | 说明 |
| --- | --- | --- |
| Dockerfile | 已补齐 | 可构建本地演示镜像，容器启动 FastAPI 服务，数据库可由 Olist CSV 自动生成。 |
| GitHub Actions CI | 已补齐 | CI 执行 Python/JS 语法检查、`pytest`、Playwright 浏览器验收和 Docker build。 |
| 每日异常播报 mock | 已补齐 | `/api/reports/daily-risk` 和 `scripts/generate_daily_report.py` 生成可发送内容，不调用真实飞书/企微 webhook。 |
| Agent 执行链路可视化 | 已补齐 | `AgentFlow.vue` 在证据栏展示权限、Guardrail、Router、工具、复核和审计节点。 |
| 审计日志中心 | 已补齐 | `/audit` 读取最近审计事件，展示 request_id、route、tool trace、latency、token 和成本。 |
| 审批中心模拟页 | 已补齐 | `/review` 读取人工复核队列，支持主管把高危请求标记为已通过或已驳回，不执行真实退款。 |
| 公开项目页 | 已补齐 | `/public` 用于作品集或投递链接，清楚说明项目定位、能力边界和可演示路径。 |
| 线上部署蓝图 | 已补齐 | Dockerfile 支持云平台 `PORT`，`deploy/render.yaml` 提供公开演示部署配置。 |
| LangGraph 执行流 | 已补齐 | `/api/langgraph/chat` 将 Permission、Guardrail、Router、执行、人工复核和审计建模为状态图。 |
| MySQL 只读查询 | 已补齐轻量版 | 默认仍用 SQLite；可用 `scripts/sync_tickets_to_mysql.py` 同步 Olist 生成的 `tickets` 表，再切换 `DATA_QUERY_BACKEND=mysql`。 |
| Redis 运行层 | 已补齐 | session memory、rate limit、热点缓存、任务状态和事件队列优先走 Redis，不可用时降级内存。 |
| 长期语义 Memory | Roadmap | 暂不实现，避免引入持久化污染、权限隔离和敏感字段最小化的半成品。 |

## LangGraph 状态图

当前代码里有两条执行入口：主路径 `Orchestrator.respond()` 保持稳定演示，`/api/langgraph/chat` 用 LangGraph 把同一套能力显式建模为状态图。

```text
START
  -> Guardrail / Permission Check
  -> Auto Router
      -> Function Calling Agent
          -> Tool Validation
          -> Readonly SQL / Risk / Policy Tool
          -> Synthesis
      -> SQL -> RAG Chain
          -> Readonly SQL Summary
          -> Policy RAG with SQL Context
          -> Human Review Queue if needed
      -> RAG
          -> Chroma Vector Search or Lexical Fallback
          -> Citation Synthesis
  -> Audit Log
  -> END
```

面试时可以这样说：

> 当前项目保留了稳定的普通 API 编排，同时提供 LangGraph 入口。Permission、Guardrail、Router、Tool/RAG 执行、人工复核和 Audit 都能作为节点输出 `graph_trace`，方便解释 Agent 工作流，也方便后续扩展 retry、fallback 和审批分支。

建议接入时机：

- 需要多轮审批 / 人工复核。
- 需要 retry / fallback / 分支可视化。
- 需要更复杂的多工具依赖。

当前不把所有流量强制切到 LangGraph 的原因：

- 主 API 路径更稳定，适合面试现场演示和 E2E。
- LangGraph 入口用于展示工作流建模能力，避免为了框架牺牲可调试性。
- 两条路径复用同一套工具、RAG、权限、审计和复核逻辑。

## Tool Registry / MCP

当前新增轻量工具注册层：

```text
GET  /api/tools/registry
POST /api/tools/invoke
POST /api/mcp
python scripts/mcp_stdio_server.py --role analyst
```

覆盖工具：

- `get_user_risk`
- `query_refund_cases`
- `search_policy_docs`
- `query_order_status`
- `query_logistics_status`
- `query_refund_eligibility`
- `query_policy_by_market`

面试口径：

> Tool Registry 把原来散落在 Function Calling Agent 里的业务工具统一登记，暴露工具名、描述、input schema、所需权限和 read-only 安全标记。`/api/mcp` 方便 HTTP 调试，`scripts/mcp_stdio_server.py` 提供 stdio MCP server，支持 `initialize`、`tools/list` 和 `tools/call`，用于说明我理解 Agent 平台里的工具管理、权限和调用边界。

## Redis Session Memory

当前短期 memory 已支持 Redis + 内存 fallback：

```text
Redis available: session:{session_id}:messages with TTL
Redis unavailable: in-process dict fallback
```

当前用途：

- 保存最近多轮消息。
- 支持订单号 follow-up，例如先查物流，再问“那退款资格呢？”。
- Redis 不可用时继续本地演示。

面试口径：

> 当前 memory 是短期会话上下文，优先走 Redis，设置 TTL；没有 Redis 时降级到进程内字典，保证本地演示稳定。长期语义 Memory 暂不做，因为它涉及污染防护、用户隔离和敏感字段最小化。

建议接口：

```python
class MemoryStore:
    def recent_messages(session_id: str, limit: int) -> list[dict]: ...
    def append(session_id: str, role: str, content: str) -> None: ...
```

这样本地内存和 Redis 可以实现同一个接口。

### 长期语义 Memory Roadmap

短期 Redis memory 已实现。长期语义 Memory 暂不做，因为它不只是换存储，还涉及写入准入、权限隔离和污染防护。后续如果演进到生产形态，建议按下面的边界实现：

1. 写入前先过 Guardrail，只记录正常查询、已授权动作和人工复核结论。
2. Redis key 带租户、用户和 session 维度，避免不同角色共享上下文。
3. 设置 TTL，例如会话消息 24 小时、复核摘要 7 天。
4. 对用户 ID、订单 ID 等字段做最小化存储，只保留回答需要的摘要。
5. Memory 写入和读取都进入审计日志，方便追踪上下文来源。

推荐接口仍然保持 `MemoryStore` 抽象：

```python
class MemoryStore:
    def recent_messages(self, session_id: str, limit: int) -> list[dict[str, str]]: ...
    def append(self, session_id: str, role: str, content: str) -> None: ...
```

这样当前的 `SessionMemoryStore` 和后续的 `RedisMemoryStore` 可以平滑替换。

## 更完整的权限系统

当前已实现轻量 RBAC：

- `viewer`
- `analyst`
- `supervisor`

生产版本可以增强为：

1. 接入企业 SSO / JWT。
2. 从 token 中解析用户、部门、角色。
3. 对每个 tool 定义最小权限。
4. 对敏感字段做脱敏。
5. 对高风险请求进入人工审批队列。
6. 审计日志接入 SIEM / 告警系统。

当前版本适合面试展示，因为它已经证明了三点：

- Agent 工具调用不是所有角色都能用。
- 高风险操作被 Guardrail 拦截。
- 所有请求都能审计追踪。

## 最推荐继续做的增强

如果继续投入，优先级是：

1. MCP：stdio server 已补齐；后续可继续扩展 streamable HTTP、OAuth/网关鉴权和工具级灰度发布。
2. 长期语义 Memory：带 TTL、角色隔离、敏感字段最小化和 Guardrail-filtered writes。
3. 权限：从角色级扩展到 tool-level + field-level permission。
4. 通知接入：在 mock 日报基础上接真实飞书/企微 webhook、失败重试和发送审计。
