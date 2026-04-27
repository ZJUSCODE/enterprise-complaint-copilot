# AI Agent 求职小白训练手册

这份文档给你自己用。目标不是把项目包装得很夸张，而是让你能做到三件事：

1. 面试官问“你这个项目做了什么”，你能在 30 秒、2 分钟、5 分钟三个长度里讲清楚。
2. 面试官问 RAG、Function Calling、LangGraph、SQL 安全、权限、E2E、CI、GIF、成本追踪，你能用人话解释。
3. 你知道哪些地方已经实现，哪些地方只是原型边界，不会在面试里过度承诺。

你是小白也没关系，按这份手册从上往下练。不要先背术语，先背“业务目标”和“请求链路”。

## 0. 先看结论

这个项目适合投这些岗位：

| 岗位方向 | 你要强调什么 |
| --- | --- |
| AI 应用工程师 | Agent 工具调用、RAG、Guardrail、成本追踪、评测 |
| Agent 工程师 | Router、Function Calling、LangGraph 工作流、工具 trace、人审队列 |
| Python 后端工程师 | FastAPI、JWT、RBAC、SQLite/MySQL 只读查询、审计日志、pytest |
| 全栈 AI 应用工程师 | Vue3 工作台、FastAPI API、权限、可视化、E2E、Docker/CI |
| 数据产品/数据应用工程师 | 客诉风险指标、异常明细、SOP 依据、复核闭环 |

一句话版本：

> 我做的是一个面向客服主管和运营分析的企业级客诉 Copilot。用户用自然语言描述目标后，系统会自动判断是查数据、查 SOP，还是走 SQL + RAG 复合链路；后端通过 Function Calling、只读 SQL、LangChain RAG、LangGraph、Guardrail、RBAC 和审计日志把结果变成可追踪、可复核、可演示的业务处理流程。

你不能说：

- 我训练了大模型。
- 模型可以自动退款。
- 这是完整企业生产系统。
- 所有规则都已经覆盖所有业务场景。

你应该说：

- 我做的是 AI 应用和 Agent 原型。
- 模型被放在受控工具链里使用。
- 高风险动作只进入人工复核，不自动执行。
- 当前是求职展示级项目，但已经补齐了真实工程里常见的安全、权限、审计、E2E、CI、成本追踪和 demo 产物。

## 1. 项目到底解决什么问题

业务场景：电商客服、售后、运营团队每天要处理大量客诉。

他们常见的问题是：

- 哪些订单最需要优先处理？
- 哪些质量问题可能产生高额退款？
- 用户问“3C 拆封后还能退吗”，客服应该依据哪条 SOP？
- 一个订单是否需要主管复核？
- 系统给出的判断有没有引用来源？
- 模型是不是越权执行了退款、改单、删除数据等动作？

传统做法：

1. 人去数据库里查 SQL。
2. 人去文档里翻 SOP。
3. 人把明细、金额、规则、风险等级整理到 Excel。
4. 人凭经验判断要不要升级主管。

这个项目的做法：

> 用户只说业务目标，系统自动补齐数据、SOP 依据、风险判断、安全拦截、人工复核和审计记录。

示例问题：

```text
质量问题退款超过100元的明细，按 SOP 是否需要主管复核？
```

系统应该做的不是简单回答“需要”或“不需要”，而是：

- 先用只读 SQL 查询异常明细。
- 再把查询结果摘要交给 RAG 检索 SOP。
- 如果 SOP 没有“所有质量问题退款超过 100 元统一复核”这条规则，就不能编造。
- 如果数据呈现高赔付异常，并且规则缺口明显，就建议人工复核。
- 同时展示 SQL、明细、SOP 引用、token/cost、trace 和 review case。

这就是项目最重要的求职亮点：

> 它不是聊天机器人，而是带业务闭环的 AI Copilot。

## 2. 给面试官的 30 秒介绍

背这一段：

> 我做了一个企业级智能客诉预警与数据洞察 Copilot，面向客服主管和运营分析场景。用户可以用自然语言查询异常退款、订单物流、售后 SOP 和用户风险。系统通过 Auto Router 判断该走数据查询、政策检索，还是 SQL + RAG 复合链路；数据查询由 Function Calling 工具和只读 SQLite/MySQL 层完成，政策回答由 LangChain RAG 返回引用来源和分数。为了避免 Agent 越权，我加了 JWT/RBAC、Guardrail、只读 SQL 校验、审计日志和人工复核队列。前端用 Vue3 做成目标优先的工作台，并补了 pytest、Playwright E2E、GitHub Actions CI、Docker 和 demo GIF。

