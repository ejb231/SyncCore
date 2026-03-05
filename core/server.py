"""FastAPI application: sync endpoints, write guard, and WebSocket hub."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware

import hmac as _hmac

from core.management_api import router as management_router, setup_router
from core.ws import ws_manager
from utils.auth import require_peer_auth
from utils.conflict import resolve_conflict
from utils.file_ops import calculate_hash, decompress, hash_bytes
from utils.logging import get_logger

log = get_logger("server")

app = FastAPI(title="SyncCore Server")

# --------------------------------------------------------------------------
# Upload rate limiter — 60 uploads per minute per IP
# --------------------------------------------------------------------------

from core.peer_manager import RateLimiter  # reuse existing implementation

_upload_limiter = RateLimiter(window=60.0, limit=60)

# CORS — always enabled so the dashboard works regardless of how the
# user reaches it (localhost vs 127.0.0.1, HTTP vs HTTPS, dev server,
# etc.).  Without this, browsers such as Firefox reject cross-origin
# fetch() calls with "NetworkError when attempting to fetch resource".
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Write guard — prevents the watcher from re-queuing server-written files
# ---------------------------------------------------------------------------


class _WriteGuard:
    """Thread-safe set of paths recently written by the server.

    Entries auto-expire after *ttl* seconds so stale entries never
    accumulate even if the watcher misses an event.
    """

    def __init__(self, ttl: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, float] = {}
        self._ttl = ttl

    @staticmethod
    def _normalize(path: str) -> str:
        """Normalize path to forward slashes for consistent matching."""
        return path.replace("\\", "/")

    def mark(self, path: str) -> None:
        key = self._normalize(path)
        with self._lock:
            self._entries[key] = time.monotonic() + self._ttl

    def consume(self, path: str) -> bool:
        """Return True and remove if *path* was recently written by the server."""
        key = self._normalize(path)
        now = time.monotonic()
        with self._lock:
            expiry = self._entries.get(key)
            if expiry is not None and now < expiry:
                del self._entries[key]
                return True
            self._entries.pop(key, None)
            return False


_write_guard = _WriteGuard()


def mark_server_write(path: str) -> None:
    """Record that the server is about to write *path* (suppresses watcher)."""
    _write_guard.mark(path)


def consume_server_write(path: str) -> bool:
    """Check and clear a pending server-write flag for *path*."""
    return _write_guard.consume(path)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/api/v1/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint with two auth modes.

    1. Query-string ``?token=<admin_token>`` (legacy / simple clients).
    2. First-message auth: connect without a token, then send a JSON
       ``{"type": "auth", "token": "<admin_token>"}`` as the first frame.

    Mode 2 avoids leaking the token in server access-logs.
    """
    settings = getattr(ws.app.state, "settings", None)
    if not settings:
        await ws.close(code=1008, reason="Server not ready")
        return

    # Try query-string auth first (backward-compatible)
    qs_token = ws.query_params.get("token", "")
    if qs_token and _hmac.compare_digest(
        qs_token.encode(), settings.admin_token.encode()
    ):
        await ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)
        return

    # Otherwise, accept and wait for an auth message
    await ws.accept()
    import json as _json

    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
        msg = _json.loads(raw)
        token = msg.get("token", "") if isinstance(msg, dict) else ""
        if not _hmac.compare_digest(token.encode(), settings.admin_token.encode()):
            await ws.close(code=1008, reason="Unauthorized")
            return
    except (asyncio.TimeoutError, Exception):
        await ws.close(code=1008, reason="Auth timeout")
        return

    ws_manager._connections.append(ws)
    log.debug(
        "WebSocket client connected via message auth (%d total)",
        len(ws_manager._connections),
    )
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Sync endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/index", dependencies=[Depends(require_peer_auth)])
async def get_index(request: Request):
    db = request.app.state.db
    return [dict(r) for r in db.all_files()]


