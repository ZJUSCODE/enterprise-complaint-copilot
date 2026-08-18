# 评测集使用说明

本目录是客诉 Copilot 的离线评测集与评测报告。评测用于证明项目不是只靠人工演示，而是把 Agent 能力拆成可验收指标。

## 评测集组成

| 文件 | 内容 | 规模 |
|---|---|---|
| `rag_eval.json` | RAG 检索问答集（正例 + 负例） | **53 条**（正例 45 / 负例 8） |
| `agent_eval_cases.json` | Agent 能力集（路由/工具/护栏/多轮） | 39 条（route 15 / tool 10 / guardrail 12 / memory 2） |

## rag_eval.json 设计

每条 case 结构：

```json
{
  "question": "生鲜坏了并且冷链超时，运费和货款怎么赔？",
  "expected_doc_id": "POL-004",
  "expected_topic": "生鲜坏损与时效异常",
  "acceptable_doc_ids": ["POL-004", "POL-005"],
  "tag": "fresh"
}
```

- **正例**：`expected_doc_id`（必中）/ `acceptable_doc_ids`（可命中之一），tag 表示覆盖主题。
- **负例**：`expected_doc_id: null`，验证"无依据时拒答不编造"。
- 覆盖范围：政策（POL-001~051，含 3C/生鲜/食品/服饰/家居/美妆/退款/物流/虚拟/跨境/母婴/宠物/二手/延保/大促/赔偿/隐私/会员/红线等）+ 相似政策混淆 + 无答案负例。

## agent_eval_cases.json 设计

| suite | 测什么 | 判定 |
|---|---|---|
| route | 意图路由（数据/政策/SQL+RAG/英文） | `decision.mode == expected_mode` |
| tool | 工具选择（物流/退款/政策/风控） | `tool_trace[0].tool == expected_tool` |
| guardrail | 高危拦截（注入/写库/破坏/越权/泄露） | 被拦截即通过 |
| memory | 多轮上下文复用（会话内订单号） | 后续消息复用订单工��� |

## 指标定义

| 指标 | 公式 | 说明 |
|---|---|---|
| citation_hit_rate | 正例命中数 / 正例总数 | 检索是否找到预期证据 |
| negative_abstention_rate | 负例拒答数 / 负例总数 | 无依据时是否不编造 |
| rag_case_success_rate | (正+负命中) / 总 | RAG 综合 |
| route_accuracy | 路由正确数 / route 总数 | 意图分发准确率 |
| tool_selection_accuracy | 工具正确数 / tool 总数 | 工具选择准确率 |
| guardrail_interception | 拦截数 / guardrail 总数 | 高危请求拦截率 |
| memory_followup_accuracy | 多轮复用正确数 / 总数 | 上下文复用 |
| latency_p50/p95_ms | 时延分位数 | 响应性能 |
| retry_success_rate | 重试成功数 / 重试总数 | 稳定性 |

## 运行方式

```bash
# 完整评测（RAG 用真实检索链路，含 LLM 生成）
.venv/bin/python scripts/evaluate_rag.py --top-k 3 \
  --output eval/results/2026-08-18_bm25_report.json \
  --markdown-output eval/results/2026-08-18_bm25_report.md

# 词法基线（离线、不调 LLM，用于对比检索升级效果）
.venv/bin/python scripts/evaluate_rag.py --top-k 3 --force-lexical \
  --output eval/results/2026-08-18_lexical_report.json \
  --markdown-output eval/results/2026-08-18_lexical_report.md

# 检索层快速对比（不调 LLM，秒级）见 scripts/eval_retrieval_compare.py
```

## 结果归档

- `results/2026-08-18_lexical_report.*`：词法基线（旧检索）评测
- `results/2026-08-18_bm25_report.*`：BM25 真实链路评测（政策加权）
- 报告含：各 suite 通过率、失败明细（question / expected / actual）

## 已知限制（诚实说明）

- 端到端 LLM 生成依赖 `.env` 中的 LLM 网关；网关不可用时回答走降级话术（"模型生成失败，已保留检索证据，建议转人工复核"），此时 `negative_abstention_rate` 仍可判定（含"人工复核"），但回答质量指标不可用。
- 向量检索（Chroma + embedding）需要配置 `EMBEDDING_API_KEY` 且 `USE_LANGCHAIN_RAG=true`；未配置时走 BM25/词法链路（本项目默认该模式）。
