"""检索层快速探测：只跑 53 个 RAG case 的检索部分（不调 LLM 生成），
用于混合检索（hybrid_bm25）调参时快速评估 citation 命中率。

用法（配合环境变量调参）：
  HYBRID_BM25_WEIGHT=2.0 .venv/Scripts/python.exe scripts/eval_retrieval_probe.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import main as app_main  # noqa: E402


def main() -> None:
    cases = json.loads((ROOT / "eval" / "rag_eval.json").read_text(encoding="utf-8"))
    rag = app_main.orchestrator.langchain_rag
    # 关闭 LLM 生成，只测检索层
    rag.llm = None

    pos_total = pos_hit = neg_total = neg_hit = 0
    lat = []
    fails = []
    for case in cases:
        start = time.perf_counter()
        result = rag.query(case["question"], top_k=3)
        lat.append((time.perf_counter() - start) * 1000)
        ids = [s.get("id") for s in result.get("sources", [])]
        acc = case.get("acceptable_doc_ids") or ([case["expected_doc_id"]] if case.get("expected_doc_id") else [])
        if not acc:
            neg_total += 1
            neg_hit += 1  # 负例不做检索判定
        else:
            pos_total += 1
            hit = any(d in ids for d in acc)
            pos_hit += int(hit)
            if not hit:
                fails.append((case["question"], acc, ids))

    rate = pos_hit / max(pos_total, 1)
    print(f"citation_hit_rate: {rate:.4f}  ({pos_hit}/{pos_total})")
    print(f"negative_cases: {neg_total} (默认拒答通过)")
    print(f"latency_p50: {statistics.median(lat):.0f}ms  p95: {sorted(lat)[int((len(lat)-1)*0.95)]:.0f}ms")
    print(f"未命中 {len(fails)} 个：")
    for q, acc, ids in fails[:10]:
        print(f"  - {q}")
        print(f"    expected={acc} got={ids}")


if __name__ == "__main__":
    main()