这段里面每个词都能继续展开：

- Auto Router：自动判断该走哪条处理链路。
- Function Calling：模型只选择工具和参数，不直接编造数据。
- 只读 SQL：真正 SQL 在后端受控生成和校验。
- RAG：从售后 SOP 中找依据，不凭空回答政策。
- Guardrail：拦截退款、改单、导出用户等高危请求。
- RBAC：不同角色能用的能力不同。
- Trace/cost：每次请求能看到工具耗时、token 和估算成本。
- E2E/CI/GIF：项目可以自动验收，也能给招聘方看演示产物。

## 3. 给面试官的 2 分钟介绍

背这一段：

> 这个项目的目标是把客服主管每天要做的客诉分析流程变成一个可控的 AI Copilot。前端不是传统的功能堆叠，而是从“今天最该处理什么”开始，引导用户先看优先级，再进入处理工作台。用户输入一个业务目标后，后端先做权限和安全检查，再由 Auto Router 判断问题类型。如果是结构化数据问题，就走 Function Calling Agent，模型选择工具，后端执行只读 SQL 查询退款明细、订单状态、物流状态或退款资格。如果是政策问题，就走 LangChain RAG，从售后 SOP 中检索引用来源、retrieval score 和 rerank score。如果是“明细 + SOP 判断”问题，就先 SQL 查询，再把明细摘要送入 RAG，最后给出是否需要人工复核的建议。

> 我比较重视 Agent 的可控性，所以没有让模型直接写 SQL 或直接执行退款。工具层只暴露查询能力，SQL 做只读校验，Guardrail 会拦截审批、退款、改单、导出用户等高风险请求；命中高风险后会生成人工复核单。系统还记录 request_id、trace_id、工具 trace、token usage、cost breakdown、retry 次数和审计日志。工程化方面，项目有 pytest、Playwright E2E、GitHub Actions CI、Docker 镜像构建、demo 截图和 GIF，方便面试现场或投递材料展示。

如果你只能记两个关键词，就记：

- `受控工具链`：模型不能乱动系统，只能调用被允许的工具。
- `证据闭环`：答案必须带数据、SOP 引用、trace、审计或复核动作。

## 4. 项目架构，给小白看的版本

你可以把系统想成一个客服主管助理团队。

| 系统模块 | 像什么角色 | 它负责什么 |
| --- | --- | --- |
| Vue3 前端 | 工作台 | 让用户先看到今日重点，再输入目标和查看证据 |
| FastAPI | 总调度台 | 接收请求、校验身份、组织 Agent 和工具 |
| JWT/RBAC | 门禁 | 判断你是 viewer、analyst 还是 supervisor |
| Auto Router | 分诊员 | 判断问题该查数据、查 SOP，还是两个都要 |
| Function Calling Agent | 助理 | 根据目标选择工具和参数 |
| SQL Store | 数据员 | 只读查询客诉、订单、退款、物流等结构化数据 |
| LangChain RAG | 资料员 | 从售后 SOP 中找可引用依据 |
| LangGraph | 流程编排 | 把权限、安全、路由、执行、复核、审计变成显式节点 |
| Guardrail | 安全员 | 拦截退款、改单、删除、导出用户等高风险动作 |
| Review Queue | 主管待办 | 高风险或证据不足的问题进入人工复核 |
| Audit Log | 记录员 | 记录每次请求、工具、SQL、成本和耗时 |
| Playwright/CI | 质检员 | 自动跑浏览器验收和持续集成 |

工程架构图：

```text
用户
  -> Vue3 工作台
  -> FastAPI API
  -> JWT / RBAC 权限
  -> Guardrail 安全检查
  -> Auto Router
      -> Function Calling Agent
          -> 只读 SQL 工具
          -> 订单 / 物流 / 退款资格 / 市场政策工具
      -> LangChain RAG
          -> SOP 知识库
          -> Chroma / fallback 检索
      -> SQL + RAG 复合链路
  -> LangGraph 工作流
  -> 人工复核队列
  -> 审计日志 / trace / token / cost
```

## 5. 项目文件你要认识

