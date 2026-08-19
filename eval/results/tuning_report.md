# Copilot Agent Evaluation Report

- Evaluation mode: `runtime_rag`
- Total cases: **92**
- RAG status: `ready`

## Metrics

| Metric | Value |
| --- | ---: |
| `route_accuracy` | 0.9333 |
| `tool_selection_accuracy` | 0.9 |
| `citation_hit_rate` | 0.8889 |
| `rag_case_success_rate` | 0.9057 |
| `negative_abstention_rate` | 1.0 |
| `guardrail_interception` | 1.0 |
| `memory_followup_accuracy` | 1.0 |
| `latency_p50_ms` | 2871.25 |
| `latency_p95_ms` | 6148.0 |
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

- `rag` 普通退货还在 7 天无理由范围内，应该先查什么？ | expected `POL-001` | actual `['POL-020', 'sop_beauty_cosmetics_chunk_126', 'faq_after_sales_chunk_050']`
- `rag` 食品里发现异物，应该按什么流程处理？ | expected `POL-018` | actual `['case_studies_escalation_chunk_017', 'case_studies_chunk_006', 'faq_order_payment_chunk_072']`
- `rag` 退款提交后一般多久到账？ | expected `POL-019` | actual `['faq_refund_complaint_chunk_084', 'faq_returns_detail_chunk_089', 'faq_after_sales_chunk_049']`
- `rag` 客服可以对用户说『你爱投诉就投诉』吗？ | expected `POL-032` | actual `['sop_service_escalation_detail_chunk_343', 'sop_complaint_escalation_chunk_148', 'faq_refund_complaint_chunk_086']`
- `rag` 大促超卖导致订单被取消，补偿标准是什么？ | expected `POL-001` | actual `['case_studies_risk_chunk_037', 'faq_order_payment_chunk_072', 'sop_promotion_campaign_chunk_310']`
- `route` 最近的售后情况怎么样？有什么需要注意的？ | expected `langchain_rag` | actual `function_call_agent`
- `tool` 3C数码超过500元的退款需要哪些SOP依据？ | expected `search_policy_docs` | actual `query_refund_cases`

## Coverage Notes

- RAG covers direct policy hits, similar-SOP confusion, and no-answer/abstention cases.
- Route covers data-only, policy-only, SQL + RAG, English tool intent, and ambiguous requests.
- Tool selection covers order status, logistics, refund eligibility, market policy, user risk, SQL details, and policy search.
- Guardrail covers prompt injection, SQL mutation, destructive actions, approval bypass, and data exfiltration.
- Memory follow-up checks whether a later message can reuse an order id from the same session.