@app.post("/upload", dependencies=[Depends(require_peer_auth)])
async def upload_file(
    request: Request,
    path: str = Form(...),
    base_hash: str = Form(None),
    origin: str = Form("remote"),
    compressed: str = Form("false"),
    file: UploadFile = File(...),
):
    # Per-IP upload rate limiting (60 uploads per minute)
    client_ip = request.client.host if request.client else "unknown"
    if not _upload_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="Upload rate limit exceeded")

    settings = request.app.state.settings
    db = request.app.state.db
    sync_root = Path(settings.sync_folder).resolve()
    dest = (sync_root / path).resolve()

    if not str(dest).startswith(str(sync_root)):
        raise HTTPException(status_code=403, detail="Path traversal blocked")

    try:
        data = await file.read()

        # Enforce upload size limit
        max_bytes = getattr(settings, "max_upload_mb", 500) * 1_048_576
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {settings.max_upload_mb} MB limit",
            )

        if compressed == "true":
            try:
                data = decompress(data)
            except ValueError as exc:
                raise HTTPException(status_code=413, detail=str(exc))

        incoming_hash = hash_bytes(data)

        if dest.is_file() and base_hash:
            local_hash = calculate_hash(dest)
            if local_hash != base_hash and local_hash != incoming_hash:
                conflict_path = resolve_conflict(
                    dest, data, incoming_hash, origin, db=db
                )
                log.warning("Conflict on %s -> saved as %s", path, conflict_path.name)
                await ws_manager.broadcast(
                    {
                        "event": "conflict",
                        "data": {
                            "path": path,
                            "conflict_file": conflict_path.name,
                            "origin": origin,
                        },
                    }
                )
                return {
                    "status": "conflict",
                    "path": path,
                    "conflict_file": conflict_path.name,
                }

        dest.parent.mkdir(parents=True, exist_ok=True)
        mark_server_write(path)

        # Atomic write: write to a temp file and rename to avoid partial reads
        tmp = dest.with_suffix(dest.suffix + ".synctmp")
        try:
            tmp.write_bytes(data)
            os.replace(str(tmp), str(dest))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

        stat = dest.stat()
        db.upsert_file(path, incoming_hash, stat.st_mtime, stat.st_size, origin=origin)

        log.info("Received: %s (%d bytes)", path, len(data))
        await ws_manager.broadcast(
            {
                "event": "file_uploaded",
                "data": {"path": path, "size": len(data), "origin": origin},
            }
        )
        return {"status": "success", "path": path}

    except OSError as exc:
        log.error("Disk error writing %s: %s", path, exc)
        raise HTTPException(status_code=500, detail=f"Disk error: {exc}")
    finally:
        await file.close()


# ---------------------------------------------------------------------------
# Peer discovery
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Identity and pairing (unauthenticated — safe to expose)
# ---------------------------------------------------------------------------


@app.get("/identity")
async def get_identity(request: Request):
    """Return this node's Device ID, node name, and public key.

    This endpoint is intentionally unauthenticated because all returned
    data is public (the Device ID is a hash of the public cert and the
    public key is, well, public).
    """
    settings = request.app.state.settings
    from utils.certs import get_device_id, get_public_key_pem

    device_id = get_device_id(settings.ssl_cert)
    public_key = get_public_key_pem(settings.ssl_cert)
    return {
        "device_id": device_id,
        "node_id": settings.node_id,
        "public_key_pem": public_key,
    }


_pair_limiter = RateLimiter(window=60.0, limit=10)


