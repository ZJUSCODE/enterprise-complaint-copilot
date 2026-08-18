from __future__ import annotations

import json
import re
import time
from typing import Any, Generator

from openai import OpenAI
from pydantic import ValidationError

from app.analytics import LocalAnalyticsEngine
from app.config import Settings
from app.domain import (
    DATA_EXFILTRATION_PATTERNS,
    MUTATION_PATTERNS,
    POLICY_PATTERNS,
    PROMPT_INJECTION_PATTERNS,
    QUERY_PATTERNS,
    SOCIAL_ENGINEERING_PATTERNS,
    contains_any,
    detect_amount_threshold,
    detect_category_from_query,
    detect_complaint_type,
    normalize_category,
)
from app.rag import PolicyKnowledgeBase
from app.schemas import (
    GetUserRiskArgs,
    QueryLogisticsStatusArgs,
    QueryOrderStatusArgs,
    QueryPolicyByMarketArgs,
    QueryRefundArgs,
    QueryRefundEligibilityArgs,
    SearchPolicyArgs,
    TOOL_RESULT_MODELS,
)
from app.stores import SessionMemoryStore
from app.ticket_store import QueryFilters, ReadOnlySQLiteStore
from app.utils import (
    add_token_usage,
    extract_usage,
    lexical_overlap_score,
    safe_json_loads,
    summarize_text,
    timed_call,
)


