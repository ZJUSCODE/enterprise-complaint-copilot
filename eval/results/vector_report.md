# Copilot Agent Evaluation Report

- Evaluation mode: `runtime_rag`
- Total cases: **92**
- RAG status: `ready`

## Metrics

| Metric | Value |
| --- | ---: |
| `route_accuracy` | 0.9333 |
| `tool_selection_accuracy` | 0.9 |
| `citation_hit_rate` | 0.5556 |
| `rag_case_success_rate` | 0.6226 |
| `negative_abstention_rate` | 1.0 |
| `guardrail_interception` | 1.0 |
| `memory_followup_accuracy` | 1.0 |
| `latency_p50_ms` | 2165.66 |
| `latency_p95_ms` | 5350.19 |
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

- `rag` 普通退货还在 7 天无理由范围内，应该先查什么？ | expected `POL-001` | actual `['case_studies_escalation_chunk_016', 'sop_beauty_cosmetics_chunk_126', 'sop_warehouse_receiving_chunk_353']`
- `rag` 3C 数码拆封后出现质量问题，应该怎么处理？ | expected `POL-003` | actual `['sop_3c_digital_chunk_099', 'sop_refund_process_chunk_318', 'case_studies_chunk_001']`
- `rag` 水果签收后发现腐烂，用户提供照片时应该走补发还是退款？ | expected `POL-004` | actual `['case_studies_chunk_002', 'sop_evidence_standards_chunk_166', 'sop_refund_process_chunk_316']`
- `rag` 定制刻字的商品签收后想退，能按 7 天无理由处理吗？ | expected `POL-010` | actual `['case_studies_service_chunk_038', 'case_studies_escalation_chunk_016', 'faq_returns_detail_chunk_093']`
- `rag` 鲜活易腐的生鲜类商品支持无理由退货吗？ | expected `POL-010` | actual `['sop_issue_matrix_chunk_217', 'faq_common_chunk_057', 'sop_issue_matrix_chunk_253']`
- `rag` 手机 10 天内出现性能故障，按三包应该怎么处理？ | expected `POL-012` | actual `['sop_warehouse_receiving_chunk_353', 'case_studies_chunk_001', 'sop_issue_matrix_chunk_253']`
- `rag` 一箱水果 70% 烂了，按生鲜赔付分级应该怎么处理？ | expected `POL-013` | actual `['sop_fresh_food_chunk_197', 'case_studies_chunk_002', 'sop_complaint_escalation_chunk_144']`
- `rag` 冷链包裹签收时已经化冻，责任怎么判定？ | expected `POL-014` | actual `['sop_3c_digital_chunk_098', 'sop_fresh_food_chunk_191', 'sop_claim_settlement_chunk_135']`
- `rag` 衣服吊牌剪了还能无理由退货吗？ | expected `POL-015` | actual `['faq_common_chunk_056', 'faq_common_chunk_057', 'sop_return_execution_chunk_326']`
- `rag` 大件家具签收后发现断裂，应该怎么处理？ | expected `POL-016` | actual `['sop_complaint_escalation_chunk_144', 'case_studies_chunk_009', 'sop_fresh_food_chunk_197']`
- `rag` 食品里发现异物，应该按什么流程处理？ | expected `POL-018` | actual `['sop_logistics_chunk_272', 'case_studies_escalation_chunk_017', 'sop_virtual_goods_chunk_346']`
- `rag` 退款提交后一般多久到账？ | expected `POL-019` | actual `['faq_after_sales_chunk_048', 'faq_refund_complaint_chunk_084', 'faq_after_sales_chunk_052']`
- `rag` 无理由退货的运费应该谁承担？ | expected `POL-020` | actual `['POL-050', 'faq_common_chunk_057', 'faq_after_sales_chunk_052']`
- `rag` 快递确认丢件了，客服应该怎么处理？ | expected `POL-021` | actual `['sop_logistics_chunk_276', 'faq_quality_after_sale_chunk_080', 'faq_common_chunk_059']`
- `rag` 买完 3 天降价了能申请补差价吗？ | expected `POL-022` | actual `['sop_3c_digital_chunk_095', 'faq_common_chunk_061', 'sop_warehouse_receiving_chunk_353']`
- `rag` 用户要求删除全部个人信息，应该走什么流程？ | expected `POL-024` | actual `['sop_issue_matrix_chunk_253', 'case_studies_risk_chunk_034', 'sop_warehouse_receiving_chunk_353']`
- `rag` 用户说要投诉到 12315，一线客服应该怎么办？ | expected `POL-025` | actual `['sop_issue_matrix_chunk_253', 'faq_after_sales_chunk_054', 'case_studies_escalation_chunk_016']`
- `rag` 客服可以对用户说『你爱投诉就投诉』吗？ | expected `POL-032` | actual `['sop_after_sales_chunk_119', 'sop_service_escalation_detail_chunk_343', 'case_studies_escalation_chunk_016']`
- `rag` 大促期间物流延误几天才开始判定异常？ | expected `POL-002` | actual `['sop_fresh_food_chunk_189', 'sop_logistics_chunk_265', 'case_studies_chunk_007']`
- `rag` 大促超卖导致订单被取消，补偿标准是什么？ | expected `POL-001` | actual `['POL-040', 'case_studies_risk_chunk_037', 'sop_fresh_food_chunk_190']`
- `route` 最近的售后情况怎么样？有什么需要注意的？ | expected `langchain_rag` | actual `function_call_agent`
- `tool` 3C数码超过500元的退款需要哪些SOP依据？ | expected `search_policy_docs` | actual `query_refund_cases`

## Coverage Notes

- RAG covers direct policy hits, similar-SOP confusion, and no-answer/abstention cases.
- Route covers data-only, policy-only, SQL + RAG, English tool intent, and ambiguous requests.
- Tool selection covers order status, logistics, refund eligibility, market policy, user risk, SQL details, and policy search.
- Guardrail covers prompt injection, SQL mutation, destructive actions, approval bypass, and data exfiltration.
- Memory follow-up checks whether a later message can reuse an order id from the same session.