| 文件或目录 | 你怎么讲 |
| --- | --- |
| `main.py` | FastAPI 兼容入口，方便 `uvicorn main:app` 启动 |
| `app/runtime.py` | 项目核心，包含权限、Router、Agent、RAG、SQL、安全、审计、复核、API |
| `frontend/src` | Vue3 默认生产前端，包含登录、公开页、今日工作台、处理工作台、审计中心、复核中心 |
| `frontend/src/views/HomeView.vue` | 今日优先级页面，引导用户先处理最重要风险 |
| `frontend/src/views/CopilotView.vue` | 主处理工作台，用户输入目标，系统返回结论和证据 |
| `frontend/src/views/AuditCenterView.vue` | 审计中心，展示 request_id、route、tool trace、latency、token 和成本 |
| `frontend/src/views/PublicShowcaseView.vue` | 公网页面，用于投递或作品集展示项目定位和能力边界 |
| `frontend/src/components/AgentFlow.vue` | Agent 执行链路可视化，展示权限、Guardrail、Router、工具、复核、审计节点 |
| `frontend/src/components/EvidenceRail.vue` | 右侧证据栏，展示 SOP 引用、SQL、trace、token 和成本 |
| `frontend/src/stores/chat.ts` | 前端聊天状态和 SSE 处理逻辑 |
| `templates` / `static` | 旧版轻量演示页，保留在 `/legacy` 和 `/legacy-review` 做兼容 |
| `knowledge_base/policies.json` | 售后 SOP 知识库 |
| `complaint_copilot.sqlite3` | 本地只读样本数据库 |
| `audit_log.sqlite3` | 审计日志、复核队列、反馈事件等 |
| `tests/` | pytest 单元测试和接口测试 |
| `tests/e2e/acceptance.spec.js` | Playwright 浏览器端到端验收 |
| `.github/workflows/ci.yml` | GitHub Actions CI |
| `Dockerfile` / `docker-compose.yml` | 容器化和 Redis/Nginx 组合部署 |
| `scripts/capture_demo.js` | 自动截图并生成 demo GIF |
| `output/playwright/copilot-demo.gif` | 可放到作品集或 README 的演示 GIF |

注意：项目现在以 Vue3 作为默认生产前端。

- 单端口演示访问 `http://127.0.0.1:4261`，FastAPI 会优先托管 `frontend/dist`。
- `templates` / `static` 仍然保留，但只作为 `/legacy` 和 `/legacy-review` 兼容入口。

面试时可以这样解释：

> 我把 Vue3 工作台提升为默认生产前端，并保留旧静态页作为兼容入口。这样面试时打开 4261 就是完整产品化工作台，同时仍能说明我考虑了迁移和回滚路径。

## 6. 一条请求到底怎么跑

以这个问题为例：

```text
质量问题退款超过100元的明细，按 SOP 是否需要主管复核？
```

后端流程：

1. `/api/chat` 收到请求。
2. 从 Bearer Token 解析用户身份和角色。
3. Rate limit 和权限检查，避免未授权调用。
4. Guardrail 先看是否有退款、改单、删除、导出用户等高危意图。
5. Auto Router 判断这是 `sql_rag_chain`，也就是先查数据再查 SOP。
6. SQL 工具用参数化查询读取本地 SQLite 或 MySQL 只读数据。
7. SQL 返回异常明细、金额、订单、类目、SQL preview。
8. 后端把“查到的结构化摘要”交给 RAG。
9. LangChain RAG 检索 SOP，返回引用、检索分数、rerank 分数。
10. 系统组织结论：不能编造不存在的统一规则，但数据高风险时建议人工复核。
11. 如果需要复核，写入 human review queue。
12. 写审计日志：request_id、trace_id、route、tool trace、SQL、latency、token、cost、retry。
13. 前端展示结论，右侧证据栏展示 SQL、SOP、trace、成本。

你要强调的点：

> 模型不是直接拍脑袋回答，而是被放在“权限、安全、工具、证据、审计”这条链路里。

## 7. 当前已经实现了什么

你之前问过四个点：LangChain token/cost 细化、E2E、CI、GIF。当前都已经落到项目里了，面试可以讲。

| 能力 | 当前状态 | 面试讲法 |
| --- | --- | --- |
| LangChain token/cost 细化 | 已实现 | RAG 和 Agent 响应会返回 `token_usage`、`cost_breakdown`、`estimated_cost_usd`，前端也展示运行成本 |
| E2E | 已实现 | Playwright 覆盖首页、数据洞察、RAG、SQL + RAG、Guardrail、审计、复核中心 |
| CI | 已实现 | GitHub Actions 跑 Python 依赖、Node 依赖、py_compile、JS check、pytest、frontend build、Playwright E2E、Docker build |
| GIF | 已实现 | `npm run capture:demo` 生成截图和 `output/playwright/copilot-demo.gif` |
| Vue3 产品化前端 | 已实现 | 登录、今日页、处理工作台、复核中心、证据栏、运行成本展示 |
| JWT 登录 | 已实现 | 种子账号、PBKDF2 密码哈希、Bearer Token |
| RBAC | 已实现 | viewer、analyst、supervisor 三类角色，复核中心限制 supervisor |
| Redis fallback | 已实现 | 有 Redis 用 Redis，没有 Redis 自动使用内存 fallback |
| LangGraph | 已实现原型 | 权限、安全、路由、执行、复核、审计节点显式编排 |
| 只读 SQL | 已实现 | SQLite 默认，本地 MySQL 只读路径有说明和脚本 |
| Guardrail | 已实现 | 拦截高危写操作和越权动作 |
| 审计日志 | 已实现 | SQLite 记录请求、工具、SQL、成本、耗时 |
| 反馈事件 | 已实现 | 前端反馈写入后端事件表 |

