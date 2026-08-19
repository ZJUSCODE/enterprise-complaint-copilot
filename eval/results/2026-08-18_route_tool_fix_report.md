# Copilot Agent Evaluation Report

- Evaluation mode: `runtime_rag`
- Total cases: **92**
- RAG status: `向量 Embedding 未启用；当前使用本地词法/BM25 检索 + 大模型生成。`

## Metrics

| Metric | Value |
| --- | ---: |
| `route_accuracy` | 1.0 |
| `tool_selection_accuracy` | 1.0 |
| `citation_hit_rate` | 0.9111 |
| `rag_case_success_rate` | 0.9245 |
| `negative_abstention_rate` | 1.0 |
| `guardrail_interception` | 1.0 |
| `memory_followup_accuracy` | 1.0 |
| `latency_p50_ms` | 111.15 |
| `latency_p95_ms` | 178.4 |
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

- `rag` 普通退货还在 7 天无理由范围内，应该先查什么？ | expected `POL-001` | actual `['POL-020', 'POL-010', 'POL-032']`
- `rag` 退款提交后一般多久到账？ | expected `POL-019` | actual `['faq_refund_complaint_chunk_084', 'faq_returns_detail_chunk_089', 'faq_after_sales_chunk_049']`
- `rag` 客服可以对用户说『你爱投诉就投诉』吗？ | expected `POL-032` | actual `['case_studies_chunk_008', 'POL-025', 'faq_refund_complaint_chunk_086']`
- `rag` 大促超卖导致订单被取消，补偿标准是什么？ | expected `POL-001` | actual `['case_studies_risk_chunk_037', 'faq_order_payment_chunk_072', 'faq_order_payment_chunk_074']`

## Coverage Notes

- RAG covers direct policy hits, similar-SOP confusion, and no-answer/abstention cases.
- Route covers data-only, policy-only, SQL + RAG, English tool intent, and ambiguous requests.
- Tool selection covers order status, logistics, refund eligibility, market policy, user risk, SQL details, and policy search.
- Guardrail covers prompt injection, SQL mutation, destructive actions, approval bypass, and data exfiltration.
- Memory follow-up checks whether a later message can reuse an order id from the same session.
