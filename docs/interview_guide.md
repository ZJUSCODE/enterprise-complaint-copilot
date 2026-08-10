# 企业级智能客诉 Copilot 面试讲解稿

这份文档给面试前 30 分钟快速复习用。更详细的小白学习版看 `docs/ai_agent_job_hunting_guide_for_beginner.md`。

## 30 秒介绍

> 我做了一个企业级智能客诉 Copilot，面向客服主管和运营分析场景。用户可以用自然语言查询异常退款、订单物流、售后 SOP 和用户风险。系统通过 Auto Router 判断该走 Function Calling、RAG，还是 SQL + RAG 复合链路；数据查询由 Tool Registry 统一登记的只读工具完成，政策回答由 LangChain RAG 返回引用来源和分数。为了避免 Agent 越权，我加了 JWT/RBAC、Guardrail、只读 SQL 校验、审计日志和人工复核队列。前端用 Vue3 做成目标优先的工作台，并补了 token/cost 追踪、可复现离线 eval、pytest、Playwright E2E、GitHub Actions CI、Docker 和 demo GIF。

## 2 分钟展开

这个项目解决的是客服主管每天处理客诉时的三个问题：

1. 不会 SQL 的业务人员也要查异常退款、订单物流和用户风险。
2. 售后政策回答必须有 SOP 引用，不能靠模型编。
3. Agent 不能越权退款、改单、导出用户，必须有权限、安全、审计和人工复核。

我的实现分成六层：

| 层 | 做什么 |
| --- | --- |
| Vue3 工作台 | 公开页、登录、今日作战台、处理页、审计中心、复核中心、右侧证据栏 |
| FastAPI API | 统一接收请求，处理身份、权限、SSE、任务和审计 |
| Router / LangGraph | 判断请求类型，把权限、安全、路由、执行、复核、审计串成流程 |
| Tool Registry / Function Calling Tools | 统一暴露工具 schema、权限、HTTP JSON-RPC 与 stdio MCP 调用、查询订单、物流、退款资格、异常退款明细、市场政策 |
| LangChain RAG | 从售后 SOP 中检索 citation、retrieval score、rerank score |
| Governance | Guardrail、RBAC、只读 SQL、review queue、audit center、token/cost |

重点讲这句话：

> 我不是让模型直接控制业务系统，而是把模型放在受控工具链里，让它负责理解目标和选择工具，真正的数据查询、安全边界、权限和审计都由后端控制。

## 一条请求的执行链路

示例：

```text
质量问题退款超过100元的明细，按 SOP 是否需要主管复核
```

链路：

1. 前端把用户目标发到 `/api/chat`。
2. 后端解析 JWT，得到用户角色。
3. Guardrail 检查是否有退款、改单、删除、导出用户等高危动作。
4. Auto Router 判断这是 `sql_rag_chain`。
5. 只读 SQL 工具查询质量问题且赔付超过 100 元的异常明细。
6. 后端把明细摘要交给 LangChain RAG 检索 SOP。
7. 如果 SOP 没有统一金额复核规则，系统不会编造。
8. 如果数据有高赔付异常且规则缺口明显，系统建议人工复核。
9. 返回结论、SQL preview、异常明细、SOP 引用、Tool Trace、token/cost。
10. 写入审计日志；如需复核，写入 review queue。

面试强调：

> 这个链路体现了“数据 + 规则 + 安全 + 复核”的业务闭环。

## 关键文件

| 文件 | 怎么讲 |
| --- | --- |
| `app/runtime.py` | 核心后端，包含 API、Router、Agent、RAG、SQL、安全、审计、复核 |
| `eval/agent_eval_cases.json` | route、tool、guardrail、多轮上下文评测集 |
| `eval/v2_eval_report.md` | 由离线运行生成的评测摘要报告 |
| `frontend/src/views/HomeView.vue` | 今日优先级页面，用户先看到最该处理的风险 |
| `frontend/src/views/CopilotView.vue` | 处理工作台，用户说目标，系统自动选择证据链路 |
| `frontend/src/components/EvidenceRail.vue` | 证据栏，展示 SOP、SQL、trace、token 和 cost |
| `frontend/src/components/AgentFlow.vue` | Agent 执行链路，展示权限、Guardrail、路由、工具、复核和审计 |
| `frontend/src/views/AuditCenterView.vue` | 审计中心，展示 request_id、route、tool trace、latency、token/cost |
| `frontend/src/views/EvalReportView.vue` | 评测报告页，展示 route/tool/RAG/Guardrail/memory 指标 |
| `frontend/src/views/ReviewCenterView.vue` | 主管复核中心 |
| `knowledge_base/policies.json` | 售后 SOP 知识库 |
| `tests/e2e/acceptance.spec.js` | FastAPI 单端口托管 Vue 生产包的 Playwright 验收 |
| `tests/e2e/vue.spec.js` | Vue3 主工作台 Playwright 端到端验收 |
| `.github/workflows/ci.yml` | CI 自动化检查 |
| `scripts/capture_demo.js` | 自动截图和 GIF |

## 如何现场演示

推荐单端口启动：