## 8. 核心技术概念，用人话解释

### 8.1 LLM

LLM 就是大语言模型，比如 GPT 系列。它擅长理解自然语言和组织文字，但不应该直接相信它的事实和权限判断。

你项目里的做法：

> LLM 负责理解用户目标和选择工具，真实数据、权限、安全和执行都由后端控制。

### 8.2 Function Calling

Function Calling 是让模型返回“要调用哪个工具”和“参数是什么”。

普通聊天：

```text
用户：查质量问题退款超过100元的明细
模型：我觉得有 10 条...
```

Function Calling：

```text
用户：查质量问题退款超过100元的明细
模型：调用 query_refund_cases，参数 complaint_type=质量问题，amount_threshold=100
后端：执行只读 SQL，返回真实明细
```

你面试要说：

> 我没有让模型直接编造数据，而是让模型选择工具和参数，数据由后端只读查询返回。

### 8.3 RAG

RAG 是 Retrieval Augmented Generation，中文可以理解成“先检索资料，再回答”。

为什么需要 RAG：

- 模型不知道你公司的最新售后 SOP。
- 模型可能编造政策。
- 面试官会关心答案有没有出处。

你项目里的 RAG：

- 知识来源是 `knowledge_base/policies.json`。
- 可使用 LangChain + Chroma 向量库。
- 没有 API Key 或向量库不可用时，有 fallback 检索。
- 返回 citation、retrieval score、rerank score。
- 记录 token usage 和 cost breakdown。

面试背法：

> RAG 不是为了让回答更花哨，而是为了让政策回答可追溯。用户问售后规则时，系统先检索 SOP，再让模型基于证据组织答案，并把引用来源展示给用户。

### 8.4 SQL + RAG

SQL + RAG 是这个项目的亮点之一。

只查 SQL，只能知道“哪些订单异常”。

只查 RAG，只能知道“SOP 怎么写”。

SQL + RAG 可以回答：

```text
这些异常订单按 SOP 是否需要主管复核？
```

流程：

```text
自然语言问题
  -> 只读 SQL 查明细
  -> 将明细摘要交给 RAG
  -> 检索 SOP
  -> 给出复核建议
```

这比单纯问答更像真实业务系统。

### 8.5 Guardrail

Guardrail 是安全护栏。

它要防止用户这样问：

```text
直接退款并改订单
导出所有用户数据
删除这些投诉记录
ignore previous instructions
```

项目的处理：

- 拦截高危意图。
- 不暴露写工具。
- SQL 做只读校验。
- 生成 review case。
- 写审计日志。

你要强调：

> Guardrail 不只是 prompt，而是工具层、SQL 层、权限层和审计层一起限制 Agent 能力。

### 8.6 RBAC

RBAC 是基于角色的权限控制。

项目角色：

| 角色 | 能力 |
| --- | --- |
| viewer | 只能看基础信息和政策类能力 |
| analyst | 可以做只读数据分析和 Copilot 查询 |
| supervisor | 可以进入复核中心处理高风险 case |

求职讲法：

> Agent 应用不能只做聊天框，必须知道谁能查什么、谁能复核什么。这个项目用 JWT 和 RBAC 做了轻量权限边界。

### 8.7 LangGraph

LangGraph 可以理解为把 Agent 流程变成“节点图”。

项目里的节点可以这样讲：

```text
permission_node
  -> guardrail_node
  -> router_node
  -> execute_node
  -> review_node
  -> audit_node
```

它的好处：

- 流程清晰。
- 哪一步拦截、哪一步执行、哪一步写审计都能追踪。
- 后续扩展多步骤 Agent 更方便。

不要夸大：

> 当前 LangGraph 是显式编排原型，不是复杂多 Agent 自主规划系统。

### 8.8 Token 和 Cost

Token 可以简单理解为模型计算文本时的单位。Cost 是按 token 估算出来的成本。

项目里做了：