class FunctionCallingAgent:
    def __init__(self, settings: Settings, analytics: LocalAnalyticsEngine, sql_store: ReadOnlySQLiteStore, knowledge_base: PolicyKnowledgeBase, memory: SessionMemoryStore, langchain_rag: Any | None = None):
        self.settings = settings
        self.analytics = analytics
        self.sql_store = sql_store
        self.knowledge_base = knowledge_base
        self.memory = memory
        self.langchain_rag = langchain_rag
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url) if settings.llm_api_key else None

    def _guardrail(self, message: str) -> dict[str, Any] | None:
        trigger: str | None = None
        if contains_any(message, MUTATION_PATTERNS):
            trigger = "高危写操作意图"
        elif contains_any(message, PROMPT_INJECTION_PATTERNS):
            trigger = "Prompt Injection / 规则绕过意图"
        elif contains_any(message, DATA_EXFILTRATION_PATTERNS):
            trigger = "越权导出或全量数据请求"
        elif contains_any(message, SOCIAL_ENGINEERING_PATTERNS):
            trigger = "社会工程学攻击（身份冒充或紧急施压）"
        if trigger:
            return {
                "mode": "guardrail",
                "title": "高危操作已拦截",
                "summary": "当前 Agent 只支持授权范围内的查询、检索与分析，不执行写操作、规则绕过或全量敏感数据导出。",
                "highlights": [f"命中 Safety Guardrail：{trigger}", "执行层只允许只读工具", "已进入人工复核队列"],
                "citations": [{"label": "只读安全要求", "text": "Text-to-SQL 与工具层禁止 UPDATE、DELETE、INSERT 等写操作，并拒绝绕过权限和全量导出。"}],
                "tool_trace": [],
                "review_required": True,
                "review_reason": f"命中{trigger}，需要人工判断是否进入审批或安全处理流程。",
            }
        return None

    def _build_tools(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "get_user_risk", "description": "查询指定用户的风险评分、风险等级和建议动作。", "parameters": {"type": "object", "properties": {"user_id": {"type": "string", "description": "用户唯一编号"}}, "required": ["user_id"]}}},
            {"type": "function", "function": {"name": "query_refund_cases", "description": "查询异常退款和客诉明细，返回关键指标、明细表和 SQL 预览。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "用户原始问题"}, "category": {"type": "string", "description": "业务类目，如 3C数码、生鲜"}, "complaint_type": {"type": "string", "description": "客诉类型，如 质量问题、物流延误"}, "amount_threshold": {"type": "number", "description": "赔付金额阈值，单位元"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "search_policy_docs", "description": "检索售后 SOP、赔付规则、客服安抚话术，并返回引用来源。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "检索问题"}, "category": {"type": "string", "description": "业务类目，可选"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "query_order_status", "description": "Lookup order status by order_id.", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
            {"type": "function", "function": {"name": "query_logistics_status", "description": "Lookup logistics delivery status and delay by order_id.", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
            {"type": "function", "function": {"name": "query_refund_eligibility", "description": "Check refund eligibility and escalation priority for an order.", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["order_id"]}}},
            {"type": "function", "function": {"name": "query_policy_by_market", "description": "Lookup market-specific refund or complaint policy guidance.", "parameters": {"type": "object", "properties": {"market": {"type": "string"}, "topic": {"type": "string"}}, "required": ["market", "topic"]}}},
        ]

    def _validate_tool_args(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_user_risk":
            return GetUserRiskArgs(**arguments).model_dump()
        if name == "query_refund_cases":
            payload = QueryRefundArgs(**arguments).model_dump()
            payload["category"] = normalize_category(payload.get("category")) or detect_category_from_query(payload["query"])
            payload["complaint_type"] = payload.get("complaint_type") or detect_complaint_type(payload["query"])
            payload["amount_threshold"] = payload.get("amount_threshold") or detect_amount_threshold(payload["query"])
            return payload
        if name == "search_policy_docs":
            payload = SearchPolicyArgs(**arguments).model_dump()
            payload["category"] = normalize_category(payload.get("category")) or detect_category_from_query(payload["query"])
            return payload
        if name == "query_order_status":
            return QueryOrderStatusArgs(**arguments).model_dump()
        if name == "query_logistics_status":
            return QueryLogisticsStatusArgs(**arguments).model_dump()
        if name == "query_refund_eligibility":
            return QueryRefundEligibilityArgs(**arguments).model_dump()
        if name == "query_policy_by_market":
            return QueryPolicyByMarketArgs(**arguments).model_dump()
        raise ValueError(f"未知工具：{name}")

    def _validate_tool_result(self, name: str, result: dict[str, Any]) -> dict[str, Any] | None:
        model_cls = TOOL_RESULT_MODELS.get(name)
        if not model_cls:
            return None
        try:
            validated = model_cls(**result)
            return validated.model_dump()
        except Exception:
            return None

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_user_risk":
            return self.analytics.get_user_risk(arguments["user_id"])
        if name == "query_refund_cases":
            return self.sql_store.query_ticket_details(QueryFilters(category=arguments.get("category"), complaint_type=arguments.get("complaint_type"), amount_threshold=arguments.get("amount_threshold")))
        if name == "search_policy_docs":
            query = arguments.get("query", "")
            cat = arguments.get("category") or detect_category_from_query(query)
            if self.langchain_rag and self.langchain_rag.available:
                rag_result = self.langchain_rag.query(query, category=cat, top_k=3)
                return {"documents": rag_result.get("sources", [])}
            docs = self.knowledge_base.lexical_search(query, category=cat, top_k=3)
            return {"documents": docs}
        if name == "query_order_status":
            return self.analytics.query_order_status(arguments["order_id"])
        if name == "query_logistics_status":
            return self.analytics.query_logistics_status(arguments["order_id"])
        if name == "query_refund_eligibility":
            return self.analytics.query_refund_eligibility(arguments["order_id"], reason=arguments.get("reason"))
        if name == "query_policy_by_market":
            return self.analytics.query_policy_by_market(arguments["market"], arguments["topic"])
        return {"error": f"未知工具：{name}"}

    def _recent_order_id(self, session_id: str) -> str | None:
        for item in reversed(self.memory.recent_messages(session_id, limit=12)):
            match = re.search(r"[0-9a-f]{24,}", item.get("content", ""), re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _should_fallback_to_tools(self, message: str) -> bool:
        if re.search(r"[0-9a-f]{24,}", message, re.IGNORECASE) and "风险" in message:
            return True
        return contains_any(message, QUERY_PATTERNS) or contains_any(message, POLICY_PATTERNS) or contains_any(message, ["order status", "logistics", "shipping", "refund eligibility", "market policy", "订单状态", "物流", "退款资格", "市场政策"])

    def _respond_without_llm(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        sid = self.memory.get_or_create(session_id)
        aggregate_payload: dict[str, Any] = {}
        tool_trace: list[dict[str, Any]] = []

        user_match = re.search(r"[0-9a-f]{24,}", user_message, re.IGNORECASE)
        order_id = user_match.group(0) if user_match else self._recent_order_id(sid)
        message_lower = user_message.lower()

        # Check session context: if previous tool was policy search and follow-up has no strong data intent, stay on policy
        last_mode = self.memory.get_meta(sid, "last_mode") if hasattr(self.memory, "get_meta") else None
        has_strong_data_intent = contains_any(user_message, ["查询", "查一下", "明细", "统计", "分析", "超过", "多少", "金额", "top", "最多"])
        if last_mode in {"langchain_rag", "sql_rag_chain"} and not has_strong_data_intent and not user_match:
            tool_name = "search_policy_docs"
            validated_args = self._validate_tool_args(tool_name, {"query": user_message})
        elif order_id and contains_any(message_lower, ["logistics", "shipping", "delivery", "物流", "快递", "到哪", "进度", "配送"]):
            tool_name = "query_logistics_status"
            validated_args = {"order_id": order_id}
        elif order_id and contains_any(message_lower, ["order status", "订单状态", "status", "订单进展"]):
            tool_name = "query_order_status"
            validated_args = {"order_id": order_id}
        elif order_id and contains_any(message_lower, ["eligible", "refund eligibility", "能退", "退款资格", "能不能退", "是否能退"]):
            tool_name = "query_refund_eligibility"
            validated_args = {"order_id": order_id, "reason": user_message}
        elif contains_any(message_lower, ["market policy", "policy by market", "市场政策", "跨市场"]):
            market_match = re.search(r"\b(BR|US|EU|CN)\b", user_message, re.IGNORECASE)
            tool_name = "query_policy_by_market"
            validated_args = {"market": market_match.group(1).upper() if market_match else "GLOBAL", "topic": user_message}
        elif user_match and "风险" in user_message:
            tool_name = "get_user_risk"
            validated_args = {"user_id": user_match.group(0)}
        elif contains_any(user_message, POLICY_PATTERNS) and not contains_any(user_message, ["明细", "统计", "最多", "超过"]):
            tool_name = "search_policy_docs"
            validated_args = self._validate_tool_args(tool_name, {"query": user_message})
        else:
            tool_name = "query_refund_cases"
            validated_args = self._validate_tool_args(tool_name, {"query": user_message})

        result, duration_ms = timed_call(self._execute_tool, tool_name, validated_args)
        trace_entry: dict[str, Any] = {"tool": tool_name, "arguments": validated_args, "duration_ms": duration_ms, "result_summary": summarize_text(json.dumps(result, ensure_ascii=False), limit=180)}
        structured = self._validate_tool_result(tool_name, result)
        if structured is not None:
            trace_entry["structured_output"] = structured
        tool_trace.append(trace_entry)

        if tool_name == "query_refund_cases":
            aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
            aggregate_payload["table"] = result.get("rows", [])
            aggregate_payload["sql_preview"] = result.get("sql_preview")
            aggregate_payload["highlights"] = [result.get("summary", "")]
            summary = "（降级模式：未配置 LLM，使用确定性工具返回原始数据）已完成只读数据查询。如需自然语言总结，请配置 LLM_API_KEY。"
        elif tool_name == "search_policy_docs":
            aggregate_payload["citations"] = [{
                "label": doc["citation"],
                "text": doc["excerpt"],
                "source": "lexical_fallback",
                "retrieval_score": None,
                "rerank_score": round(lexical_overlap_score(user_message, f"{doc['title']} {doc['excerpt']}"), 4),
            } for doc in result.get("documents", [])]
            aggregate_payload["highlights"] = [doc["title"] for doc in result.get("documents", [])]
            summary = "（降级模式：未配置 LLM，使用本地政策检索返回可引用依据）如需 AI 生成自然语言回答，请配置 LLM_API_KEY。"
        elif tool_name in {"query_order_status", "query_logistics_status", "query_refund_eligibility", "query_policy_by_market"}:
            aggregate_payload["highlights"] = [json.dumps(result, ensure_ascii=False)]
            if tool_name == "query_refund_eligibility" and result.get("priority") == "high":
                aggregate_payload["review_required"] = True
                aggregate_payload["review_reason"] = "Refund eligibility returned high priority and requires supervisor escalation."
            summary = "（降级模式：未配置 LLM，使用确定性工具返回原始数据）已完成业务查询。如需 AI 总结，请配置 LLM_API_KEY。"
        else:
            if result.get("found"):
                aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
                aggregate_payload["highlights"] = [f"风险分：{result['risk_score']}", f"风险等级：{result['risk_level']}", result["suggestion"]]
            else:
                aggregate_payload["highlights"] = [result.get("message", "未找到用户记录。")]
            summary = "（降级模式：未配置 LLM，使用本地风险评分返回结果）如需 AI 分析，请配置 LLM_API_KEY。"

        self.memory.append(sid, "user", user_message)
        self.memory.append(sid, "assistant", summary)
        # Track last tool for memory follow-up routing
        if hasattr(self.memory, "set_meta") and tool_trace:
            self.memory.set_meta(sid, "last_tool", tool_trace[-1].get("tool"))
        return {
            "mode": "function_call_agent",
            "title": "Function Calling Agent",
            "summary": summary,
            "session_id": sid,
            "tool_trace": tool_trace,
            **aggregate_payload,
        }

    def respond(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        blocked = self._guardrail(user_message)
        if blocked:
            return blocked
        if not self.client:
            return self._respond_without_llm(user_message, session_id=session_id)

        sid = self.memory.get_or_create(session_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": "你是企业级智能客诉 Copilot。你的职责是调用工具完成只读分析和政策检索。禁止捏造数据，禁止执行审批、改单、删除或退款执行。"}]
        messages.extend(self.memory.recent_messages(sid))
        messages.append({"role": "user", "content": user_message})
        tool_trace: list[dict[str, Any]] = []
        aggregate_payload: dict[str, Any] = {}
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        retry_count = 0

        for _ in range(2):
            try:
                response = self.client.chat.completions.create(model=self.settings.llm_model, messages=messages, tools=self._build_tools(), tool_choice="auto", temperature=0)
                token_usage = add_token_usage(token_usage, extract_usage(response))
            except Exception as exc:
                retry_count += 1
                if retry_count <= self.settings.llm_max_retries:
                    time.sleep(0.2 * retry_count)
                    continue
                fallback = self._respond_without_llm(user_message, session_id=sid)
                fallback["_retry_count"] = retry_count
                fallback["_token_usage"] = token_usage
                fallback["degradation_path"] = "llm_error_to_local_tools"
                fallback["error"] = {"code": "llm_call_failed", "message": str(exc)}
                return fallback
            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []
            if not tool_calls:
                answer = assistant_message.content or "模型未返回有效内容。"
                if not aggregate_payload and self._should_fallback_to_tools(user_message):
                    fallback = self._respond_without_llm(user_message, session_id=sid)
                    fallback["summary"] = "模型已连接，但本次未触发工具调用，系统已回退到受控工具链完成查询。"
                    fallback.setdefault("highlights", [])
                    fallback["highlights"] = ["模型响应未包含 tool_call，已使用确定性工具 fallback 保持演示稳定。", *fallback["highlights"]]
                    fallback["_retry_count"] = retry_count
                    fallback["_token_usage"] = token_usage
                    return fallback
                self.memory.append(sid, "user", user_message)
                self.memory.append(sid, "assistant", answer)
                return {"mode": "function_call_agent", "title": "Function Calling Agent", "summary": answer, "session_id": sid, "tool_trace": tool_trace, "_retry_count": retry_count, "_token_usage": token_usage, **aggregate_payload}
            messages.append({"role": "assistant", "content": assistant_message.content or "", "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}} for call in tool_calls]})
            for call in tool_calls:
                args: dict[str, Any] = {}
                try:
                    args = safe_json_loads(call.function.arguments or "{}")
                    validated_args = self._validate_tool_args(call.function.name, args)
                    result, duration_ms = timed_call(self._execute_tool, call.function.name, validated_args)
                    trace_entry: dict[str, Any] = {"tool": call.function.name, "arguments": validated_args, "duration_ms": duration_ms, "result_summary": summarize_text(json.dumps(result, ensure_ascii=False), limit=180)}
                    structured = self._validate_tool_result(call.function.name, result)
                    if structured is not None:
                        trace_entry["structured_output"] = structured
                    tool_trace.append(trace_entry)
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    result = {"error": f"工具参数校验失败：{exc}"}
                    validated_args = args if isinstance(args, dict) else {}
                    tool_trace.append({"tool": call.function.name, "arguments": validated_args, "result_summary": str(exc)})
                if call.function.name == "query_refund_cases":
                    aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
                    aggregate_payload["table"] = result.get("rows", [])
                    aggregate_payload["sql_preview"] = result.get("sql_preview")
                    aggregate_payload.setdefault("highlights", []).append(result.get("summary", ""))
                elif call.function.name == "search_policy_docs":
                    aggregate_payload["citations"] = [{"label": doc["citation"], "text": doc["excerpt"], "retrieval_score": doc.get("retrieval_score"), "rerank_score": doc.get("rerank_score"), "source": doc.get("source")} for doc in result.get("documents", [])]
                    aggregate_payload.setdefault("highlights", []).extend(doc["title"] for doc in result.get("documents", []))
                elif call.function.name == "get_user_risk" and result.get("found"):
                    aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
                    aggregate_payload.setdefault("highlights", []).extend([f"风险分：{result['risk_score']}", f"风险等级：{result['risk_level']}", result["suggestion"]])
                elif call.function.name in {"query_order_status", "query_logistics_status", "query_refund_eligibility", "query_policy_by_market"}:
                    aggregate_payload.setdefault("highlights", []).append(json.dumps(result, ensure_ascii=False))
                    if call.function.name == "query_refund_eligibility" and result.get("priority") == "high":
                        aggregate_payload["review_required"] = True
                        aggregate_payload["review_reason"] = "Refund eligibility returned high priority and requires supervisor escalation."
                elif result.get("error"):
                    aggregate_payload.setdefault("highlights", []).append(result["error"])
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})

        self.memory.append(sid, "user", user_message)
        self.memory.append(sid, "assistant", "工具调用轮次已达上限。")
        return {"mode": "function_call_agent", "title": "Function Calling Agent", "summary": "工具调用轮次已达上限，请调整问题后重试。", "session_id": sid, "tool_trace": tool_trace, **aggregate_payload}

    def respond_stream(self, user_message: str, session_id: str | None = None) -> Generator[dict[str, Any], None, None]:
        """Yield status, token, and final events for true SSE streaming."""
        blocked = self._guardrail(user_message)
        if blocked:
            yield {"type": "final", "data": blocked}
            return

        if not self.client:
            fallback = self._respond_without_llm(user_message, session_id=session_id)
            # Split summary into sentences for simulated streaming
            summary = fallback.get("summary", "")
            sentences = re.split(r"(?<=[。！？\n])", summary)
            for sentence in sentences:
                if sentence.strip():
                    yield {"type": "token", "content": sentence}
            yield {"type": "final", "data": fallback}
            return

        sid = self.memory.get_or_create(session_id)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "你是企业级智能客诉 Copilot。你的职责是调用工具完成只读分析和政策检索。禁止捏造数据，禁止执行审批、改单、删除或退款执行。"}
        ]
        messages.extend(self.memory.recent_messages(sid))
        messages.append({"role": "user", "content": user_message})
        tool_trace: list[dict[str, Any]] = []
        aggregate_payload: dict[str, Any] = {}
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        for turn in range(2):
            try:
                stream = self.client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=messages,
                    tools=self._build_tools(),
                    tool_choice="auto",
                    temperature=0,
                    stream=True,
                    stream_options={"include_usage": True},
                )
            except Exception as exc:
                fallback = self._respond_without_llm(user_message, session_id=sid)
                fallback["degradation_path"] = "llm_error_to_local_tools"
                fallback["error"] = {"code": "llm_call_failed", "message": str(exc)}
                yield {"type": "final", "data": fallback}
                return

            # Collect streamed content and tool_calls
            content_parts: list[str] = []
            tool_calls_data: dict[int, dict[str, Any]] = {}  # index -> {id, name, arguments}

            for chunk in stream:
                # Extract usage from final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    token_usage["prompt_tokens"] = getattr(chunk.usage, "prompt_tokens", 0) or 0
                    token_usage["completion_tokens"] = getattr(chunk.usage, "completion_tokens", 0) or 0
                    token_usage["total_tokens"] = getattr(chunk.usage, "total_tokens", 0) or 0

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # Stream content tokens
                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "token", "content": delta.content}

                # Collect tool_calls
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_data:
                            tool_calls_data[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_data[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_data[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_data[idx]["arguments"] += tc_delta.function.arguments

            # If no tool calls, we're done
            if not tool_calls_data:
                answer = "".join(content_parts) or "模型未返回有效内容。"
                if not aggregate_payload and self._should_fallback_to_tools(user_message):
                    fallback = self._respond_without_llm(user_message, session_id=sid)
                    fallback["summary"] = "模型已连接，但本次未触发工具调用，系统已回退到受控工具链完成查询。"
                    fallback.setdefault("highlights", [])
                    fallback["highlights"] = ["模型响应未包含 tool_call，已使用确定性工具 fallback 保持演示稳定。", *fallback["highlights"]]
                    fallback["_token_usage"] = token_usage
                    yield {"type": "final", "data": fallback}
                    return
                self.memory.append(sid, "user", user_message)
                self.memory.append(sid, "assistant", answer)
                yield {"type": "final", "data": {
                    "mode": "function_call_agent", "title": "Function Calling Agent",
                    "summary": answer, "session_id": sid, "tool_trace": tool_trace,
                    "_token_usage": token_usage, **aggregate_payload,
                }}
                return

            # Execute tool calls
            yield {"type": "status", "phase": "tools", "message": f"正在执行 {len(tool_calls_data)} 个工具调用。"}
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts), "tool_calls": []}
            for idx in sorted(tool_calls_data.keys()):
                tc = tool_calls_data[idx]
                assistant_msg["tool_calls"].append({
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                })
            messages.append(assistant_msg)

            for idx in sorted(tool_calls_data.keys()):
                tc = tool_calls_data[idx]
                args: dict[str, Any] = {}
                try:
                    args = safe_json_loads(tc["arguments"] or "{}")
                    validated_args = self._validate_tool_args(tc["name"], args)
                    result, duration_ms = timed_call(self._execute_tool, tc["name"], validated_args)
                    trace_entry: dict[str, Any] = {
                        "tool": tc["name"], "arguments": validated_args,
                        "duration_ms": duration_ms,
                        "result_summary": summarize_text(json.dumps(result, ensure_ascii=False), limit=180),
                    }
                    structured = self._validate_tool_result(tc["name"], result)
                    if structured is not None:
                        trace_entry["structured_output"] = structured
                    tool_trace.append(trace_entry)
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    result = {"error": f"工具参数校验失败：{exc}"}
                    validated_args = args if isinstance(args, dict) else {}
                    tool_trace.append({"tool": tc["name"], "arguments": validated_args, "result_summary": str(exc)})

                self._collect_tool_payload(tc["name"], result, aggregate_payload)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, ensure_ascii=False)})

        self.memory.append(sid, "user", user_message)
        self.memory.append(sid, "assistant", "工具调用轮次已达上限。")
        yield {"type": "final", "data": {
            "mode": "function_call_agent", "title": "Function Calling Agent",
            "summary": "工具调用轮次已达上限，请调整问题后重试。",
            "session_id": sid, "tool_trace": tool_trace, **aggregate_payload,
        }}

    def _collect_tool_payload(self, tool_name: str, result: dict[str, Any], payload: dict[str, Any]) -> None:
        """Update aggregate_payload from a tool result (shared by respond and respond_stream)."""
        if tool_name == "query_refund_cases":
            payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
            payload["table"] = result.get("rows", [])
            payload["sql_preview"] = result.get("sql_preview")
            payload.setdefault("highlights", []).append(result.get("summary", ""))
        elif tool_name == "search_policy_docs":
            payload["citations"] = [{"label": doc["citation"], "text": doc["excerpt"], "retrieval_score": doc.get("retrieval_score"), "rerank_score": doc.get("rerank_score"), "source": doc.get("source")} for doc in result.get("documents", [])]
            payload.setdefault("highlights", []).extend(doc["title"] for doc in result.get("documents", []))
        elif tool_name == "get_user_risk" and result.get("found"):
            payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
            payload.setdefault("highlights", []).extend([f"风险分：{result['risk_score']}", f"风险等级：{result['risk_level']}", result["suggestion"]])
        elif tool_name in {"query_order_status", "query_logistics_status", "query_refund_eligibility", "query_policy_by_market"}:
            payload.setdefault("highlights", []).append(json.dumps(result, ensure_ascii=False))
            if tool_name == "query_refund_eligibility" and result.get("priority") == "high":
                payload["review_required"] = True
                payload["review_reason"] = "Refund eligibility returned high priority and requires supervisor escalation."
        elif result.get("error"):
            payload.setdefault("highlights", []).append(result["error"])