```powershell
python -m pip install -r requirements.txt
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

账号：

```text
analyst@example.com / Analyst@123
supervisor@example.com / Supervisor@123
```

演示顺序：

1. 打开 `/public`，说明这是受控 Agent 工作台。
2. 登录 analyst，展示今日作战台。
3. 点击“处理”，输入 SQL + RAG 示例问题。
4. 展示 SQL preview、异常明细、SOP 引用、Agent 执行链路、运行成本。
5. 输入“直接退款并改订单”，展示 Guardrail 拦截和复核单。
6. 进入审计中心，展示 request_id、route、tool trace、latency、token/cost。
7. 进入评测报告，展示由当前生成报告提供的 route/tool/RAG/Guardrail/memory 指标。
8. 切换 supervisor，进入复核中心处理 case。
9. 展示 `output/playwright/copilot-demo.gif`、`eval/v2_eval_report.md`，或运行 `npm run test:e2e`。

## 常见追问

### 这个项目为什么算 Agent？

算 AI Agent 应用原型，不是多智能体系统。它具备 Agent 的关键能力：意图路由、工具调用、参数校验、外部知识检索、短期 memory、安全拦截、人工复核和执行轨迹。

### 为什么不用模型直接写 SQL？

直接让模型生成任意 SQL 风险高，可能 SQL 注入、越权查询或执行写操作。我让模型只选择工具和参数，SQL 由后端受控生成，使用参数化查询和只读校验。

### Tool Registry / MCP 做了什么？

它把订单、物流、退款资格、市场政策、风险和 SOP 检索工具统一登记，返回工具名、描述、input schema、所需权限和 read-only 安全标记。`/api/mcp` 方便 HTTP 调试，`scripts/mcp_stdio_server.py` 支持 stdio MCP 的 `initialize`、`tools/list` 和 `tools/call`，用来说明后续可以接 Agent 平台工具市场。

### RAG 的价值是什么？

RAG 让政策回答有依据。售后 SOP 是企业内部知识，模型不能凭记忆回答。系统先检索 SOP，再组织答案，并把 citation、retrieval score、rerank score 展示出来。

### SQL + RAG 解决什么问题？

真实业务问题常常既要数据又要规则。比如“这些高赔付质量问题是否需要主管复核”，系统要先查明细，再结合 SOP 判断。单独 SQL 或单独 RAG 都不够。

### 如果 SOP 没写“超过 100 元统一复核”怎么办？

不能编造。系统应该说明当前 SOP 没有统一金额规则，再结合商品类别、是否拆封、用户风险、高赔付异常等因素建议人工复核。

### Guardrail 是 prompt 吗？

不只是 prompt。项目从四层做限制：工具层不暴露写接口，SQL 层只读校验，权限层用 RBAC，策略层用 Guardrail 拦截高危意图，并写审计和复核单。

### token/cost 为什么重要？

AI 应用上线后成本是关键指标。项目记录 token usage、embedding/prompt/completion 成本、estimated cost、retry 和 latency，方便后续优化 RAG、prompt 和工具链。

### Redis 不可用会怎样？

项目会降级到内存实现。Redis 用于 session memory、rate limit、缓存和任务状态，但本地演示不依赖 Redis。当前还支持简单多轮 follow-up，例如先查某个订单物流，再问“那退款资格呢？”。

### LangGraph 做了什么？

LangGraph 把 permission、guardrail、router、execute、review、audit 这些步骤显式编排成工作流节点，方便解释和扩展。

### 项目离生产还差什么？

真实企业数据只读账号、SSO、数据脱敏、更完整的监控告警、压测、线上审批系统、更严格的 RAG eval 和更细粒度权限。

## 简历写法

项目描述：

```text
企业级智能客诉预警与数据洞察 Copilot：面向客服主管和运营分析场景，构建一个可进行自然语言数据查询、售后 SOP 检索、高风险操作拦截、人工复核和审计追踪的 AI Copilot 原型。
```

推荐 bullet：

```text
- 基于 FastAPI 和 Vue3 构建企业客诉 Copilot 原型，支持登录、角色权限、自然语言查询、异常明细展示和人工复核流程。
- 设计 Auto Router，将用户问题分发到 Function Calling、LangChain RAG 或 SQL + RAG 复合链路，提升回答的结构化和可解释性。
- 建立 Tool Registry / MCP 工具层，将订单、物流、退款资格、市场政策、风险和 SOP 检索封装为统一只读工具，并通过 HTTP JSON-RPC 与 stdio MCP server 暴露，在工具调用前执行 RBAC 和参数校验。
- 实现 SQLite/MySQL 只读查询层与 SQL 安全校验，禁止模型直接执行任意 SQL，工具层通过参数化查询返回结构化指标、明细、SQL preview 和 Tool Trace。
- 构建 SOP RAG 与复合推理链路，基于 citation、retrieval score、rerank score 和明细摘要生成可追溯回答，并修正“规则未覆盖时不能编造统一复核条件”的输出逻辑。
- 建立 Agent 治理能力，包括 Guardrail、高危请求拦截、human-in-the-loop 复核队列、反馈事件、审计日志、trace_id、retry_count、token usage 和 cost breakdown。
- 搭建工程化验收体系，使用 pytest、Playwright 单端口生产验收、Vue 工作台 E2E、移动端 E2E、可复现离线 eval、GitHub Actions CI、Docker build 和自动截图/GIF 脚本覆盖核心演示路径。
```

## 最稳的收尾

面试最后可以这样收：

> 这个项目目前是求职展示级原型，不是完整生产系统。但我有意识地补了真实 AI 应用落地会关注的部分：工具调用边界、RAG 可追溯、只读 SQL、安全拦截、权限、审计、人工复核、成本追踪和自动化验收。我的重点不是做一个炫技聊天框，而是把 AI 能力放进一个可控的业务流程里。