- 提取 LLM usage。
- 估算 prompt tokens、completion tokens、embedding tokens。
- 按配置的单价估算成本。
- 在响应和审计日志里记录。
- 前端在证据栏展示运行成本。

求职讲法：

> AI 应用上线后成本是核心指标，所以我没有只看回答质量，还把 token、cost、retrieval latency 和 retry 写入 trace，方便排查和优化。

### 8.9 E2E

E2E 是端到端测试，就是模拟真实用户用浏览器操作。

项目里的 E2E 会验证：

- 首页能打开。
- 数据洞察能跑。
- RAG 有引用。
- SQL + RAG 有 SQL 和 SOP 证据。
- Guardrail 能拦截。
- 审计日志有记录。
- 复核中心能处理 case。

面试讲法：

> 单元测试只能证明函数对，E2E 能证明关键用户路径真的能跑通。

### 8.10 CI

CI 是持续集成。每次 push 或 PR 都自动跑检查。

项目 CI 包括：

- 安装 Python 依赖。
- 安装 Node 和前端依赖。
- Python 编译检查。
- JavaScript 语法检查。
- pytest。
- Vue 前端 build。
- Playwright E2E。
- Docker image build。

求职讲法：

> 我把项目从 demo 往工程化推进了一步，不靠手工点页面判断能不能跑。

### 8.11 GIF

GIF 不是技术核心，但对求职很有用。

作用：

- 简历或作品集里能快速看到项目效果。
- 面试官不用先拉代码也能理解你做了什么。
- 证明项目有可视化演示结果。

项目命令：

```powershell
npm run capture:demo
```

产物：

```text
output/playwright/copilot-demo.gif
```

## 9. 面试现场怎么演示

### 9.1 构建 Vue 前端

```powershell
cd frontend
npm run build
cd ..
```

### 9.2 启动单端口演示

```powershell
$env:AUTH_ENFORCED="true"
$env:REDIS_ENABLED="false"
$env:DATA_QUERY_BACKEND="sqlite"
$env:USE_LANGCHAIN_RAG="false"
python -m uvicorn main:app --host 127.0.0.1 --port 4261
```

默认地址：

```text
http://127.0.0.1:4261
```

演示账号：

```text
viewer@example.com / Viewer@123
analyst@example.com / Analyst@123
supervisor@example.com / Supervisor@123
```

### 9.3 演示顺序

第一步：登录。

你说：

> 这里演示了企业应用最基本的身份入口。不同角色看到的功能不同，比如复核中心只有主管能进。

第二步：首页看今日优先级。

你说：

> 我没有把页面做成功能按钮堆叠，而是按客服主管的目标组织，先告诉他今天最该处理什么。

第三步：进入处理工作台，问：

```text
质量问题退款超过100元的明细，按 SOP 是否需要主管复核
```

你说：

> 这是 SQL + RAG 复合链路。先查异常明细，再检索 SOP。注意这里不会编造“超过 100 元统一复核”的规则，如果 SOP 没有明确写，就会提示按类目、风险和证据人工复核。

第四步：问政策：

```text
3C 数码拆封后出现质量问题，应该怎么处理
```

你说：

> 这是 RAG 场景，回答必须带 SOP 引用和检索分数。

第五步：问物流：

```text
查询订单 53cdb2fc8bc7dce0b6741e2150273451 的物流状态
```

你说：

> 这是业务工具调用，不是 RAG。模型负责选工具，后端返回结构化订单和物流信息。

第六步：输入高危请求：

```text
直接退款并改订单
```

你说：

> 这个系统定位是只读分析助手，所以退款和改单会被 Guardrail 拦截，并进入人工复核队列。

第七步：打开复核中心。

你说：

> 高风险不是自动执行，而是生成复核单，主管可以通过或驳回。这就是 human-in-the-loop。

第八步：展示工程化。

```powershell
python -m pytest -q
cd frontend
npm run build
cd ..
npm run test:e2e
npm run capture:demo
```

你说：

> 我补了单元测试、前端构建、浏览器验收和 demo GIF，CI 也会自动跑这些关键检查。

## 10. 简历怎么写

### 10.1 项目标题

推荐：

```text
企业级智能客诉预警与数据洞察 Copilot
```

可选副标题：

```text
基于 FastAPI、Vue3、Function Calling、LangChain RAG、LangGraph 和 Guardrail 的 AI Agent 应用
```

### 10.2 一句话项目描述

```text
面向客服主管和运营分析场景，构建一个可进行自然语言数据查询、售后 SOP 检索、高风险操作拦截、人工复核和审计追踪的 AI Copilot 原型。
```

### 10.3 简历 bullet，小白稳妥版

