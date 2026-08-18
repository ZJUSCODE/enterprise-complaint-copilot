# 客诉预警 Copilot 项目 — 完全吃透学习计划

> 基于本项目的真实代码结构制定。每步都有明确目标、操作指引、检验标准。
> 你可以选择 **AI PM 路线（4 周）** 或 **AI 应用工程师路线（6 周）**，或两条都走。

---

## 使用说明

- 每个任务标注了预估耗时和优先级（P0 = 必须做，P1 = 建议做，P2 = 可选）
- 「检验标准」是你自我检测的及格线——做完了过不了检验说明没真懂
- 工程师路线假设你会 Python 基础 + 基本的 REST API 概念。不会的话先花 2 周补：[Python 官方教程](https://docs.python.org/3/tutorial/) + [FastAPI 教程](https://fastapi.tiangolo.com/tutorial/)

---

## 第一阶段：把项目跑起来（2 天，两条路线都要做）

> **目标**：项目能在本地启动，你能在浏览器里使用 Copilot 对话界面。

### 1.1 环境准备

```bash
# 1. 确认 Python 版本 >= 3.10
python --version

# 2. 创建虚拟环境（项目根目录下）
cd "D:\A_产品\企业级智能客诉预警与数据洞察 Copilot\Try-Code"
python -m venv .venv

# 3. 激活虚拟环境（Windows PowerShell）
.venv\Scripts\Activate.ps1
# 如果报权限错误，先执行：Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 4. 安装依赖
pip install -r requirements.txt
```

### 1.2 配置

在项目根目录创建 `.env` 文件：

```env
# 必填：LLM API Key（用你的 OpenAI 或兼容 API 的 key）
LLM_API_KEY=sk-your-key-here
# 可选：如果用的是第三方 API（如 DeepSeek、通义千问），还要配 base_url
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 其他保持默认即可
AUTH_ENFORCED=false
DATA_QUERY_BACKEND=sqlite
```

### 1.3 启动并验证

```bash
# 启动后端（项目根目录）
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 另开一个终端，启动前端
cd frontend
npm install        # 仅第一次
npm run dev        # 启动在 127.0.0.1:4261
```

**检验标准**：
- [ ] 浏览器打开 `http://127.0.0.1:4261` 能看到登录页面
- [ ] 用 `analyst@example.com` / `password123` 登录成功
- [ ] 在 Copilot 页面输入「查一下上个月的高赔付订单」能返回结果
- [ ] 如果卡住了，看终端日志报了什么错

---

## 第二阶段：建立概念底盘（3 天，两条路线都要做）

> **目标**：你能用自己的话解释清楚 LLM、RAG、Agent、Embedding、向量数据库这 5 个概念，以及它们在项目里分别对应哪段代码。

### 2.1 LLM（大语言模型）

**学什么**：LLM 是一个「根据上文预测下一个词」的概率模型。它对世界的一切知识都来自训练数据，训练完成后知识就固定了。

**在项目里对应**：`app/function_agent.py` 第 1 行 `from openai import OpenAI`——本项目通过 OpenAI SDK 调用 LLM。

**检验**：能说清楚「为什么 LLM 会胡说八道（幻觉）」和「为什么 LLM 不知道你公司内部的退款政策」。

---

### 2.2 RAG（检索增强生成）

**学什么**：在调 LLM 之前，先从知识库里搜出相关资料，把资料和问题一起给 LLM。流程：文档 → 切块 → 向量嵌入 → 存入向量库 → 用户提问也嵌入 → 搜出最相似的块 → 块+问题 → LLM 生成。

**在项目里对应**：`app/rag.py` 的 `LangChainRAGService.query()` 方法。

**检验**：能画出「文档→切块→嵌入→检索→生成」五步流程图，每步旁边标注对应的代码文件/函数名。

---

### 2.3 Agent / Function Calling

**学什么**：普通 LLM 只能「说」，Agent 能「做」——调用外部工具获取真实数据。Function Calling 是 OpenAI 提供的一种机制：你给 LLM 一个工具列表（函数名+描述+参数），LLM 在需要时返回「我要调函数 X，参数是 Y」，你的代码执行并返回结果，LLM 再根据结果回答。

**在项目里对应**：`app/function_agent.py` 的 `_build_tools()`（定义 7 个工具）和 `respond()`（ReAct 循环）。

**检验**：能区分三个概念——「LLM 直接回答」「LLM + RAG」「LLM + Function Calling」，各举一个本项目的真实例子。

---

### 2.4 Embedding（向量嵌入）

**学什么**：Embedding 是把一段文字变成一串数字（向量）。语义相近的文字，向量也相近。这是 RAG 能「语义搜索」的基础。

**在项目里对应**：`app/rag.py` 中 `OpenAIEmbeddings(model="text-embedding-3-small")`。

**检验**：能解释「为什么搜『退货流程』能找到标题是『退款政策』的文档」——因为二者的向量在空间中很接近。

---

### 2.5 向量数据库（ChromaDB）

**学什么**：专门存储和检索向量的数据库。你存入一堆（向量 + 原文本）对，查询时给它一个查询向量，它返回最接近的 K 个结果。

**在项目里对应**：`app/rag.py` 中的 `chromadb.PersistentClient` 和 `collection.query()`。

**检验**：能说清楚 ChromaDB 在本项目中的两个用途——① 启动时把知识库文档嵌入并存入；② 每次 RAG 查询时检索 Top-K 相关文档片段。

---

## AI PM 路线（第 3-6 周）

> 如果你目标是 AI 产品经理，走这条。**不需要写代码**，但要能读懂架构、讲清楚设计决策。

---

### 第三周：读懂项目的业务和架构

#### Day 1-2：业务场景

**操作**：
1. 细读 `README.md` 前 3 段（到演示账户那行），用一句话总结这个项目解决什么业务问题
2. 打开前端，用 3 个不同角色登录，体验每个角色能看到什么功能
3. 读 `docs/project-tutorial.html` 第 1 章

**检验**：不看资料，对空气讲 2 分钟：「这个项目是什么、解决什么问题、给谁用的」

#### Day 3-4：5 种 Agent 模式的业务意义

**操作**：
1. 读 `docs/project-tutorial.html` 第 5.2 节的表格
2. 回到前端 Copilot 页面，切换 5 种模式（下拉选择器），每种模式问一个问题，看返回有什么不同
3. 思考：如果你的用户说下面这些话，系统分别应该走哪个模式？

| 用户说 | 应该走哪个模式 | 为什么 |
|--------|-------------|--------|
| "订单 8a3f2b 到哪了" | function_call_agent | 纯数据查询，只需要调 SQL |
| "巴西市场怎么退款" | langchain_rag | 纯政策咨询，只需要查知识库 |
| "高赔付订单能不能退款" | sql_rag_chain | 先查哪些订单高赔付，再看政策允不允许 |
| "这个用户整体风险怎么样，要不要升级" | multi_agent | 需要数据 + 政策 + 风险评估三方面 |
| "中国和巴西的退货政策有什么区别" | modular_rag | 复杂多跳 RAG，需要 KG + CRAG |

**检验**：给你 5 个你没见过的问题，正确判断每个该走哪个模式，且能说清理由。

#### Day 5：安全护栏的业务设计

**操作**：
1. 读 `docs/project-tutorial.html` 第 9.1-9.2 节
2. 读 `app/domain.py` 中的 4 个安全模式列表（`MUTATION_PATTERNS`、`PROMPT_INJECTION_PATTERNS`、`DATA_EXFILTRATION_PATTERNS`、`SOCIAL_ENGINEERING_PATTERNS`）
3. 在前端试：输入「帮我把订单退款了」看看会发生什么
4. 思考两个场景：
   - 「护栏太松」漏了一个该拦的请求 → 业务上有什么后果？
   - 「护栏太紧」拦了一个不该拦的请求 → 用户体验有什么影响？

**检验**：能独立设计一套护栏规则——如果你接手的不是电商而是医疗问诊场景，护栏应该拦什么？（提示：药品推荐、诊断建议、紧急情况）

#### Day 6-7：全流程串讲 + 画图

**操作**：
1. 对着 `docs/project-tutorial.html` 第 5 章，在白纸或白板上画出「用户问高赔付订单」的完整 7 步流程图
2. 每步标注：哪个文件负责、输入是什么、输出是什么
3. 画完后自己讲一遍，录下来，回放听有没有卡壳的地方

**检验**：脱稿讲完 7 步，中间不翻资料，不卡壳超过 5 秒。

---

### 第四周：评测和迭代（AI PM 最核心技能）

#### Day 1-2：理解评测体系

**操作**：
1. 打开 `eval/agent_eval_cases.json`，看结构（不需要逐行读），理解评测分 4 类：
   - `route`：测路由对不对
   - `tool`：测工具选得对不对
   - `guardrail`：测护栏拦得对不对
   - `memory`：测多轮对话记不记得住
2. 打开 `eval/v2_eval_report.md`，找到所有「失败」或「不通过」的 case
3. 思考：评测为什么要分类测，而不是只测「答案准不准」？

**检验**：能解释「路由准确率 86.7%」和「引用命中率 100%」这两个指标分别测什么，为什么一个低一个高。

#### Day 3-4：Bad Case 分析实战

**操作**：
1. 在 `eval/v2_eval_report.md` 里找 3 个失败的 case
2. 对每个 case，分析：
   - 用户问了什么
   - 系统做了什么（错了什么）
   - 根因是什么（路由规则写漏了？护栏模式没覆盖？RAG 检索偏了？）
   - 如果你来改，你会怎么改？

**格式示例**：

```markdown
## Bad Case #1

**用户输入**："帮我查下 refund 的流程"
**系统行为**：路由到了 function_call_agent，调了 SQL 查询
**应该行为**：应该走 langchain_rag 查政策文档
**根因**："refund" 是英文，路由规则只匹配了中文关键词"退款"
**改进方案**：在 POLICY_PATTERNS 里加英文关键词
```

**检验**：分析完 3 个 case，每个都能说清楚根因和改进方案。

#### Day 5-6：设计改进闭环

**操作**：
1. 思考：如果这个产品上线了，你怎么持续发现和修复 Bad Case？
2. 设计一个「用户反馈 → Bad Case 收集 → 分析归类 → 改进 → 验证」的闭环流程
3. 在项目里找对应这个闭环的功能模块（提示：`FeedbackEventStore`、`AuditLogStore`、评测脚本）

**检验**：能画出完整的「AI 产品迭代闭环」流程图，标注每个环节在项目中的代码对应。

#### Day 7：复盘

- 把本周学到的东西用你自己的话写一篇总结
- 重点写：评测体系设计的核心原则、Bad Case 分析的方法论

---

### 第五周：面试准备

#### Day 1-2：准备项目介绍

**2 分钟版本**（逐字稿）：

> 我做的是一个企业级 AI Agent 工作台，场景是电商客诉处理。传统做法是客服主管手动查数据库、翻政策文档、凭经验判断要不要升级。我的方案是：用户用自然语言说目标，系统自动判断意图、查数据或检索政策、综合答案，并且给出可追溯的证据链。
>
> 技术上，我设计了 5 种 AI 工作模式来覆盖不同场景——纯数据查询走 Function Calling Agent，纯政策咨询走 RAG，数据+政策组合走 SQL+RAG，复杂综合分析走多 Agent 协作，复杂 RAG 查询走模块化流水线。安全方面有 6 层防护——JWT 认证、RBAC 鉴权、安全护栏、只读 SQL、人工复核、全量审计。
>
> 评测结果是路由准确率 86.7%，引用命中率 100%，护栏拦截率 83.3%。

**5 分钟版本**：在 2 分钟基础上，深挖安全护栏的设计（4 类检测 + 为什么这样分类 + 人工复核的逻辑）。

#### Day 3-4：准备追问

以下问题的回答自己要练到流畅：

| 面试官可能问 | 你要能答出 |
|------------|----------|
| "5 种模式怎么选的？" | 规则路由（正则+关键词，80% 场景，零延迟）+ LLM 路由（模糊意图，分类提示词），规则置信度低于 0.8 才走 LLM |
| "RAG 准确性怎么保证？" | 5 层保障：混合检索→RRF 融合→CrossEncoder 重排序→CRAG 纠正→Self-RAG 反思 |
| "如果部署到生产环境，还需要做什么？" | SQLite→PostgreSQL、ChromaDB→Milvus、Redis 集群化、加 API 网关/WAF、Prometheus 监控、A/B 测试框架 |
| "这个项目最大的技术挑战是什么？" | 在 LLM 的「自由」和企业的「管制」之间找平衡——护栏阻断危险输入、工具注册表限制能力边界、只读 SQL 防止数据污染、全量审计确保可追溯 |
| "AI PM 和传统 PM 最大的区别？" | AI PM 要管理不确定性——LLM 输出不可控，需要用评测体系量化质量、用 Bad Case 分析驱动迭代、用护栏定义安全边界 |
| "你怎么评估一个 AI 功能做得好不好？" | 多维度评测——不只看答案对不对，还要测路由、工具选择、护栏拦截、引用质量、延迟、成本。然后用 Bad Case 分析找根因 |

#### Day 5-6：模拟面试

找人（朋友/同事/你自己对着镜子）听你讲：
1. 2 分钟项目介绍
2. 深挖一个模块（建议安全护栏，最体现 PM 思维）
3. 回答上面的追问

录下来，回放，检查：
- 有没有用了对方听不懂的技术名词没解释？
- 有没有逻辑跳跃？
- 有没有讲到亮点但没说「为什么这个很重要」？

#### Day 7：查漏补缺

重读 `docs/project-tutorial.html`，标记出你还讲不清楚的部分，针对补。

---

## AI 应用工程师路线（第 3-8 周）

> 如果你目标是 AI 应用开发岗，走这条。**需要写代码、打断点、逐行读源码**。

---

### 第三周：LLM 开发基础（不碰项目代码）

> 这周的目的是：脱离项目，先学会用 OpenAI SDK。项目里的 Agent 就是这些基础操作的组合。

#### Day 1-2：最简 LLM 调用

**操作**：新建 `learn/01_basic_llm.py`，写以下脚本并跑通：

```python
from openai import OpenAI

client = OpenAI(api_key="sk-xxx", base_url="https://api.openai.com/v1")

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "你是一个电商客服助手。"},
        {"role": "user", "content": "退款一般需要几天？"}
    ],
    temperature=0.3,
    max_tokens=200
)

print(response.choices[0].message.content)
print(f"用了 {response.usage.total_tokens} tokens")
```

**关键实验**（每个改一行跑一次，观察输出变化）：
- 把 `temperature` 改成 1.5，看输出变多随机
- 把 `max_tokens` 改成 20，看输出被截断
- 把 system prompt 改成「你是一个粗暴的客服，每句话都用感叹号结尾」

**检验**：能说清楚 `temperature`、`max_tokens`、`system prompt` 三个参数各自控制什么。

---

#### Day 3-4：Function Calling

**操作**：新建 `learn/02_function_calling.py`：

```python
from openai import OpenAI
import json

client = OpenAI(api_key="sk-xxx", base_url="https://api.openai.com/v1")

# 定义一个工具
tools = [{
    "type": "function",
    "function": {
        "name": "get_order_status",
        "description": "查询某个订单的状态",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单ID"}
            },
            "required": ["order_id"]
        }
    }
}]

# 模拟订单数据库
orders = {"A001": "已发货", "A002": "处理中", "A003": "已签收"}

messages = [{"role": "user", "content": "订单 A002 到哪了？"}]

# 第一轮：LLM 决定要不要调工具
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=messages,
    tools=tools
)

msg = response.choices[0].message
print(f"LLM 想调工具吗？ {msg.tool_calls}")

# 如果 LLM 要调工具
if msg.tool_calls:
    tool_call = msg.tool_calls[0]
    func_name = tool_call.function.name
    func_args = json.loads(tool_call.function.arguments)
    print(f"调 {func_name}({func_args})")

    # 执行工具
    if func_name == "get_order_status":
        result = orders.get(func_args["order_id"], "未找到")

    # 把结果告诉 LLM
    messages.append({"role": "assistant", "tool_calls": [tool_call]})
    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

    # 第二轮：LLM 根据结果生成最终答案
    final = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages
    )
    print(f"最终答案：{final.choices[0].message.content}")
```

**关键实验**：
- 把 `order_id` 改成写成不存在的，看 LLM 怎么处理
- 再加一个工具 `get_user_info`，让 LLM 在「查用户信息」时自动选对工具
- 故意不传 `order_id`，看 LLM 会不会追问

**检验**：能解释「为什么代码里有两轮 LLM 调用」——第一轮让 LLM 决定调什么工具，第二轮让 LLM 根据工具结果生成答案。

---

#### Day 5：SSE 流式输出

**操作**：新建 `learn/03_stream.py`，把 Day 1 的脚本改成流式：

```python
from openai import OpenAI

client = OpenAI(api_key="sk-xxx", base_url="https://api.openai.com/v1")

stream = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "告诉我退款流程"}],
    stream=True,                    # 关键：开启流式
    stream_options={"include_usage": True}  # 最后返回 token 用量
)

# 逐 token 打印
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
    # usage 在最后一个 chunk 里
    if chunk.usage:
        print(f"\n\n用了 {chunk.usage.total_tokens} tokens")
```

**检验**：能解释 SSE 和普通 HTTP 请求的区别——普通是你问一句它答一句，SSE 是它一边生成你一边收。

---

#### Day 6-7：FastAPI 端点

**操作**：新建 `learn/04_fastapi_chat.py`，写一个最简单的聊天 API：

```python
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import uvicorn

app = FastAPI()
client = OpenAI(api_key="sk-xxx", base_url="https://api.openai.com/v1")

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
def chat(req: ChatRequest):
    """普通版本：一次性返回"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": req.message}]
    )
    return {"answer": response.choices[0].message.content}

from fastapi.responses import StreamingResponse

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式版本"""
    def generate():
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": req.message}],
            stream=True
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield f"data: {chunk.choices[0].delta.content}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

用 Postman 或 curl 分别调两个端点，感受区别。

**检验**：
- [ ] 用 Postman POST `/chat`，能看到一次返回完整答案
- [ ] 用 Postman POST `/chat/stream`，能看到逐字输出
- [ ] 能解释：项目 `runtime.py` 里的 `/api/chat` 和 `/api/chat/stream` 就对应这两个

---

### 第四周：理解初始化 + 读通 RAG

#### Day 1：跑通项目并验证

**操作**：
1. 确保项目按第一阶段的步骤能跑起来
2. 用浏览器 DevTools → Network 面板，观察一次对话请求
3. 看看实际发出的请求体长什么样，响应体长什么样

**检验**：能找出一次请求的完整 Request/Response JSON。

---

#### Day 2-3：理解初始化流程（依赖注入）

**操作**：
1. 打开 `app/runtime_state.py`，找到 `initialize_runtime()` 函数
2. 从第一行开始逐行读，理解 14 个初始化步骤
3. 关键问题——每一步为什么依赖前一步？比如：
   - 为什么 `Settings` 必须第一个？
   - 为什么 `Orchestrator` 在第 11 步而不是更早？
   - 为什么 `Orchestrator` 构造时能把前面 10 步创建的所有对象传入？

4. 打开 `app/runtime.py`，找到模块底部的 `__getattr__` 函数，理解这行代码的意义：
   ```python
   # 当你写 from app.runtime import orchestrator
   # Python 会自动调用 __getattr__("orchestrator") 而不是直接导入
   ```

**检验**：能脱稿讲出 14 步初始化顺序，每步创建什么对象、为什么在这个位置。

---

#### Day 4-5：精读 RAG 检索（最重要）

**操作**：
1. 打开 `app/rag.py`，定位到 `LangChainRAGService` 类
2. 精读 `query()` 方法（这是项目 RAG 的核心），逐行加注释

**精读路径**：

```
query(question, category, top_k)
  │
  ├─ 1. 如果没有 LLM 或向量库不可用 → 回退到词法搜索
  │
  ├─ 2. _vector_search(query, top_k)        ← 向量检索
  │     └─ ChromaDB 的 collection.query()
  │     └─ _fetch_parent_context()            ← 小块的父块
  │
  ├─ 3. _lexical_search_results(query, top_k) ← 词法检索
  │
  ├─ 4. reciprocal_rank_fusion([向量结果, 词法结果]) ← RRF 融合
  │
  ├─ 5. 用 rag_prompt 拼装 context + question
  │
  └─ 6. llm.invoke(prompt)                   ← LLM 生成答案
        └─ compute_online_metrics()            ← 在线指标
```

**检验**：
- [ ] 能给 `query()` 的每一段代码写上中文注释（写下来，不是脑子里想）
- [ ] 能解释 Small-to-Big：为什么只嵌入小块、但返回大块？
- [ ] 能解释 RRF 公式：`score = 1/(60 + rank)`，为什么用排名不用分数？

---

#### Day 6-7：ChromaDB 动手实验

**操作**：新建 `learn/05_chromadb_demo.py`：

```python
import chromadb
from chromadb.utils import embedding_functions

# 创建本地 ChromaDB
client = chromadb.PersistentClient(path="./demo_chroma")

# 用 OpenAI embedding 函数
ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key="sk-xxx",
    model_name="text-embedding-3-small"
)

