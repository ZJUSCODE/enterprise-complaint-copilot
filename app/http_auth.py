from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException

from app.runtime_state import get_runtime
from app.security import jwt_decode


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def optional_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    runtime = get_runtime()
    token = _bearer_token(authorization)
    if not token:
        if runtime.settings.auth_enforced:
            raise HTTPException(status_code=401, detail={"code": "missing_token", "message": "Bearer token required"})
        return None
    try:
        payload = jwt_decode(token, runtime.settings.jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"code": str(exc), "message": "Invalid or expired token"}) from exc
    user = runtime.user_store.get_by_id(str(payload.get("sub", "")))
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail={"code": "user_inactive", "message": "User is inactive or missing"})
    return user


def require_current_user(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    if current_user:
        return current_user
    raise HTTPException(status_code=401, detail={"code": "missing_token", "message": "Bearer token required"})


def resolve_role(requested_role: str | None, current_user: dict[str, Any] | None) -> str:
    # Request roles are display hints only; authorization comes from the trusted identity.
    return current_user["role"] if current_user else "viewer"
