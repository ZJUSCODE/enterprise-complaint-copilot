# Agent 治理与工具边界

这个项目的核心卖点不是“模型会回答”，而是 Agent 在受控边界内完成查询、检索、复核和审计。治理层覆盖权限、工具注册、只读 SQL、Guardrail、人工复核和可观测性。

## 权限模型

当前实现三类角色：

| 角色 | 权限 | 典型入口 |
| --- | --- | --- |
| `viewer` | `rag:read`、`overview:read` | 看概览、问 SOP 政策 |
| `analyst` | viewer 权限 + `data:query`、`risk:read`、`audit:read` | 查异常明细、查用户风险、看审计 |
| `supervisor` | analyst 权限 + `case:review` | 处理人工复核队列 |

前端路由和后端接口都做权限边界。后端仍是最终裁决点，不能依赖前端隐藏按钮来保证安全。

## 工具注册

工具通过 `ToolRegistry` 统一暴露，接口包括：

```text
GET  /api/tools/registry
POST /api/tools/invoke
POST /api/mcp
python scripts\mcp_stdio_server.py --role analyst
```

当前工具：

| 工具 | 能力 | 权限 | 安全边界 |
| --- | --- | --- | --- |
| `get_user_risk` | 查询用户风险评分和建议动作 | `risk:read` | 只读 |
| `query_refund_cases` | 查询异常退款明细 | `data:query` | 参数化 SQL + readonly validator |
| `search_policy_docs` | 检索 SOP 文档 | `rag:read` | 只读知识库 |
| `query_order_status` | 查询订单状态 | `data:query` | 只读 |
| `query_logistics_status` | 查询物流状态 | `data:query` | 只读 |
| `query_refund_eligibility` | 查询退款资格 | `data:query` | 只读 |
| `query_policy_by_market` | 查询市场政策 | `rag:read` | 只读 |

每个工具返回结构化结果，并进入 `tool_trace`，用于前端证据栏和审计中心回放。

## Guardrail

Guardrail 主要拦截：

- 退款、改单、删除、审批通过等写操作。
- `UPDATE`、`DELETE`、`DROP`、`PRAGMA` 等 SQL 变更或敏感操作。
- prompt injection，例如要求忽略规则、绕过系统约束。
- 全量用户导出、敏感数据外泄。

命中高危请求时，系统不会执行动作，只会生成安全回答和人工复核记录。

## 只读 SQL 边界

项目没有让模型直接执行任意 SQL。数据查询由工具层把参数转换为固定查询模板，并通过 `validate_readonly_sql` 检查：

- 仅允许 `SELECT` / `WITH`。
- 禁止 DDL、DML、连接外部库和危险 PRAGMA。
- 查询参数由后端组装，不拼接用户原始 SQL。
- 返回 SQL preview 用于解释，不作为用户可执行入口。

## Human-in-the-loop

高危请求或证据不足的请求进入 `HumanReviewQueue`。`supervisor` 可以在 `/review` 查看并标记通过或驳回。当前项目不会真实执行退款或改单，这一点在 README 和演示脚本里需要明确说明。

## 审计与可观测性

每次请求记录：

- `request_id` / `trace_id`
- 用户角色和请求模式
- Router 决策和原因
- Guardrail / Permission 是否拦截
- 工具轨迹、SQL preview、RAG citation
- latency、retry、token usage、estimated cost

面试时可以强调：Agent 上线后排查误路由、越权尝试、工具失败和成本异常，都需要这类审计数据。

## 生产化路线

后续可以增强：

1. 接入企业 SSO，把部门、角色、数据域放进 token claims。
2. 扩展到 tool-level + field-level permission。
3. 对用户 ID、订单 ID 等敏感字段做脱敏展示。
4. 审计日志接入 SIEM 或告警系统。
5. MCP 从 stdio 扩展到 streamable HTTP，并增加网关鉴权。
6. 长期 memory 写入前先过 Guardrail，并按租户、用户、角色隔离。
