"""FastAPI authentication dependencies.

Supports two authentication schemes:

1. **Peer certificate auth** — peers sign requests with their private key.
   The server verifies the signature against the pinned public key in the
   trust store.  Headers: ``X-Device-ID``, ``X-Timestamp``, ``X-Signature``.

2. **Admin bearer token** — the local web dashboard authenticates via
   ``Authorization: Bearer <admin_token>``.

Legacy API-key auth (``X-API-Key``) is still accepted as a fallback for
backward compatibility but should be considered deprecated.
"""

from __future__ import annotations

import base64
import hmac
import time

from fastapi import Header, HTTPException, Request


def _safe_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------------------
# Peer-to-peer authentication (certificate signatures or legacy API key)
# ---------------------------------------------------------------------------

# Maximum clock skew allowed between peers (seconds).
_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


async def require_peer_auth(request: Request) -> str:
    """Dependency: authenticate an incoming peer request.

    Tries certificate-based signature auth first, then falls back to the
    legacy ``X-API-Key`` header.  Returns the authenticated device ID
    (or ``"legacy-api-key"`` for old-style callers).
    """
    device_id = request.headers.get("x-device-id", "")
    timestamp_str = request.headers.get("x-timestamp", "")
    signature_b64 = request.headers.get("x-signature", "")

    if device_id and timestamp_str and signature_b64:
        return await _verify_device_signature(
            request, device_id, timestamp_str, signature_b64
        )

    # Fall back to legacy API key
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        expected = request.app.state.settings.api_key
        if _safe_compare(api_key, expected):
            return "legacy-api-key"

    raise HTTPException(
        status_code=403,
        detail="Authentication required — peer not trusted",
    )


async def _verify_device_signature(
    request: Request,
    device_id: str,
    timestamp_str: str,
    signature_b64: str,
) -> str:
    """Validate an RSA-PSS signed request from a trusted peer."""
    trust_store = getattr(request.app.state, "trust_store", None)
    if trust_store is None:
        raise HTTPException(status_code=503, detail="Trust store not available")

    if not trust_store.is_trusted(device_id):
        raise HTTPException(status_code=403, detail="Device not trusted")

    # Timestamp freshness
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp header")

    if abs(time.time() - timestamp) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=403, detail="Request timestamp expired")

    # Signature verification
    public_key_pem = trust_store.get_public_key(device_id)
    if not public_key_pem:
        raise HTTPException(status_code=403, detail="No public key for device")

    method = request.method
    path = request.url.path
    message = f"{device_id}:{timestamp_str}:{method}:{path}".encode()

    try:
        signature = base64.b64decode(signature_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature encoding")

    from utils.certs import verify_signature

    if not verify_signature(public_key_pem, message, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    trust_store.touch(device_id)
    return device_id


# ---------------------------------------------------------------------------
# Legacy API-key auth (kept for backward compatibility)
# ---------------------------------------------------------------------------


async def require_api_key(request: Request, x_api_key: str = Header(None)) -> str:
    """Dependency: reject requests without a valid ``x-api-key`` header.

    .. deprecated:: Use :func:`require_peer_auth` for peer endpoints.
    """
    expected = request.app.state.settings.api_key
    if not x_api_key or not _safe_compare(x_api_key, expected):
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return x_api_key


# ---------------------------------------------------------------------------
# Admin / management UI authentication
# ---------------------------------------------------------------------------


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
