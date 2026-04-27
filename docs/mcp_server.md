# MCP Server

项目现在同时提供两种工具暴露方式：

- `/api/mcp`：HTTP JSON-RPC 兼容入口，方便前端、接口测试和普通 HTTP 客户端调用。
- `scripts/mcp_stdio_server.py`：stdio MCP server，面向支持 MCP 的 Agent/IDE 客户端。

## 启动

```powershell
python scripts\mcp_stdio_server.py --role analyst
```

可选角色：

```text
viewer
analyst
supervisor
```

默认角色来自 `MCP_ROLE` 环境变量，未设置时为 `analyst`。

客户端配置示例：

```text
mcp.example.json
```

## 支持的方法

```text
initialize
notifications/initialized
ping
tools/list
tools/call
```

所有工具仍然复用后端 `ToolRegistry`，因此会经过同一套 RBAC、参数校验、只读 SQL 边界和审计友好的 tool trace。

## 可暴露工具

```text
get_user_risk
query_refund_cases
search_policy_docs
query_order_status
query_logistics_status
query_refund_eligibility
query_policy_by_market
```

## 本地自检

```powershell
python -m pytest tests\test_mcp_stdio_server.py -q
```

面试讲法：

> 原来项目只有 HTTP JSON-RPC 入口，用于说明工具 schema、权限和只读边界。现在我补了 stdio MCP server，支持 MCP 生命周期初始化和 tools/list、tools/call，并且复用同一套 Tool Registry，所以不是另写一套 demo 工具，而是把现有受控工具层标准化暴露出去。
