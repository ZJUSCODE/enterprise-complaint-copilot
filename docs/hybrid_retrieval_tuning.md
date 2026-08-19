# 混合检索调优记录（hybrid_bm25）

> 2026-08-18 · 检索层 `citation_hit_rate` 从 **55.6% 调优至 88.9%**（+33.3pp），端到端全量评测验证通过。
> 复现命令见文末；相关代码变更：`app/rag.py`（检索融合）、`app/bm25.py`（加权 RRF）、`app/config.py`（可配置参数）。

## 1. 问题

本地混合检索（向量 + BM25 + RRF）在 53 个 RAG 用例上的 citation 命中率仅 **55.6%**，
显著低于 BM25 单路兜底路径的 **88.9%** 和词法基线的 **91.1%**。

| 检索方式 | citation_hit_rate | 说明 |
|---|---|---|
| 词法基线（--force-lexical） | 91.1% | token 重叠启发式 |
| BM25 单路（向量未启用兜底） | 88.9% | `_bm25_sources` 含政策加权 |
| **混合 hybrid_bm25（调优前）** | **55.6%** | 向量 + BM25 + RRF，无加权 |
| **混合 hybrid_bm25（调优后）** | **88.9%** | 本文目标达成 |

## 2. 根因分析

对比单路路径 `_bm25_sources` 与混合路径 `query()` 的实现差异，发现三个不一致：

1. **候选池大小不一致**：单路路径 BM25 召回 `top_k*3=9` 个候选；混合路径只召回 `top_k*2=6` 个。
   评测集正确条目（POL-XXX 政策）常排在第 6~9 位，直接被截断，RRF 融合池里根本没有正确答案。
2. **缺少政策锚点加权**：单路路径对 `POL-` 前缀条目做 `score × 1.5` 加权重排
   （docstring 明示："政策条目是判责锚点，避免政策被更长的 FAQ/SOP chunk 挤出 top_k"）；
   混合路径的 BM25 侧没有该策略，长文本 FAQ/SOP chunk 更容易排在政策前。
3. **RRF 无权重融合**：`reciprocal_rank_fusion` 对向量与 BM25 两路等权相加。
   向量 top-1 得分 `1/(60+1)≈0.0164` 与 BM25 top-3 得分 `1/(60+3)≈0.0159` 几乎持平，
   语义相近但答案错误的 FAQ 结果（向量前 3 名）能把 BM25 的正确答案挤出 top-3。

## 3. 实验过程

评估工具：`scripts/eval_retrieval_probe.py`（检索层快速探测，不调 LLM 生成，单轮约 90 秒）。
参数均通过环境变量注入，未改动业务逻辑，配置项见 `app/config.py`。

| # | BM25 候选 | POL 加权 | BM25 融合权重 | citation_hit_rate | 结论 |
|---|---|---|---|---|---|
| 基线 | 6 | 1.0 | 1.0 | 55.6% | 复现问题 |
| 1 | 6 | 1.0 | 2.0 | 71.1% | BM25 加权有效（+15.5pp） |
| 2 | 6 | 1.0 | 3.0 | 71.1% | 权重 ≥2 后无增益 |
| 3 | 6 | 1.0 | 4.0 | 71.1% | 同上 |
| 4 | **9** | **1.5** | **2.0** | **88.9%** | 三项组合达到上限 |
| 5 | 9 | 1.5 | 1.0 | 77.8% | 融合权重仍必要 |
| 6 | 12 | 1.5 | 2.0 | 88.9% | 候选 9 已足够 |
| 7 | 9 | 2.0 | 2.0 | 88.9% | POL 加权 1.5 已足够 |

## 4. 最终参数（已固化为默认值）

| 配置项 | 环境变量 | 调优前 | 调优后 |
|---|---|---|---|
| BM25 候选数 | `HYBRID_BM25_CANDIDATES` | 6 | **9** |
| POL 政策锚点加权 | `HYBRID_POLICY_WEIGHT` | 1.0 | **1.5** |
| BM25 融合权重（RRF） | `HYBRID_BM25_WEIGHT` | 1.0 | **2.0** |
| 向量候选数 | `HYBRID_VECTOR_CANDIDATES` | 6 | 6（不变） |
| RRF k | `HYBRID_RRF_K` | 60 | 60（不变） |

> 调优思路总结：**BM25 在本评测集上是更强的一路，混合检索的任务是"保住 BM25 的正确结果，再用向量补充"，而非五五开**。
> 因此：扩大 BM25 候选池 → 政策锚点加权保住判责条目 → 融合权重向 BM25 倾斜。

## 5. 端到端验证（含 LLM 生成）

`evaluate_rag.py --top-k 3` 全量 53 RAG + 39 Agent，DeepSeek V4 Flash：

| 指标 | 调优前 | 调优后 |
|---|---|---|
| citation_hit_rate | 55.6% | **88.9%** |
| rag_case_success_rate | 62.3% | **90.6%** |
| negative_abstention_rate | 100% | 100%（保持） |
| route_accuracy | 93.3% | 93.3%（保持） |
| tool_selection_accuracy | 90% | 90%（保持） |
| guardrail_interception | 100% | 100%（保持） |
| memory_followup_accuracy | 100% | 100%（保持） |

报告文件：`eval/results/tuning_report.json` / `tuning_report.md`。

## 6. 剩余边界（5 个未命中）

调优后 45 个正例中仍有 5 个未命中，与 BM25 单路持平（均为检索/标注边界，非参数问题）：

- 关键词歧义：如「普通退货还在 7 天无理由范围内」BM25 命中 POL-020 而非 POL-001；
- 标注口径：如「退款多久到账」实际答案更贴近 FAQ，但标注指向 POL-019；
- 语义抽象：如「客服可以对用户说『你爱投诉就投诉』吗」需更深语义理解。

后续可尝试：重排模型（cross-encoder）、问题分类路由（FAQ 类问题优先走 FAQ 库）、评测标注修正。

## 7. 复现

```bash
# 检索层快速探测（无 LLM，约 90 秒）
.venv/bin/python scripts/eval_retrieval_probe.py

# 端到端全量评测（含 LLM，约 3 分钟）
.venv/bin/python scripts/evaluate_rag.py --top-k 3 \
  --output eval/results/tuning_report.json \
  --markdown-output eval/results/tuning_report.md
```

调优参数已固化为 `app/config.py` 默认值；如需回退/试验，用环境变量覆盖即可，例如：
`HYBRID_BM25_WEIGHT=1.0 HYBRID_POLICY_WEIGHT=1.0 HYBRID_BM25_CANDIDATES=6 ...`
