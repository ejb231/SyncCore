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
from utils.auth import require_api_key
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

# CORS is only needed during development when the frontend runs on a
# different port (e.g. Vite dev server).  In production the React build
# is served from the same origin so CORS headers are unnecessary.
if os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
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


@app.get("/index", dependencies=[Depends(require_api_key)])
async def get_index(request: Request):
    db = request.app.state.db
    return [dict(r) for r in db.all_files()]


@app.post("/upload", dependencies=[Depends(require_api_key)])
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
            data = decompress(data)

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


@app.post("/peers/register", dependencies=[Depends(require_api_key)])
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


@app.get("/peers", dependencies=[Depends(require_api_key)])
async def list_peers(request: Request):
    peer_mgr = getattr(request.app.state, "peer_manager", None)
    if peer_mgr is None:
        return []
    return peer_mgr.all_peers


@app.get("/download", dependencies=[Depends(require_api_key)])
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


@app.delete("/delete", dependencies=[Depends(require_api_key)])
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

    app.mount("/", StaticFiles(directory=str(_web_dist), html=True), name="frontend")
else:
    log.warning(
        "Web dashboard not found at %s — run 'npm run build' in web/",
        _web_dist,
    )