# 创建或获取 collection
collection = client.get_or_create_collection(
    name="demo_kb",
    embedding_function=ef
)

# 添加 3 段文档
collection.add(
    documents=[
        "退款需要提供订单截图和退款原因，审核通过后 3-5 个工作日到账。",
        "生鲜类商品不支持无理由退货，但如果收到时已经变质可以申请退款。",
        "订单发货后可以在物流页面查看实时配送进度。"
    ],
    ids=["doc1", "doc2", "doc3"]
)

# 查询
results = collection.query(
    query_texts=["我买的菜坏了怎么退"],
    n_results=2
)

print("匹配的文档：")
for i, doc in enumerate(results['documents'][0]):
    print(f"  [{results['distances'][0][i]:.3f}] {doc}")
# distance 越小越相关
```

**关键实验**：
- 把查询改成「快递到哪了」，看返回什么（应该返回 doc3）
- 再加 2 段内容相似的文档，看 ChromaDB 怎么区分
- 打印 `results` 的完整结构，理解 `ids`、`documents`、`distances`、`metadatas`

**检验**：能解释 ChromaDB 的 `add()` 存的不是原始文本，而是向量；`query()` 返回的是距离最近的向量对应的文本。

---

### 第五周：精读核心 Agent 链路（最重要的一周）

#### Day 1-2：路由决策（routing.py）

**操作**：
1. 打开 `app/routing.py`，全文约 150 行，逐行读
2. 重点关注：
   - `_rule_route()` 里的 6 条规则各自匹配什么关键词
   - 置信度怎么算的（为什么大部分返回 0.85 或 0.9）
   - `_llm_route()` 的 prompt 怎么写——LLM 路由的提示词长什么样
   - 回退逻辑：如果规则和 LLM 都失败了，为什么选 `multi_agent`

**在代码中找答案**：
```python
# 找这行——为什么阈值是 0.8？
if decision["confidence"] >= 0.80:
    return decision
