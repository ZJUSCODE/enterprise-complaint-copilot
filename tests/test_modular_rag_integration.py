import pytest
from app.schemas import ChatRequest


def test_chat_request_includes_modular_rag():
    """Verify modular_rag is a valid mode in ChatRequest."""
    req = ChatRequest(message="test", mode="modular_rag")
    assert req.mode == "modular_rag"


def test_chat_request_all_modes():
    """Verify all modes are accepted."""
    modes = ["function_call_agent", "sql_rag_chain", "langchain_rag", "router_demo", "auto", "modular_rag"]
    for mode in modes:
        req = ChatRequest(message="test", mode=mode)
        assert req.mode == mode
