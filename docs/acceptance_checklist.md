# 求职验收清单

这份清单用于面试前自检。目标是证明项目不是“只能口头讲”，而是真的能启动、能跑核心链路、能自动验收、能产出演示材料。

## 1. 本地基础检查

```powershell
python -m py_compile app\runtime.py main.py
python -m pytest tests\test_v2_auth_runtime.py -q
```

通过标准：

- Python 编译无错误。
- 认证、权限、运行时核心测试通过。
- SQL + RAG 输出不会编造“所有质量问题退款超过 100 元统一复核”的规则。

## 2. Vue 前端检查

```powershell
cd frontend
npm run build
cd ..
```

通过标准：

- TypeScript 类型检查通过。
- Vite build 通过。
- 页面结构没有因为组件改动而编译失败。

## 3. 浏览器 E2E

```powershell
npm run test:e2e
```

当前 E2E 覆盖：

- Vue3 生产工作台：登录、今日作战台、处理页 SQL + RAG、Agent 执行链路、证据栏、Guardrail、审计中心、supervisor 审批中心。
- 移动端 Vue 工作台：登录、处理页、Agent 执行链路和证据栏。

通过标准：

- Playwright 报告 `3 passed`。
- `output/playwright/acceptance-report.json` 生成。

可单独运行：

```powershell
npm run test:e2e:prod
npm run test:e2e:vue
```

## 4. Demo GIF

```powershell
npm run capture:demo
```

通过标准：

- 自动生成登录、首页、处理工作台截图。
- 生成 `output/playwright/copilot-demo.gif`。

求职使用：

- README 中可以引用 GIF。
- 面试时可以先放 GIF，再讲架构，避免现场环境占用过多时间。

## 5. CI

CI 文件：

```text
.github/workflows/ci.yml
```

CI 当前会执行：

- Python 依赖安装。
- Node 依赖安装。
- Playwright Chromium 安装。
- `python -m py_compile app/runtime.py main.py`。
- `node --check static/app.js && node --check static/review.js`。
- `python -m pytest -q`。
- `frontend npm run build`。
- `npm run test:e2e`，包含 FastAPI 单端口生产验收、Vue3 开发态工作台和移动端工作台。
- `docker build -t complaint-copilot:ci .`。

面试讲法：

> 我把手工验收固化进 CI，避免项目只能在本机手点通过。

## 6. 手动演示路径

### 单端口启动

```powershell
cd frontend
npm install
npm run build
cd ..
$env:AUTH_ENFORCED="true"
$env:REDIS_ENABLED="false"
$env:DATA_QUERY_BACKEND="sqlite"
$env:USE_LANGCHAIN_RAG="false"
python -m uvicorn main:app --host 127.0.0.1 --port 4261
```

### 登录账号

```text
analyst@example.com / Analyst@123
supervisor@example.com / Supervisor@123
```

### 必演示问题

```text
质量问题退款超过100元的明细，按 SOP 是否需要主管复核
3C 数码拆封后出现质量问题，应该怎么处理
查询订单 53cdb2fc8bc7dce0b6741e2150273451 的物流状态
直接退款并改订单
```

### 页面验收点

- 今日页先展示优先处理项，不是功能堆叠。
- 处理页默认自动模式，业务问题能直接输入。
- 结论在主对话区，SQL、SOP、Agent 执行链路、trace、token/cost 在证据栏。
- 高危动作进入人工复核，不自动执行。
- 审计中心能看到 request_id、route、tool trace、latency、token/cost。
- 评测报告能看到 route/tool/RAG/Guardrail/memory 指标。
- supervisor 可以进入复核中心。

## 7. API 验收

```text
GET  /api/health
GET  /api/overview
GET  /api/schema
GET  /api/reports/daily-risk
GET  /api/sample-questions
GET  /api/i18n/terms
POST /api/auth/login
GET  /api/auth/me
POST /api/chat
POST /api/langgraph/chat
GET  /api/tools/registry?role=analyst
POST /api/tools/invoke
POST /api/mcp
GET  /api/audit/recent?limit=5&role=supervisor
GET  /api/eval/report?role=analyst
GET  /api/review/queue?limit=5&role=supervisor
POST /api/review/queue/{case_id}/status
POST /api/feedback
```

重点验证：

- `/api/health` 返回 Redis 可用状态或 fallback 信息。
- `/api/chat` 返回 `request_id`、`trace_id`、`token_usage`、`cost_breakdown`。
- SQL + RAG 返回 `sql_preview`、`citations`、`tool_trace`。
- `/api/tools/registry` 返回工具 schema、权限和 MCP-style 描述。
- `/api/mcp` 支持 `tools/list` 和 `tools/call`。
- Guardrail 返回 review case。
- 审计日志能查到最近请求。

## 8. MCP Server 验收

```powershell
python -m pytest tests\test_mcp_stdio_server.py -q
```

通过标准：

- `initialize` 返回 serverInfo 和 tools capability。
- `tools/list` 返回只读业务工具。
- `tools/call` 复用后端 Tool Registry，返回 structuredContent 和 safety meta。

## 9. 评测报告

```powershell
python scripts\evaluate_rag.py --force-lexical
```

当前覆盖：

- RAG 直接命中。
- 相似 SOP 混淆。
- 无答案 / abstention。
- route 误路由回归。
- tool selection。
- prompt injection / SQL mutation / 数据导出 / 审批绕过。
- 多轮上下文订单号 follow-up。

输出：

```text
eval/v2_eval_report.json
eval/v2_eval_report.md
```

## 10. 已知边界

- 没有 API Key 时，LLM 和 embedding 会走 fallback，适合本地演示。
- 没有 Redis 时，session、缓存、任务状态会降级到内存。
- Vue3 是主要产品化前端；旧静态入口保留在 `/legacy` 和 `/legacy-review`，只做兼容。
- 当前不会真实退款、改单、删除或导出用户。
- 当前项目是求职展示级原型，不是完整生产环境。