```

**思考题**：如果用户在 Copilot 里选了「数据」模式（mode=function_call_agent），还会经过 AutoRouter 吗？在 `orchestrator.py` 里找答案。

**检验**：给一段你没见过的用户消息，能预测两条路由规则的结果，并说出置信度。

---

#### Day 3-4：Function Calling Agent 核心循环（重中之重）

**操作**：
1. 打开 `app/function_agent.py`，全文约 400 行
2. 按以下顺序精读，每段写注释：

**第一遍：理解工具定义**
```python
# 找到 _build_tools() 方法
# 理解 7 个工具各自的 name、description、parameters
# 思考：为什么 description 要写得这么详细？
```

**第二遍：理解安全护栏**
```python
# 找到 _guardrail() 方法
# 理解它怎么检查 4 类危险模式
# 理解命中后返回什么（mode: "guardrail", review_required: True）
```

**第三遍：理解 ReAct 循环（核心中的核心）**
```python
# 找到 respond() 方法，按执行顺序读：
# 
# 1. guardrail 检查
#    if guard := self._guardrail(message):
#        return guard
#
# 2. 如果没有 LLM，走确定性回退
#    if self.client is None:
#        return self._respond_without_llm(message, session_id)
#
# 3. 构建消息和工具列表
#    messages = [system_prompt, user_message]
#    tools = self._build_tools()
#
# 4. 第 1 轮 LLM 调用
#    response = self.client.chat.completions.create(
#        model=..., messages=messages, tools=tools
#    )
#
# 5. 检查 LLM 是否调用了工具
#    if msg.tool_calls:
#        for tool_call in msg.tool_calls:
#            result = self._execute_tool(name, args)
#            self._collect_tool_payload(name, result, payload)
#        把工具结果追加到 messages
#
# 6. 第 2 轮 LLM 调用（带工具结果）
#    response2 = self.client.chat.completions.create(...)
#
# 7. 提取最终答案 + 表格 + 指标
```

**第四遍：理解降级策略**
```python
# 找到 _respond_without_llm() 
# 理解它怎么用正则匹配来做确定性路由
# 这是「没有 LLM 时系统还能工作」的关键
```

**思考题**：
- 为什么最多 2 轮工具调用而不是无限循环？
- 如果 LLM 返回了不存在的工具名怎么办？
- 工具调用和工具结果怎么拼进 messages 才能让 LLM 理解？

**检验**：
- [ ] 能给 `respond()` 逐行写注释
- [ ] 能画出 ReAct 循环的时序图（LLM → 工具 → LLM → 答案）
- [ ] 能解释 `_respond_without_llm()` 的降级策略

---

#### Day 5：SQL 查询层（ticket_store.py）

**操作**：
1. 打开 `app/ticket_store.py`，找到 `ReadOnlySQLiteStore.query_ticket_details()`
2. 理解：
   - `_where_clause()` 怎么根据用户查询构建 SQL WHERE 条件
   - 为什么用参数化查询（`?` 占位符），不用字符串拼接
   - `validate_readonly_sql()` 怎么保证只读安全
   - 返回值的结构：`{"rows": [...], "metrics": [...], "sql_preview": "..."}`

**检验**：能解释「如果用字符串拼接 SQL 会有什么安全风险」，以及参数化查询怎么防。

---

#### Day 6-7：串联 + 断点调试

**操作**：
1. 在 `app/function_agent.py` 的 `respond()` 方法中加 `breakpoint()` 或 print
   - 第 1 轮 LLM 调用前后
   - 工具执行前后
   - 第 2 轮 LLM 调用前后
2. 用 Postman 发请求：`POST /api/chat {"message": "查高赔付订单", "mode": "function_call_agent"}`
3. 观察每一步的变量值

**打印关键变量**：
```python
# 在 respond() 里临时加：
print(f"[DEBUG] messages: {messages}")
print(f"[DEBUG] tool_calls: {msg.tool_calls}")
print(f"[DEBUG] tool result: {result}")
print(f"[DEBUG] final content: {final.choices[0].message.content}")
```

**检验**：能从头到尾复述一次完整请求的数据流，不看代码：
1. 用户消息长什么样
2. LLM 第一轮返回了什么 tool_call
3. 工具怎么执行、返回什么
4. LLM 第二轮怎么用工具结果生成答案
5. 最终答案怎么组装成 ChatResponse

---

### 第六周：其余 Agent 模式 + 前端

#### Day 1-2：SQL + RAG 链

**操作**：
1. 打开 `app/orchestrator.py`，找到 `_respond_sql_rag_chain()`
2. 理解它和纯 function_call_agent 的区别：
   - 它不走 Function Calling 循环
   - 它直接调 `sql_store.query_ticket_details()` 查 SQL
   - 然后把 SQL 结果作为上下文去调 RAG
   - 最后用 LLM 综合 SQL 结果 + RAG 结果

**检验**：能画出 sql_rag_chain 的数据流：用户消息 → 重写 → SQL → RAG → LLM 综合 → 答案。

---

#### Day 3：多 Agent 协作（multi_agent.py）

**操作**：
1. 打开 `app/multi_agent.py`
2. 理解 5 个节点的 LangGraph 图：
   - `supervisor_node`：分类，决定用哪几个子 Agent
   - `data_agent_node`：调 function_call_agent
   - `policy_agent_node`：调 RAG
   - `risk_agent_node`：调 analytics
   - `synthesis_node`：合并所有结果

3. 重点理解条件边——不是所有请求都走全部节点：
   ```python
   # supervisor 判断只需要 data + policy，就不会走 risk
   ```

**检验**：能说出 multi_agent 和 function_call_agent 在什么场景下选哪个。

---

#### Day 4：模块化 RAG（pipeline + modules）

**操作**：
1. 读 `app/pipeline.py` 的 `ModularRAGPipeline.run()`——理解它怎么遍历模块
2. 读 `app/agentic_controller.py`——理解它怎么决定激活哪些模块
3. 挑 2-3 个感兴趣的模块精读（建议 `crag.py` 和 `self_rag.py`）

**检验**：能解释「为什么模块化 RAG 比写死一条 RAG 链更灵活」。

---

#### Day 5-6：前端核心

**操作**：
1. 打开 `frontend/src/stores/chat.ts`，精读 `sendMessage()` 方法
   - 理解它怎么调 `streamChat`
   - 理解流失败时怎么回退到 `postChat`
2. 打开 `frontend/src/api/client.ts`，精读 `streamChat()`
   - 理解 SSE 事件的 4 种类型：`token`、`status`、`final`、`error`
   - 理解 buffer 怎么处理跨块数据
3. 打开 `frontend/src/views/CopilotView.vue`，理解 UI 怎么连接 store

**检验**：能画出前端的完整数据流：用户键入 → store.sendMessage → streamChat → SSE 解析 → onToken 更新 UI → onFinal 显示证据。

---

#### Day 7：串讲 + 查漏

**操作**：
1. 画出完整的系统架构图（不看资料，自己画）
2. 画出完整的请求生命周期图（7 步 + 每步的文件/函数）
3. 标记出你还讲不清楚的部分，回到对应文件重读

---

### 第七周：安全 + 文档处理 + 评测

#### Day 1-2：安全全链路

**操作**：
追踪一次请求的安全检查全过程：
```
http_auth.py      → JWT 验证（你是谁）
permissions.py    → RBAC 检查（你能不能用这个模式）
domain.py         → 护栏检查（你的消息是否危险）
schemas.py        → Pydantic 参数验证（工具参数是否合法）
ticket_store.py   → 只读 SQL 校验（SQL 是否有写操作）
audit_stores.py   → 全量审计记录
```

**检验**：能说清楚 6 层安全分别防什么攻击（身份伪造、越权、注入、数据篡改、SQL 注入、事后无据可查）。

---

#### Day 3-4：文档处理流水线

**操作**：
1. 按顺序读 `app/document/` 下的文件：
   - `parser.py` → 门面，按扩展名路由到解析器
   - `parsers/pdf_parser.py` → PyMuPDF 提取
   - `cleaner.py` → 去噪/去重/质量/冲突
   - `chunking.py` → 4 种分块策略
   - `lineage.py` → 块级血缘
   - `version.py` → Git 风格版本管理
   - `audit.py` → 文档操作审计
2. 上传一个 PDF 到前端文档管理，观察各阶段的输出

**检验**：能画出文档处理 6 步流水线，每步标注输入/输出类型。

---

#### Day 5-6：评测框架

**操作**：
1. 读 `scripts/evaluate_rag.py` 的 `evaluate()` 函数，理解评测怎么组织
2. 读 `eval/agent_eval_cases.json`，挑 5 个 case 看结构
3. 读 `eval/v2_eval_report.md`，理解每个指标的含义

**检验**：能解释评测为什么分 4 类（路由/工具/护栏/记忆），各类测什么。

---

#### Day 7：跑一次完整评测

```bash
python scripts/evaluate_rag.py
```

看输出，找到哪些 case 通过了、哪些失败了，挑一个失败的 case 分析根因。

---

### 第八周：面试准备 + 扩展练习

#### Day 1-2：精读回顾

**操作**：
1. 重读 `app/function_agent.py` 的 `respond()` 和 `respond_stream()`
2. 重读 `app/rag.py` 的 `LangChainRAGService.query()`
3. 确保能脱稿讲这两段代码的完整逻辑

---

#### Day 3-4：动手扩展

做两个小练习，验证你的理解：

**练习 1：加一个新工具**
- 在 `function_agent.py` 的 `_build_tools()` 里加一个 `query_product_info` 工具
- 在 `_execute_tool()` 里实现它（从 products 表查数据）
- 写一个测试用例验证

**练习 2：加一种新的护栏规则**
- 在 `domain.py` 里加一组新规则（比如「检测用户尝试绕过限制的请求」）
- 在 `_guardrail()` 里加上检查
- 测试：输入一段绕过话术，验证能被拦截

---

#### Day 5-6：面试题练习

| 面试官可能问 | 你要能答出 |
|------------|----------|
| "ReAct 循环怎么实现的？" | 逐行讲 `respond()`——护栏→构建工具→第1轮LLM→执行工具→第2轮LLM→组装答案 |
| "混合检索怎么做的？" | 向量检索 + 词法检索 → RRF 融合 → LLM 生成 |
| "SSE 流式怎么实现的？" | 前端 `streamChat()` 用 ReadableStream 读 SSE 事件 + 后端 `respond_stream()` 用 `stream=True` 逐 chunk yield |
| "怎么保证 Agent 不干坏事？" | 6 层安全——认证/鉴权/护栏/只读SQL/人工复核/审计 |
| "如果 LLM 不可用怎么办？" | 确定性回退——`_respond_without_llm()` 用规则匹配代替 LLM 推理 |
| "怎么评估 AI 好不好？" | 4 维评测——路由/工具/护栏/记忆 + 在线指标（多样性/置信度/覆盖率） |
| "RAG 检索不准怎么办？" | CRAG 检测低质量检索并重新检索、CrossEncoder 重排序、Self-RAG 反思答案 |

---

#### Day 7：模拟面试

找人或对着镜子，完整讲一遍：
1. 3 分钟项目介绍（架构 + 核心链路）
2. 深挖 ReAct 循环实现
3. 回答 5 道以上的追问

录下来回放，检查技术细节有没有说错。

---

## 附录 A：核心文件阅读顺序速查

| 优先级 | 文件 | 预计耗时 | 要读懂什么 |
|--------|------|---------|----------|
| 🔴 P0 | `app/function_agent.py` | 4h | ReAct 循环、安全护栏、工具执行、降级策略 |
| 🔴 P0 | `app/orchestrator.py` | 3h | 5 种模式分派、审计+复核入队、响应增强 |
| 🔴 P0 | `app/rag.py` | 3h | 向量检索、词法检索、RRF 融合、Small-to-Big |
| 🔴 P0 | `app/routing.py` | 1.5h | 规则路由 6 条、LLM 路由 prompt、回退逻辑 |
| 🟡 P1 | `app/runtime_state.py` | 1h | 14 步初始化、依赖注入 |
| 🟡 P1 | `app/multi_agent.py` | 2h | LangGraph 5 节点图、条件边、synthesis |
| 🟡 P1 | `app/pipeline.py` | 0.5h | 模块遍历、`should_activate`/`execute` |
| 🟡 P1 | `app/agentic_controller.py` | 1h | LLM 决策 vs 规则决策 |
| 🟡 P1 | `app/ticket_store.py` | 1.5h | 参数化查询、只读校验、SQL 构建 |
| 🟡 P1 | `app/schemas.py` | 0.5h | Pydantic 工具参数验证 |
| 🟡 P1 | `app/domain.py` | 0.5h | 4 类护栏模式、分类函数 |
| 🟡 P1 | `frontend/src/stores/chat.ts` | 1h | sendMessage、流式回退 |
| 🟡 P1 | `frontend/src/api/client.ts` | 1h | streamChat SSE 解析 |
| 🟢 P2 | `app/reflection.py` | 0.5h | 规则检查 + LLM-as-judge |
| 🟢 P2 | `app/query_rewrite.py` | 0.5h | 后续问题重写 |
| 🟢 P2 | `app/query_planner.py` | 0.5h | 复杂查询分解 |
| 🟢 P2 | `app/modules/crag.py` | 0.5h | 检索质量评估+重试 |
| 🟢 P2 | `app/modules/self_rag.py` | 0.5h | 答案反思+重新生成 |
| 🟢 P2 | `app/modules/knowledge_graph.py` | 1h | 三元组提取+BFS |
| 🟢 P2 | `app/document/parser.py` | 0.5h | 门面路由 |
| 🟢 P2 | `app/document/cleaner.py` | 0.5h | 4 步清洗 |
| 🟢 P2 | `app/document/chunking.py` | 0.5h | 4 种分块策略 |
| 🟢 P2 | `app/audit_stores.py` | 0.5h | 审计+复核+反馈存储 |
| 🟢 P2 | `app/permissions.py` | 0.25h | 角色-权限映射 |
| ⚪ P3 | `tests/*` | 需要时 | 各种模块的用法示例 |
| ⚪ P3 | `eval/*` | 需要时 | 评测用例和指标定义 |
| ⚪ P3 | `frontend/src/views/*` | 需要时 | 各页面的 UI 逻辑 |

---

## 附录 B：学习检验清单

每周结束前，对照检查：

### AI PM 路线

- [ ] Week 3：能脱稿讲项目是什么、5 种模式分别解决什么业务问题、为什么要有护栏
- [ ] Week 4：能分析 3 个 Bad Case 的根因并提改进方案、能解释评测为什么分 4 类
- [ ] Week 5：能流畅做 2 分钟+5 分钟项目介绍、能回答所有追问

### AI 应用工程师路线

- [ ] Week 3：能独立写出 Function Calling + SSE 的 demo 脚本
- [ ] Week 4：能逐行给 `rag.py` 的 `query()` 写注释、能解释 Small-to-Big 和 RRF
- [ ] Week 5：能逐行给 `function_agent.py` 的 `respond()` 写注释、能画 ReAct 时序图
- [ ] Week 6：能讲清楚其余 4 种模式的实现差异、能画前端数据流
- [ ] Week 7：能讲清楚 6 层安全、文档处理 6 步流水线、评测 4 类指标
- [ ] Week 8：能在项目里加一个新工具和新护栏规则、能脱稿讲核心链路

---

## 附录 C：本项目 23 个核心面试问题及回答要点

### 架构类

**Q1：这个项目的整体架构是什么样的？**
> FastAPI（后端）+ Vue 3（前端）+ SQLite/MySQL（数据）+ ChromaDB（向量）+ OpenAI API（LLM）。前端发 SSE 请求 → FastAPI 验证 JWT → Orchestrator 路由分派 → Agent 执行 → 审计记录 → 返回。共 5 种 Agent 模式 + 6 层安全防护。

**Q2：为什么有 5 种 Agent 模式，而不是一个？**
> 不同场景对不同能力。纯数据查询不需要 RAG 的开销，纯政策咨询不需要 Function Calling 的复杂度。分开设计降低延迟、提高准确率、方便独立调优。

**Q3：自动路由怎么决定用哪个模式的？**
> 两级：规则路由（正则+关键词，80% 场景，零延迟，置信度 ≥0.8 直接采用）+ LLM 路由（分类提示词，处理模糊意图）。都失败则回退到 multi_agent。

---

### Agent 类

**Q4：ReAct 循环怎么实现的？**
> `function_agent.py` 的 `respond()` 方法：护栏检查 → 构建 7 个工具 → 第 1 轮 LLM 调用（带工具列表）→ 如果 LLM 返回 tool_call → 执行工具（带 Pydantic 参数验证）→ 将工具结果注入 messages → 第 2 轮 LLM 调用 → 生成最终答案。最多 2 轮。

**Q5：如果 LLM 不调用工具怎么办？**
> 有 `_should_fallback_to_tools()` 检测——如果消息明显需要工具但 LLM 没调用（比如消息包含订单 ID 但 LLM 没有调 `query_order_status`），代码自动回退到确定性规则选择并执行工具。

**Q6：多 Agent 协作怎么做的？**
> `multi_agent.py` 用 LangGraph 定义了 5 个节点的状态图：Supervisor 分类意图 → Data Agent / Policy Agent / Risk Agent 并行执行 → Synthesis 合并。条件边确保只调用需要的 Agent。

---

### RAG 类

**Q7：RAG 检索怎么保证准确性？**
> 5 层：混合检索（向量+词法）→ RRF 融合 → CrossEncoder 重排序 → CRAG 纠正（质量分低则重新检索）→ Self-RAG 反思（答案不好则重新生成）。

**Q8：Small-to-Big 分块有什么好处？**
> 小块做向量匹配（精度高），大父块给 LLM 提供上下文（生成质量好）。只嵌入小块节省 Embedding 成本。

**Q9：RRF 融合怎么做？为什么不用分数直接加权？**
> `score = 1/(60+rank)`，对不同排序列表的排名求和。好处是不依赖分数量纲——向量检索的余弦距离和词法检索的重叠分数不可直接比较。

---

### 安全类

**Q10：6 层安全防护怎么设计的？**
> JWT 认证（是谁）→ RBAC 鉴权（能干什么）→ 安全护栏（消息是否危险）→ Pydantic 工具验证（参数是否合法）→ 只读 SQL 校验（SQL 是否有写操作）→ 人工复核（高风险入队）→ 全量审计（可追溯）。

**Q11：安全护栏拦什么？**
> 4 类：写操作意图（退款/删除/修改）、提示注入（ignore previous/system prompt）、数据泄露（显示所有用户/dump）、社会工程（我是管理员/CEO/紧急情况）。

**Q12：怎么保证 SQL 不被注入？**
> 三重：① 参数化查询（`?` 占位符，不用字符串拼接）；② `validate_readonly_sql()` 强制只允许 SELECT/WITH；③ 禁止多条语句（防止分号分隔追加恶意 SQL）。

---

### 工程实践类

**Q13：如果 LLM 服务挂了怎么办？**
> `_respond_without_llm()` 提供确定性回退——用规则匹配自动选择和执行工具，不做生成式回答。同时所有组件都有降级路径：Redis 不可用→进程内存、LangGraph 不可用→函数式编排。

**Q14：SSE 流式怎么实现的？**
> 后端：`stream=True` 逐 chunk yield，每个 chunk 包成 `event: token\ndata: ...\n\n`。前端：`ReadableStream` 逐块读取，buffer 缓冲跨块数据，按双换行拆分 SSE 事件，根据 event 类型分发到 onToken/onStatus/onFinal。

**Q15：Token 用量和成本怎么算的？**
> 从 OpenAI 响应的 `usage` 字段提取 prompt_tokens 和 completion_tokens，用 `Settings` 里配置的每千 token 价格计算：`prompt_cost = tokens × price_per_1k`。

---

### 评测类

**Q16：评测体系怎么设计的？**
> 分 4 类独立评测——路由（测意图识别）、工具（测工具选择）、护栏（测安全拦截）、记忆（测多轮对话）。每类有独立的测试用例和预期结果。

**Q17：Bad Case 怎么分析和处理？**
> 分类打标签 → 找根因（prompt 问题？规则漏了？RAG 检索偏了？LLM 幻觉？）→ 按频次 × 严重程度排序 → 针对性修复 → 回归验证。

---

### 前端类

**Q18：前端状态管理怎么设计的？**
> 5 个 Pinia Store——auth（JWT/用户）、app（仪表盘数据）、chat（对话状态+流式）、audit（审计日志）、review（复核队列）。chat store 是核心，管理 SSE 流式接收和降级回退。

**Q19：前端怎么处理 SSE 流式传输？**
> `streamChat()` 用 `fetch` + `ReadableStream`，buffer 按双换行拆分 SSE 事件，解析 `event:` 和 `data:` 行，分派到 onToken（追加文本）/ onStatus（更新阶段）/ onFinal（显示证据）。流失败自动回退到普通 POST。

---

### 扩展类

**Q20：如果要加一个新工具（比如查库存），怎么做？**
> 4 步：① `schemas.py` 加参数模型；② `function_agent.py` 的 `_build_tools()` 加工具定义；③ `_execute_tool()` 加实现；④ `tool_registry.py` 注册权限。

**Q21：如果要支持新的文件类型解析，怎么做？**
> 继承 `BaseParser`，实现 `parse()` 和 `supported_extensions()`，然后在 `DocumentParser.__init__()` 注册一行。

**Q22：生产环境和现在的原型有什么区别？**
> SQLite→PostgreSQL/MySQL、ChromaDB→Milvus/Pinecone、Redis 集群化、加 API 网关/WAF、Prometheus+Grafana 监控、A/B 测试框架、CI/CD 完善。

**Q23：你觉得这个项目最值得优化的 3 个点？**
> ① 路由准确率 86.7%→补充规则覆盖边缘 case；② 护栏拦截率 83.3%→加社会工程检测；③ 记忆准确率 50%→改进上下文重写。

---

> **最后一条建议**：学这个项目最有效的办法不是看文档，而是**改代码**。改一行，跑一次，看输出哪变了。改 20 次之后，你比作者更懂这个项目。