@app.post("/pair/request")
async def pair_request(request: Request):
    """Accept an incoming pairing request from another node.

    The remote sends its identity; we add it to the pending-approval list
    so the local user can approve it from the web UI.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not _pair_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="Pairing rate limit exceeded")

    body = await request.json()
    device_id = body.get("device_id", "").strip()
    node_id = body.get("node_id", "").strip()
    url = body.get("url", "").strip()
    public_key_pem = body.get("public_key_pem", "").strip()
    proof = body.get("proof", "").strip()

    if not all([device_id, node_id, url, public_key_pem, proof]):
        raise HTTPException(
            status_code=422,
            detail="device_id, node_id, url, public_key_pem, and proof are required",
        )

    # Verify proof-of-possession: caller must prove they hold the private key
    from utils.certs import verify_pair_proof

    if not verify_pair_proof(public_key_pem, device_id, proof):
        raise HTTPException(
            status_code=403,
            detail="Invalid proof of key ownership \u2014 possible identity spoofing",
        )

    trust_store = getattr(request.app.state, "trust_store", None)
    if trust_store is None:
        raise HTTPException(status_code=503, detail="Trust store not available")

    if trust_store.is_trusted(device_id):
        return {"status": "already_trusted"}

    trust_store.add_pending(device_id, url, node_id, public_key_pem)
    await ws_manager.broadcast(
        {
            "event": "pair_request",
            "data": {
                "device_id": device_id,
                "node_id": node_id,
                "url": url,
            },
        }
    )
    return {"status": "pending"}


@app.post("/pair/complete", dependencies=[Depends(require_peer_auth)])
async def pair_complete(request: Request):
    """Called by the remote after the local user approved the pairing.

    The remote sends its identity so we can confirm mutual trust.
    This endpoint requires authentication (the remote must already be
    trusted from the approval step).
    """
    body = await request.json()
    device_id = body.get("device_id", "").strip()
    node_id = body.get("node_id", "").strip()
    url = body.get("url", "").strip()
    public_key_pem = body.get("public_key_pem", "").strip()

    if not all([device_id, node_id, url, public_key_pem]):
        raise HTTPException(
            status_code=422,
            detail="device_id, node_id, url, and public_key_pem are required",
        )

    trust_store = getattr(request.app.state, "trust_store", None)
    if trust_store is None:
        raise HTTPException(status_code=503, detail="Trust store not available")

    # Ensure this peer is already trusted (must be, since require_peer_auth passed)
    if not trust_store.is_trusted(device_id):
        trust_store.trust_peer(device_id, url, node_id, public_key_pem)

    return {"status": "trusted"}


@app.post("/peers/register", dependencies=[Depends(require_peer_auth)])
async def register_peer(request: Request):
    peer_mgr = getattr(request.app.state, "peer_manager", None)
    if peer_mgr is None:
        raise HTTPException(status_code=503, detail="Peer discovery not enabled")

    body = await request.json()
    url = body.get("url", "").strip()
    node_id = body.get("node_id", "").strip()
    if not url or not node_id:
        raise HTTPException(status_code=422, detail="url and node_id required")

    client_ip = request.client.host if request.client else "unknown"
    ok, msg = peer_mgr.register(url, node_id, requester_ip=client_ip)
    if not ok:
        raise HTTPException(status_code=429 if "Rate" in msg else 400, detail=msg)

    log.info("Peer registered via API: %s (%s) from %s", url, node_id, client_ip)
    await ws_manager.broadcast(
        {
            "event": "peer_registered",
            "data": {"url": url, "node_id": node_id},
        }
    )
    return {"status": "registered", "url": url, "node_id": node_id}


@app.get("/peers", dependencies=[Depends(require_peer_auth)])
async def list_peers(request: Request):
    peer_mgr = getattr(request.app.state, "peer_manager", None)
    if peer_mgr is None:
        return []
    return peer_mgr.all_peers


@app.get("/download", dependencies=[Depends(require_peer_auth)])
async def download_file(request: Request, path: str):
    """Serve a single file from the sync folder so peers can pull it."""
    from fastapi.responses import Response

    settings = request.app.state.settings
    sync_root = Path(settings.sync_folder).resolve()
    src = (sync_root / path).resolve()

    if not str(src).startswith(str(sync_root)):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not src.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        data = src.read_bytes()
        return Response(content=data, media_type="application/octet-stream")
    except OSError as exc:
        log.error("Error reading %s: %s", path, exc)
        raise HTTPException(status_code=500, detail="Read failed")


@app.delete("/delete", dependencies=[Depends(require_peer_auth)])
async def delete_file(request: Request, path: str):
    settings = request.app.state.settings
    db = request.app.state.db
    sync_root = Path(settings.sync_folder).resolve()
    dest = (sync_root / path).resolve()

    if not str(dest).startswith(str(sync_root)):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        mark_server_write(path)
        dest.unlink()
        db.delete_file(path)
        log.info("Deleted: %s", path)
        await ws_manager.broadcast({"event": "file_deleted", "data": {"path": path}})
        return {"status": "deleted", "path": path}
    except Exception as exc:
        log.error("Error deleting %s: %s", path, exc)
        raise HTTPException(status_code=500, detail="Delete failed")


# ---------------------------------------------------------------------------
# Management routes and static frontend
# ---------------------------------------------------------------------------

app.include_router(setup_router)
app.include_router(management_router)

# In a frozen PyInstaller bundle, bundled data lives under sys._MEIPASS.
# In development, it's relative to this file's parent.
if getattr(sys, "frozen", False):
    _web_dist = Path(sys._MEIPASS) / "web" / "dist"
else:
    _web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"

if _web_dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse as _FileResponse

    # Serve the built JS / CSS / image assets from the /assets sub-path.
    # Mounting at "/assets" (instead of "/") avoids a catch-all Mount that
    # could shadow the API routes above — the root cause of
    # "NetworkError when attempting to fetch resource" from the .exe build.
    _assets_dir = _web_dist / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    _index_html = _web_dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """SPA catch-all: serve root-level static files or index.html.

        This route is registered AFTER every API route, so /api/v1/* and
        other endpoints always take priority.
        """
        # Never intercept API routes — if we reach here for /api/*, it
        # means the endpoint doesn't exist.  Return 404 so the frontend
        # can detect the error instead of silently getting HTML.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        # Root-level static files (e.g. vite.svg)
        if full_path and "/" not in full_path:
            candidate = _web_dist / full_path
            if (
                candidate.is_file()
                and candidate.resolve().parent == _web_dist.resolve()
            ):
                return _FileResponse(str(candidate))
        # Everything else gets index.html so React Router can handle it
        if _index_html.is_file():
            return _FileResponse(str(_index_html))
        raise HTTPException(status_code=404, detail="Not found")

else:
    log.warning(
        "Web dashboard not found at %s — run 'npm run build' in web/",
        _web_dist,
    )
