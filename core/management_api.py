"""Management REST API and first-run setup endpoint."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from config import Settings, write_env
from utils.auth import require_admin_token
from utils.certs import ensure_certs
from utils.filters import SyncIgnore
from utils.logging import get_log_buffer, get_logger
from utils.paths import validate_folder_path

log = get_logger("management")

_start_time = time.time()

# Keys that require a full server restart when changed.
RESTART_KEYS = {"port", "ssl_cert", "ssl_key"}

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_admin_token)])


def _get(request: Request, attr: str):
    """Retrieve an app-state attribute or raise 503 if unavailable."""
    val = getattr(request.app.state, attr, None)
    if val is None:
        raise HTTPException(status_code=503, detail=f"{attr} not available")
    return val


def require_setup(request: Request) -> None:
    """Dependency that blocks management routes until initial setup is done."""
    settings: Settings = request.app.state.settings
    if not settings.setup_complete:
        raise HTTPException(status_code=503, detail="Setup required")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status", dependencies=[Depends(require_setup)])
async def get_status(request: Request):
    settings: Settings = request.app.state.settings
    db = _get(request, "db")
    pm = getattr(request.app.state, "peer_manager", None)
    return {
        "node_id": settings.node_id,
        "sync_folder": settings.sync_folder,
        "port": settings.port,
        "peer_count": len(pm.all_peers) if pm else 0,
        "indexed_files": db.file_count(),
        "pending_queue": db.pending_count(),
        "uptime": time.time() - _start_time,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _redact_settings(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump()
    for secret in ("api_key", "admin_token"):
        if secret in data:
            data[secret] = "***"
    return data


@router.get("/config", dependencies=[Depends(require_setup)])
async def get_config(request: Request):
    return _redact_settings(request.app.state.settings)


@router.put("/config", dependencies=[Depends(require_setup)])
async def put_config(request: Request):
    body = await request.json()
    settings: Settings = request.app.state.settings
    valid_keys = set(settings.model_fields.keys())
    updates = {k: v for k, v in body.items() if k in valid_keys}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid settings provided")

    if "sync_folder" in updates:
        try:
            validate_folder_path(str(updates["sync_folder"]), label="sync_folder")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    write_env({k.upper(): str(v) for k, v in updates.items()})
    restart_required = bool(RESTART_KEYS & set(updates))

    if not restart_required:
        new_settings = Settings.reload()
        request.app.state.settings = new_settings
        orch = getattr(request.app.state, "orchestrator", None)
        if orch:
            orch.reconfigure(new_settings)

    return {"updated": list(updates.keys()), "restart_required": restart_required}


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@router.get("/files", dependencies=[Depends(require_setup)])
async def list_files(request: Request, search: str | None = None):
    db = _get(request, "db")
    rows = db.search_files(search) if search else db.all_files()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------


@router.get("/conflicts", dependencies=[Depends(require_setup)])
async def list_conflicts(request: Request):
    db = _get(request, "db")
    return [dict(r) for r in db.list_conflicts(resolved=False)]


@router.post("/conflicts/{conflict_id}/resolve", dependencies=[Depends(require_setup)])
async def resolve_conflict(
    request: Request, conflict_id: int, delete_file: bool = False
):
    db = _get(request, "db")
    ok = db.resolve_conflict_record(conflict_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conflict not found")

    if delete_file:
        conflicts = db.list_conflicts(resolved=True)
        for c in conflicts:
            if c["id"] == conflict_id:
                settings: Settings = request.app.state.settings
                conflict_path = Path(settings.sync_folder) / c["conflict_file"]
                if conflict_path.exists():
                    conflict_path.unlink()
                break

    return {"status": "resolved", "id": conflict_id}


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


@router.get("/queue", dependencies=[Depends(require_setup)])
async def list_queue(request: Request):
    db = _get(request, "db")
    return [dict(r) for r in db.all_tasks()]


@router.post("/queue/{task_id}/retry", dependencies=[Depends(require_setup)])
async def retry_task(request: Request, task_id: int):
    orch = getattr(request.app.state, "orchestrator", None)
    if orch and orch.queue_worker:
        ok = orch.queue_worker.retry_task(task_id)
    else:
        db = _get(request, "db")
        ok = db.retry_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "retried", "id": task_id}


@router.delete("/queue", dependencies=[Depends(require_setup)])
async def clear_queue(request: Request):
    orch = getattr(request.app.state, "orchestrator", None)
    if orch and orch.queue_worker:
        count = orch.queue_worker.clear_all()
    else:
        db = _get(request, "db")
        count = db.clear_pending_tasks()
    return {"status": "cleared", "count": count}


@router.post("/queue/pause", dependencies=[Depends(require_setup)])
async def pause_queue(request: Request):
    orch = getattr(request.app.state, "orchestrator", None)
    if orch and orch.queue_worker:
        orch.queue_worker.pause()
    return {"status": "paused"}


@router.post("/queue/resume", dependencies=[Depends(require_setup)])
async def resume_queue(request: Request):
    orch = getattr(request.app.state, "orchestrator", None)
    if orch and orch.queue_worker:
        orch.queue_worker.resume()
    return {"status": "resumed"}


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------


@router.get("/peers", dependencies=[Depends(require_setup)])
async def list_peers(request: Request):
    pm = getattr(request.app.state, "peer_manager", None)
    if pm is None:
        return []
    return pm.all_peers


@router.post("/peers", dependencies=[Depends(require_setup)])
async def add_peer(request: Request):
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="url is required")
    pm = getattr(request.app.state, "peer_manager", None)
    if pm is None:
        raise HTTPException(status_code=503, detail="Peer manager not available")
    ok, msg = pm.register(url, body.get("node_id", "manual"), requester_ip="admin")
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "added", "url": url}


@router.delete("/peers", dependencies=[Depends(require_setup)])
async def remove_peer(request: Request, url: str):
    pm = getattr(request.app.state, "peer_manager", None)
    if pm is None:
        raise HTTPException(status_code=503, detail="Peer manager not available")
    pm.remove(url)
    return {"status": "removed", "url": url}


# ---------------------------------------------------------------------------
# Ignore rules
# ---------------------------------------------------------------------------


@router.get("/ignore", dependencies=[Depends(require_setup)])
async def get_ignore(request: Request):
    settings: Settings = request.app.state.settings
    path = Path(settings.syncignore_path)
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {"content": content}


@router.put("/ignore", dependencies=[Depends(require_setup)])
async def put_ignore(request: Request):
    body = await request.json()
    content = body.get("content", "")
    settings: Settings = request.app.state.settings
    Path(settings.syncignore_path).write_text(content, encoding="utf-8")
    orch = getattr(request.app.state, "orchestrator", None)
    if orch:
        orch.ignore = SyncIgnore(settings.syncignore_path)
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@router.get("/logs", dependencies=[Depends(require_setup)])
async def get_logs(request: Request, level: str | None = None):
    entries = get_log_buffer(level)
    return entries[-200:]


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------


setup_router = APIRouter(prefix="/api/v1")


@setup_router.post("/setup")
async def initial_setup(request: Request):
    """Bootstrap a new node or reconfigure an existing one."""
    settings: Settings = request.app.state.settings

    # After first setup, require the admin token to reconfigure.
    if settings.setup_complete:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Setup already complete - admin token required"
            )
        token = auth_header.removeprefix("Bearer ").strip()
        if token != settings.admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")

    body = await request.json()

    env_updates: dict[str, str] = {}
    for key in ("sync_folder", "api_key", "node_id", "peers", "port", "server_url"):
        if key in body and body[key]:
            env_updates[key.upper()] = str(body[key])

    if "SYNC_FOLDER" in env_updates:
        try:
            validate_folder_path(env_updates["SYNC_FOLDER"], label="sync_folder")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    if "admin_token" not in env_updates:
        env_updates["ADMIN_TOKEN"] = settings.admin_token

    env_updates["SETUP_COMPLETE"] = "true"
    write_env(env_updates)
    ensure_certs(settings.ssl_cert, settings.ssl_key)

    new_settings = Settings.reload()
    request.app.state.settings = new_settings
    new_settings.ensure_folders()

    orch = getattr(request.app.state, "orchestrator", None)
    if orch:
        orch.reconfigure(new_settings)

    return {
        "status": "ok",
        "node_id": new_settings.node_id,
        "admin_token": new_settings.admin_token,
    }
