# 2 分钟演示脚本

## 演示前准备

推荐单端口启动：

```powershell
cd Try-Code
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

打开：

```text
http://127.0.0.1:4261
```

账号：

```text
analyst@example.com / Analyst@123
supervisor@example.com / Supervisor@123
```

## 0:00 - 0:20 项目定位

打开 `/public`，说：

> 这个项目不是普通聊天框，而是一个企业级客诉 Agent 工作台。它把自然语言目标、权限、Guardrail、工具调用、只读 SQL、SOP RAG、人工复核和审计追踪串在一起，用来演示 AI 应用落地时怎么控制风险、证据和成本。

## 0:20 - 0:40 今日作战台

登录 `analyst@example.com`。

在首页说明：

- 左侧是今日最高风险客诉和优先队列。
- 右侧是推荐演示路径。
- 顶部状态展示当前模型、数据源、RAG fallback 和本地会话状态。

重点说：

> 面试时我不从聊天框开始，而是先让业务用户看到今天该处理什么。

## 0:40 - 1:10 SQL + RAG 复合链路

进入“处理”，输入：

```text
质量问题退款超过100元的明细，按 SOP 是否需要主管复核
```

展示：

- 主回答结论
- SQL 预览
- 异常明细
- SOP 引用
- Agent 执行链路
- token/cost

讲法：

> 这个问题不能只靠 SQL，也不能只靠 RAG。系统先用只读 SQL 查异常明细，再把明细摘要交给 SOP RAG 判断是否需要升级。模型不会直接执行 SQL，也不能编造没有写在 SOP 里的规则。

## 1:10 - 1:30 Guardrail 与人工复核

输入：

```text
直接退款并改订单
```

展示：

- 高危操作已拦截
- 证据栏里的 Guardrail 状态
- review case

讲法：

> Agent 不应该直接退款、改单或导出用户。这里是后端 Guardrail 和工具边界一起拦截，并写入人工复核队列。

## 1:30 - 1:45 审计中心

进入“审计”。

展示：

- request_id
- route_mode
- tool_trace
- SQL
- latency
- retry
- token/cost

讲法：

> 每次 Agent 决策都能追踪。上线后排查误路由、成本异常、工具失败和安全拦截都要靠这类审计记录。

## 1:45 - 2:00 主管复核

退出，登录 `supervisor@example.com`。

进入“审批中心”，展示待复核单。

讲法：

> 高风险请求不会直接落到业务系统，而是进入 human-in-the-loop 流程。这个项目的重点是让 AI 在可控边界内工作。

## 收尾

> 当前项目是求职展示级原型，不是生产系统。但我已经覆盖了真实 AI 应用落地最关键的部分：工具边界、RAG 依据、只读 SQL、安全拦截、权限、人工复核、审计、token/cost 和自动化验收。

## 面试官可能追问的文件

| 问题 | 指向文件 |
| --- | --- |
| 后端主链路在哪里 | `app/runtime.py` |
| 前端工作台在哪里 | `frontend/src/views/HomeView.vue`、`frontend/src/views/CopilotView.vue` |
| Agent 执行链路在哪里 | `frontend/src/components/AgentFlow.vue` |
| 审计中心在哪里 | `frontend/src/views/AuditCenterView.vue` |
| 评测报告在哪里 | `frontend/src/views/EvalReportView.vue`、`eval/v2_eval_report.json` |
| RAG 知识库在哪里 | `knowledge_base/policies.json` |
| 评测集在哪里 | `eval/agent_eval_cases.json` |
| E2E 在哪里 | `tests/e2e/vue.spec.js`、`tests/e2e/acceptance.spec.js` |
| CI 在哪里 | `.github/workflows/ci.yml` |