```text
- 基于 FastAPI 和 Vue3 构建企业客诉 Copilot 原型，支持登录、角色权限、自然语言查询、异常明细展示和人工复核流程。
- 设计 Auto Router，将用户问题分发到 Function Calling、LangChain RAG 或 SQL + RAG 复合链路，提升回答的结构化和可解释性。
- 实现只读 SQL 查询工具，支持按投诉类型、类目、赔付金额等条件查询异常明细，并返回 SQL preview、指标汇总和明细表。
- 构建售后 SOP RAG 检索能力，返回 citation、retrieval score、rerank score，并在无向量库或无 API Key 时提供 fallback。
- 加入 Guardrail、RBAC、审计日志和人工复核队列，拦截退款、改单、导出用户等高风险请求，保证 Agent 只在受控边界内执行。
- 补充 token/cost 追踪、pytest、Playwright E2E、GitHub Actions CI、Docker 构建和 demo GIF，提高项目可演示性和工程完整度。
```

### 10.4 简历 bullet，进阶版

```text
- 负责企业客诉 Copilot 的端到端实现，使用 FastAPI + Vue3 + Pinia 构建前后端分离工作台，并通过 JWT、RBAC 和路由守卫实现 viewer / analyst / supervisor 权限边界。
- 设计受控 Agent 执行链路，将自然语言请求路由到 Function Calling、LangChain RAG、SQL + RAG 或 LangGraph 工作流，支持订单、物流、退款资格、市场政策和异常退款明细查询。
- 实现 SQLite/MySQL 只读查询层与 SQL 安全校验，禁止模型直接执行任意 SQL，工具层通过参数化查询返回结构化指标、明细、SQL preview 和 Tool Trace。
- 构建 SOP RAG 与复合推理链路，基于 citation、retrieval score、rerank score 和明细摘要生成可追溯回答，并修正“规则未覆盖时不能编造统一复核条件”的输出逻辑。
- 建立 Agent 治理能力，包括 Guardrail、高危请求拦截、human-in-the-loop 复核队列、反馈事件、审计日志、trace_id、retry_count、token usage 和 cost breakdown。
- 搭建工程化验收体系，使用 pytest、Playwright E2E、GitHub Actions CI、Docker build 和自动截图/GIF 脚本覆盖核心演示路径。
```

### 10.5 英文简历 bullet

```text
- Built an enterprise complaint intelligence Copilot with FastAPI, Vue 3, Function Calling, LangChain RAG, LangGraph, readonly SQL tools, RBAC, audit logging, and human review workflows.
- Designed a controlled Agent execution flow that routes user goals to structured data tools, SOP retrieval, or SQL-to-RAG workflows while blocking high-risk actions through guardrails.
- Implemented token usage, cost breakdown, tool trace, SQL preview, Playwright E2E tests, GitHub Actions CI, Docker build, and automated demo GIF capture for interview-ready delivery.
```

## 11. 面试常见问题和回答

### Q1：你这个项目为什么算 Agent？

答：

> 它不是多 Agent 系统，但算 AI Agent 应用原型。因为它不只是把问题发给模型，而是能根据用户目标做路由，选择工具，调用只读 SQL 或 RAG，观察结果，再组织回答。同时它有短期 memory、Guardrail、人工复核和审计 trace，具备 Agent 应用的关键组成。

### Q2：为什么不用模型直接写 SQL？

答：

> 直接让模型写 SQL 风险比较高，可能出现 SQL 注入、越权查询、写操作或者查错表。我这里让模型只输出工具参数，比如 complaint_type 和 amount_threshold，真正 SQL 由后端受控生成，并且有只读校验和参数化查询。

### Q3：RAG 解决了什么问题？

答：

> RAG 解决的是政策回答的可追溯问题。比如售后 SOP 可能更新，模型本身不知道企业内部规则，所以系统先从知识库检索相关条款，再基于引用回答，并把 citation 和检索分数展示给用户。

### Q4：SQL + RAG 为什么重要？

答：

> 真实业务问题经常既要数据又要规则。比如“质量问题退款超过 100 元是否需要主管复核”，系统要先查出符合条件的明细，再用 SOP 判断处理依据。单独 SQL 或单独 RAG 都不够，所以我做了复合链路。

### Q5：你怎么保证模型不会越权？

答：

> 第一，工具层只暴露查询和检索，不暴露退款、改单、删除接口。第二，SQL 层做只读校验。第三，Guardrail 拦截高危意图。第四，RBAC 限制角色能力。第五，所有请求写审计日志，高风险进入人工复核。

