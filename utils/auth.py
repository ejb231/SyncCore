"""FastAPI authentication dependencies."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


async def require_api_key(request: Request, x_api_key: str = Header(None)) -> str:
    """Dependency: reject requests without a valid ``x-api-key`` header."""
    expected = request.app.state.settings.api_key
    if not x_api_key or not _safe_compare(x_api_key, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return x_api_key


async def require_admin_token(request: Request) -> str:
    """Dependency: reject requests without a valid ``Authorization: Bearer`` token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin token")
    token = auth_header.removeprefix("Bearer ").strip()
    expected = request.app.state.settings.admin_token
    if not _safe_compare(token, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return token
