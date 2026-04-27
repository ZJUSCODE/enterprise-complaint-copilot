# Copilot Agent Evaluation Report

- Evaluation mode: `lexical_offline`
- Total cases: **50**
- RAG status: `ready`

## Metrics

| Metric | Value |
| --- | ---: |
| `route_accuracy` | 1.0 |
| `tool_selection_accuracy` | 1.0 |
| `citation_hit_rate` | 1.0 |
| `rag_case_success_rate` | 1.0 |
| `negative_abstention_rate` | 1.0 |
| `guardrail_interception` | 1.0 |
| `memory_followup_accuracy` | 1.0 |
| `latency_p50_ms` | 0.1 |
| `latency_p95_ms` | 0.13 |
| `retry_success_rate` | 1.0 |

## Case Counts

| Suite | Cases |
| --- | ---: |
| `rag_cases` | 18 |
| `route_cases` | 12 |
| `tool_cases` | 8 |
| `guardrail_cases` | 10 |
| `memory_cases` | 2 |

## Failed Cases

- None.

## Coverage Notes

- RAG covers direct policy hits, similar-SOP confusion, and no-answer/abstention cases.
- Route covers data-only, policy-only, SQL + RAG, English tool intent, and ambiguous requests.
- Tool selection covers order status, logistics, refund eligibility, market policy, user risk, SQL details, and policy search.
- Guardrail covers prompt injection, SQL mutation, destructive actions, approval bypass, and data exfiltration.
- Memory follow-up checks whether a later message can reuse an order id from the same session.
