from __future__ import annotations


class PermissionPolicy:
    ROLE_PERMISSIONS = {
        "viewer": {"rag:read", "overview:read"},
        "analyst": {"rag:read", "overview:read", "data:query", "risk:read", "audit:read"},
        "supervisor": {"rag:read", "overview:read", "data:query", "risk:read", "audit:read", "case:review"},
    }
    MODE_PERMISSION = {
        "function_call_agent": "data:query",
        "sql_rag_chain": "data:query",
        "router_demo": "data:query",
        "auto": "data:query",
        "langchain_rag": "rag:read",
    }

    @classmethod
    def permissions_for(cls, role: str) -> set[str]:
        return cls.ROLE_PERMISSIONS.get(role, set())

    @classmethod
    def can_use_mode(cls, role: str, mode: str) -> bool:
        required = cls.MODE_PERMISSION.get(mode, "data:query")
        return required in cls.permissions_for(role)

    @classmethod
    def can_read_audit(cls, role: str) -> bool:
        return "audit:read" in cls.permissions_for(role)

    @classmethod
    def can_review_cases(cls, role: str) -> bool:
        return "case:review" in cls.permissions_for(role)
