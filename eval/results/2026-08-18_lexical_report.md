# Copilot Agent Evaluation Report

- Evaluation mode: `lexical_offline`
- Total cases: **92**
- RAG status: `向量 Embedding 未启用；当前使用本地词法/BM25 检索 + 大模型生成。`

## Metrics

| Metric | Value |
| --- | ---: |
| `route_accuracy` | 0.8667 |
| `tool_selection_accuracy` | 0.8 |
| `citation_hit_rate` | 0.9111 |
| `rag_case_success_rate` | 0.9245 |
| `negative_abstention_rate` | 1.0 |
| `guardrail_interception` | 1.0 |
| `memory_followup_accuracy` | 1.0 |
| `latency_p50_ms` | 0.56 |
| `latency_p95_ms` | 0.9 |
| `retry_success_rate` | 1.0 |

## Case Counts

| Suite | Cases |
| --- | ---: |
| `rag_cases` | 53 |
| `route_cases` | 15 |
| `tool_cases` | 10 |
| `guardrail_cases` | 12 |
| `memory_cases` | 2 |

## Failed Cases

- `rag` 水果签收后发现腐烂，用户提供照片时应该走补发还是退款？ | expected `POL-004` | actual `['POL-019', 'POL-046', 'POL-001']`
- `rag` 无理由退货的运费应该谁承担？ | expected `POL-020` | actual `['POL-001', 'POL-010', 'POL-002']`
- `rag` 客服可以对用户说『你爱投诉就投诉』吗？ | expected `POL-032` | actual `['POL-025']`
- `rag` 大促超卖导致订单被取消，补偿标准是什么？ | expected `POL-001` | actual `['POL-029']`
- `route` 最近的售后情况怎么样？有什么需要注意的？ | expected `langchain_rag` | actual `function_call_agent`
- `route` Show me the latest complaint statistics and suggest policy changes | expected `sql_rag_chain` | actual `langchain_rag`
- `tool` 3C数码超过500元的退款需要哪些SOP依据？ | expected `search_policy_docs` | actual `query_refund_cases`
- `tool` 这个订单能不能退？退了之后物流怎么处理？ | expected `query_refund_eligibility` | actual `search_policy_docs`

## Coverage Notes

- RAG covers direct policy hits, similar-SOP confusion, and no-answer/abstention cases.
- Route covers data-only, policy-only, SQL + RAG, English tool intent, and ambiguous requests.
- Tool selection covers order status, logistics, refund eligibility, market policy, user risk, SQL details, and policy search.
- Guardrail covers prompt injection, SQL mutation, destructive actions, approval bypass, and data exfiltration.
- Memory follow-up checks whether a later message can reuse an order id from the same session.