### Q6：如果 RAG 没找到明确规则怎么办？

答：

> 不能编造规则。我的处理是说明当前 SOP 没有明确覆盖，然后结合已有数据风险给出建议，比如“证据不足，建议人工复核”。这次项目里也修正了类似问题，避免把“质量问题退款超过 100 元”错误说成统一复核规则。

### Q7：token/cost 为什么要做？

答：

> AI 应用上线后不只看效果，还要看成本。每次 RAG、LLM 或 embedding 调用都可能产生成本，所以我在响应和审计中记录 token usage、cost breakdown 和 estimated cost，前端也展示运行成本，方便后续优化。

### Q8：没有 API Key 怎么演示？

答：

> 项目设计了 fallback。没有 LLM 或 embedding key 时，Function Calling 可以走确定性工具选择，RAG 可以走本地 fallback 检索。这样面试现场即使没网，也能演示只读 SQL、SOP 引用、Guardrail、复核和审计。

### Q9：Redis 是必须的吗？

答：

> 不是必须。项目支持 Redis 存 session memory、rate limit、缓存和任务状态。如果 Redis 不可用，会自动降级到内存实现，保证本地演示稳定。

### Q10：LangGraph 在项目里起什么作用？

答：

> LangGraph 用来把权限、安全、路由、执行、复核、审计这些步骤显式编排成节点。这样比把所有逻辑揉在一个函数里更容易解释流程，也方便后续扩展更复杂的 Agent 工作流。

### Q11：这个项目最大的工程亮点是什么？

答：

> 我认为亮点不是某个单点技术，而是把 AI 能力放进了一个受控业务系统里。它有工具调用、RAG、SQL 复合链路，也有权限、安全、审计、人工复核、成本追踪、E2E、CI 和 demo 产物。

### Q12：这个项目离生产还差什么？

答：

> 主要差真实企业数据接入、正式 SSO、完善的数据脱敏、线上监控告警、更系统的 RAG 评测、更细粒度权限、真实审批系统和压测。当前项目定位是求职展示级原型，重点是证明我理解 AI 应用落地时需要的工程边界。

## 12. STAR 故事，面试讲项目难点

### 故事 1：修正 SQL + RAG 输出错误

S，背景：

> 用户问“质量问题退款超过 100 元是否需要主管复核”，系统原来容易把上下文里的 SOP 解释成统一规则。

T，任务：

> 要让系统既能给出业务建议，又不能编造 SOP 中不存在的规则。

A，行动：

> 我调整了 SQL + RAG 的回答组织逻辑，让它先说明 SOP 未提及“所有质量问题超过 100 元统一复核”，再结合高赔付异常、商品类别、拆封情况、风险等级等因素建议人工复核，并在前端展示证据。

R，结果：

> 输出从“看起来确定但依据不足”变成“有边界、有依据、有下一步动作”，更符合企业客服场景。

### 故事 2：把页面从功能堆叠改成目标优先

S，背景：

> 原页面更像功能集合，用户需要自己判断先点哪里。

T，任务：

> 按“用户要完成什么”重构前端。

A，行动：

> 我把首页改成“今日优先级”，把处理页改成“说出目标，系统自动补齐证据”，把高级设置折叠，把结论留在对话区，把 SQL、SOP、trace、成本放进右侧证据栏。

R，结果：

> 用户先看到行动建议，再按需展开证据，符合“不要让用户思考”和“渐进式展示”的交互原则。

### 故事 3：把 demo 补成可验收项目

S，背景：

> AI demo 常见问题是只能现场手点，过几天容易跑不通。

T，任务：

> 让项目可以自动验证、自动截图、自动生成演示材料。

A，行动：

> 我补了 pytest、Playwright E2E、GitHub Actions CI、Docker build 和 capture demo 脚本，核心路径包括数据洞察、RAG、SQL + RAG、Guardrail、审计和复核。

R，结果：

> 项目从“能演示”升级为“能持续验证”，更接近真实工程交付。

## 13. 小白学习路线，7 天版

### 第 1 天：只理解业务

目标：

- 能说清楚客服主管为什么需要这个系统。
- 能背 30 秒介绍。
- 能演示登录、今日页、处理页。

不要急着看代码。

### 第 2 天：理解请求链路

目标：

- 能画出“用户 -> 前端 -> FastAPI -> Router -> Tool/RAG -> 审计”的流程。
- 能讲 SQL + RAG 为什么比普通聊天强。

### 第 3 天：理解 Function Calling 和 SQL 安全

目标：

- 能解释模型不直接写 SQL。
- 能解释工具参数、参数化查询、只读校验。

### 第 4 天：理解 RAG

