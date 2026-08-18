from __future__ import annotations

import json
from types import SimpleNamespace

import main


class FakeChatCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            tool_call = SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="query_refund_cases",
                    arguments=json.dumps({"query": "查一下质量问题退款超过100元的明细"}, ensure_ascii=False),
                ),
            )
            message = SimpleNamespace(content="", tool_calls=[tool_call])
        else:
            message = SimpleNamespace(content="已完成只读查询，建议优先复核高赔付异常单。", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAIClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeChatCompletions())


def test_function_call_agent_executes_mocked_tool_call():
    original_client = main.orchestrator.function_agent.client
    try:
        main.orchestrator.function_agent.client = FakeOpenAIClient()
        result = main.orchestrator.function_agent.respond("查一下质量问题退款超过100元的明细")
    finally:
        main.orchestrator.function_agent.client = original_client

    assert result["mode"] == "function_call_agent"
    assert result["tool_trace"][0]["tool"] == "query_refund_cases"
    assert result["table"], "mocked tool call should return readonly SQL rows"
    assert "SELECT" in result["sql_preview"]


def test_function_call_agent_uses_deterministic_fallback_without_llm():
    original_client = main.orchestrator.function_agent.client
    try:
        main.orchestrator.function_agent.client = None
        result = main.orchestrator.function_agent.respond("查一下质量问题退款超过100元的明细")
    finally:
        main.orchestrator.function_agent.client = original_client

    assert result["mode"] == "function_call_agent"
    assert result["tool_trace"][0]["tool"] == "query_refund_cases"
    assert result["table"]
    assert "SELECT" in result["sql_preview"]


def test_model_cannot_drop_filters_from_original_user_query():
    args = main.orchestrator.function_agent._validate_tool_args(
        "query_refund_cases",
        {"query": "查一下退款明细", "complaint_type": "物流延误"},
        original_query="查一下质量问题退款超过100元的明细",
    )

    assert args["query"] == "查一下质量问题退款超过100元的明细"
    assert args["complaint_type"] == "质量问题"
    assert args["amount_threshold"] == 100


def test_refund_metrics_use_unique_order_aggregation():
    result = main.sql_store.query_ticket_details(
        main.QueryFilters(complaint_type="质量问题", amount_threshold=100),
    )
    metrics = result["metrics"]
    order_ids = [row["order_id"] for row in result["rows"]]

    assert order_ids
    assert len(order_ids) == len(set(order_ids))
    assert all(row["compensation_amount"] >= 100 for row in result["rows"])
    assert metrics["平均赔付"] == round(metrics["估算赔付总额"] / metrics["异常工单数"], 2)
    assert "WITH grouped_tickets" in result["sql_preview"]