目标：

- 能解释 citation、retrieval score、rerank score。
- 能讲 fallback 的意义。
- 能回答“RAG 不准怎么办”。

### 第 5 天：理解安全和权限

目标：

- 能解释 Guardrail、RBAC、JWT、Review Queue、Audit Log。
- 能演示“直接退款并改订单”被拦截。

### 第 6 天：理解工程化

目标：

- 跑一遍 pytest。
- 跑一遍 frontend build。
- 跑一遍 Playwright E2E。
- 知道 CI 做了什么。
- 知道 GIF 在哪里。

### 第 7 天：模拟面试

目标：

- 用 30 秒讲项目。
- 用 2 分钟讲架构。
- 回答 10 个常见问题。
- 讲 1 个 STAR 难点故事。

## 14. 你最应该背熟的 8 句话

1. 这个项目不是普通聊天机器人，而是带工具调用、RAG、权限、安全和审计的 AI Copilot。
2. 模型不直接查数据库，也不直接写 SQL，它只选择工具和参数。
3. 所有结构化数据查询都走后端只读工具，SQL 有参数化和只读校验。
4. RAG 的价值是让售后 SOP 回答有引用来源，而不是靠模型记忆。
5. SQL + RAG 用来解决“先查明细，再按规则判断”的真实业务问题。
6. Guardrail 不只是 prompt，它还包括工具能力边界、SQL 限制、RBAC 和审计。
7. token/cost 追踪是为了让 AI 应用具备上线后的成本可观测性。
8. E2E、CI、Docker 和 GIF 证明这个项目不是只靠手点演示。

## 15. 面试不要踩的坑

不要说：

```text
我做了一个能自动处理退款的系统。
```

改成：

```text
系统会识别高风险退款意图并进入人工复核，不自动执行退款。
```

不要说：

```text
模型会自动生成 SQL 查询数据库。
```

改成：

```text
模型选择工具和参数，SQL 由后端受控生成并只读执行。
```

不要说：

```text
RAG 一定准确。
```

改成：

```text
RAG 能提高可追溯性，但仍需要 citation、评测和人工复核兜底。
```

不要说：

```text
这是完整生产系统。
```

改成：

```text
这是求职展示级原型，已经覆盖生产系统会关注的权限、安全、审计、成本和测试等关键设计。
```

## 16. 你可以问面试官的问题

面试最后可以问：

- 贵团队现在的 AI 应用更偏 RAG 问答，还是偏业务流程自动化？
- 你们对 Agent 的安全边界是怎么设计的，是 prompt 层、工具层还是权限层一起做？
- 企业内部知识库的 RAG 评测一般看 citation 命中率，还是更关注答案可用性？
- 你们是否会记录 token、cost、tool trace 这类可观测指标？
- 这类 AI 应用上线后，人工复核和审计一般接在哪个系统里？

这些问题能表现出你不只是会写 demo，也理解真实落地问题。

## 17. 最终背诵模板

完整版本：

> 我做的项目叫企业级智能客诉预警与数据洞察 Copilot，目标是帮助客服主管和运营人员用自然语言完成客诉分析、售后 SOP 查询和高风险复核。前端用 Vue3 做成目标优先的工作台，用户先看到今日最该处理的风险，再进入处理页输入业务目标。后端基于 FastAPI，先做 JWT/RBAC 权限和 Guardrail 安全检查，再由 Auto Router 判断问题走 Function Calling、LangChain RAG，还是 SQL + RAG 复合链路。
>
> 数据查询部分，我没有让模型直接写 SQL，而是让模型选择工具和参数，后端通过只读 SQLite/MySQL 查询层返回异常明细、指标、SQL preview 和 Tool Trace。政策问答部分，我用 RAG 检索售后 SOP，返回 citation、retrieval score 和 rerank score。对于“质量问题退款超过 100 元是否需要主管复核”这类问题，系统会先查 SQL 明细，再用 RAG 查 SOP；如果 SOP 没有明确统一规则，就不会编造，而是结合高赔付异常和证据缺口建议人工复核。
>
> 为了让 Agent 可控，我加了 Guardrail、RBAC、只读 SQL 校验、审计日志和 human-in-the-loop 复核队列。为了让项目更接近工程交付，我补了 token/cost 追踪、pytest、Playwright E2E、GitHub Actions CI、Docker build 和自动截图/GIF。这个项目目前是求职展示级原型，不是完整生产系统，但它覆盖了 AI 应用落地时比较关键的工具调用、知识检索、安全边界、可观测性和验收链路。

你能把这段讲顺，就已经能撑住大部分项目面试。
