"""Management REST API and first-run setup endpoint."""

from __future__ import annotations

import hmac
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from config import Settings, write_env
from utils.auth import require_admin_token, hash_password, verify_password
from utils.certs import (
    create_pair_proof,
    ensure_certs,
    get_device_id,
    get_device_id_from_pem,
    get_public_key_pem,
)
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
    ts = getattr(request.app.state, "trust_store", None)
    device_id = (
        get_device_id(settings.ssl_cert) if Path(settings.ssl_cert).is_file() else None
    )
    return {
        "node_id": settings.node_id,
        "device_id": device_id,
        "sync_folder": settings.sync_folder,
        "port": settings.port,
        "peer_count": len(pm.all_peers) if pm else 0,
        "trusted_peers": len(ts.trusted_peers) if ts else 0,
        "pending_approvals": len(ts.pending_requests) if ts else 0,
        "indexed_files": db.file_count(),
        "pending_queue": db.pending_count(),
        "uptime": time.time() - _start_time,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _redact_settings(settings: Settings) -> dict[str, Any]:
    data = settings.model_dump()
    for secret in ("api_key", "admin_token", "admin_password_hash"):
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
# Admin token (reveal)
# ---------------------------------------------------------------------------


@router.get("/admin-token", dependencies=[Depends(require_setup)])
async def get_admin_token_value(request: Request):
    """Return the raw admin token (for reveal / copy in the UI)."""
    settings: Settings = request.app.state.settings
    return {"admin_token": settings.admin_token}


@router.post("/change-password", dependencies=[Depends(require_setup)])
async def change_password(request: Request):
    """Change the admin username and/or password."""
    settings: Settings = request.app.state.settings
    body = await request.json()
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")
    new_username = body.get("new_username", "").strip()

    if not current_password or not verify_password(
        current_password, settings.admin_password_hash
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if not new_password or len(new_password) < 8:
        raise HTTPException(
            status_code=422, detail="New password must be at least 8 characters"
        )

    env_updates: dict[str, str] = {
        "ADMIN_PASSWORD_HASH": hash_password(new_password),
    }
    if new_username:
        env_updates["ADMIN_USERNAME"] = new_username

    write_env(env_updates)
    new_settings = Settings.reload()
    request.app.state.settings = new_settings
    return {"status": "ok"}


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
    """Add a peer by URL — fetches its identity automatically.

    This starts a pairing flow: we fetch the remote's identity, trust it
    immediately (the admin explicitly requested this), and send our own
    identity as a pairing request so the remote can approve us.
    """
    body = await request.json()
    url = body.get("url", "").strip().rstrip("/")
    if not url:
        raise HTTPException(status_code=422, detail="url is required")

    settings: Settings = request.app.state.settings
    ts = getattr(request.app.state, "trust_store", None)
    pm = getattr(request.app.state, "peer_manager", None)
    if ts is None or pm is None:
        raise HTTPException(status_code=503, detail="Not ready")

    # Fetch the remote peer's identity
    try:
        http = pm._ensure_http()
        resp = http.get(url + "/identity")
        resp.raise_for_status()
        remote = resp.json()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch peer identity: {exc}",
        )

    remote_device_id = remote.get("device_id", "")
    remote_node_id = remote.get("node_id", "")
    remote_pubkey = remote.get("public_key_pem", "")
    if not all([remote_device_id, remote_node_id, remote_pubkey]):
        raise HTTPException(status_code=502, detail="Peer returned incomplete identity")

    # Verify TLS certificate matches claimed identity (MITM detection)
    try:
        parsed_url = urlparse(url)
        tls_cert_pem = ssl.get_server_certificate(
            (parsed_url.hostname, parsed_url.port or 443)
        )
        tls_device_id = get_device_id_from_pem(tls_cert_pem)
        if tls_device_id != remote_device_id:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"TLS certificate does not match claimed identity "
                    f"(cert={tls_device_id}, claimed={remote_device_id}). "
                    f"Possible man-in-the-middle attack."
                ),
            )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Could not verify TLS cert for %s: %s", url, exc)

    # Trust the remote immediately (the admin chose to add it)
    ts.trust_peer(remote_device_id, url, remote_node_id, remote_pubkey)

    # Register in the peer manager
    pm.register_skip_verify(url, remote_node_id)

    # Send our identity as a pairing request so the remote can approve us
    my_device_id = get_device_id(settings.ssl_cert)
    my_pubkey = get_public_key_pem(settings.ssl_cert)
    my_proof = create_pair_proof(settings.ssl_key, my_device_id)
    mutual_ok = False
    mutual_msg = ""
    try:
        resp = http.post(
            url + "/pair/request",
            json={
                "device_id": my_device_id,
                "node_id": settings.node_id,
                "url": settings.server_url,
                "public_key_pem": my_pubkey,
                "proof": my_proof,
            },
        )
        if resp.status_code == 200:
            result = resp.json()
            mutual_ok = result.get("status") in ("pending", "already_trusted")
            if result.get("status") == "already_trusted":
                mutual_msg = "Already trusted by remote"
            else:
                mutual_msg = "Pairing request sent — waiting for remote approval"
        else:
            mutual_msg = f"Remote returned HTTP {resp.status_code}"
    except Exception as exc:
        mutual_msg = str(exc)

    return {
        "status": "added",
        "url": url,
        "device_id": remote_device_id,
        "node_id": remote_node_id,
        "mutual": mutual_ok,
        "mutual_message": mutual_msg,
    }


@router.delete("/peers", dependencies=[Depends(require_setup)])
async def remove_peer(request: Request, url: str):
    pm = getattr(request.app.state, "peer_manager", None)
    if pm is None:
        raise HTTPException(status_code=503, detail="Peer manager not available")
    pm.remove(url)
    return {"status": "removed", "url": url}


# ---------------------------------------------------------------------------
# Trust management (certificate-based peer identity)
# ---------------------------------------------------------------------------


@router.get("/trust", dependencies=[Depends(require_setup)])
async def list_trusted(request: Request):
    """Return all trusted peers and pending approval requests."""
    ts = getattr(request.app.state, "trust_store", None)
    if ts is None:
        return {"trusted": [], "pending": []}
    return {
        "trusted": ts.trusted_peers,
        "pending": ts.pending_requests,
    }


@router.get("/trust/identity", dependencies=[Depends(require_setup)])
async def get_my_identity(request: Request):
    """Return this node's Device ID and public key."""
    settings: Settings = request.app.state.settings
    device_id = get_device_id(settings.ssl_cert)
    public_key = get_public_key_pem(settings.ssl_cert)
    return {
        "device_id": device_id,
        "node_id": settings.node_id,
        "public_key_pem": public_key,
    }


@router.post("/trust/approve", dependencies=[Depends(require_setup)])
async def approve_peer(request: Request):
    """Approve a pending pairing request.

    After approval, we also send our identity to the remote peer so it can
    trust us back (completing the mutual trust handshake).
    """
    body = await request.json()
    device_id = body.get("device_id", "").strip()
    if not device_id:
        raise HTTPException(status_code=422, detail="device_id is required")

    ts = getattr(request.app.state, "trust_store", None)
    pm = getattr(request.app.state, "peer_manager", None)
    if ts is None:
        raise HTTPException(status_code=503, detail="Trust store not available")

    ok = ts.approve_pending(device_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail="No pending request for this device"
        )

    peer = ts.get_peer(device_id)
    if not peer:
        return {"status": "approved", "mutual": False, "mutual_message": ""}

    # Register in peer manager
    if pm:
        pm.register_skip_verify(peer["url"], peer["node_id"])

    # Send our identity to the remote so it trusts us back
    settings: Settings = request.app.state.settings
    my_device_id = get_device_id(settings.ssl_cert)
    my_pubkey = get_public_key_pem(settings.ssl_cert)
    my_proof = create_pair_proof(settings.ssl_key, my_device_id)
    mutual_ok = False
    mutual_msg = ""
    try:
        if pm:
            http = pm._ensure_http()
        else:
            http = httpx.Client(timeout=10, verify=False)

        # Send a pairing request first (in case the remote doesn't trust us yet)
        resp = http.post(
            peer["url"].rstrip("/") + "/pair/request",
            json={
                "device_id": my_device_id,
                "node_id": settings.node_id,
                "url": settings.server_url,
                "public_key_pem": my_pubkey,
                "proof": my_proof,
            },
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("status") == "already_trusted":
                mutual_ok = True
                mutual_msg = "Already trusted by remote"
            else:
                mutual_msg = "Pairing request sent to remote — they may need to approve"
        else:
            mutual_msg = f"Remote returned HTTP {resp.status_code}"
    except Exception as exc:
        mutual_msg = f"Could not reach remote: {exc}"

    from core.ws import ws_manager
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(
                ws_manager.broadcast(
                    {
                        "event": "peer_trusted",
                        "data": {
                            "device_id": device_id,
                            "node_id": peer.get("node_id", ""),
                            "url": peer.get("url", ""),
                        },
                    }
                )
            )
    except Exception:
        pass

    return {
        "status": "approved",
        "device_id": device_id,
        "mutual": mutual_ok,
        "mutual_message": mutual_msg,
    }


@router.post("/trust/reject", dependencies=[Depends(require_setup)])
async def reject_peer(request: Request):
    """Reject a pending pairing request."""
    body = await request.json()
    device_id = body.get("device_id", "").strip()
    if not device_id:
        raise HTTPException(status_code=422, detail="device_id is required")

    ts = getattr(request.app.state, "trust_store", None)
    if ts is None:
        raise HTTPException(status_code=503, detail="Trust store not available")

    ok = ts.reject_pending(device_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail="No pending request for this device"
        )
    return {"status": "rejected", "device_id": device_id}


@router.delete("/trust", dependencies=[Depends(require_setup)])
async def revoke_trust(request: Request, device_id: str):
    """Remove a peer from the trusted set."""
    ts = getattr(request.app.state, "trust_store", None)
    pm = getattr(request.app.state, "peer_manager", None)
    if ts is None:
        raise HTTPException(status_code=503, detail="Trust store not available")

    peer = ts.get_peer(device_id)
    ok = ts.revoke_peer(device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found in trust store")

    # Also remove from peer manager
    if pm and peer:
        pm.remove(peer.get("url", ""))

    return {"status": "revoked", "device_id": device_id}


# ---------------------------------------------------------------------------
# LAN discovery
# ---------------------------------------------------------------------------


@router.get("/discover", dependencies=[Depends(require_setup)])
async def discover_peers(request: Request):
    """Return SyncCore nodes discovered on the local network."""
    discovery = getattr(request.app.state, "discovery", None)
    if discovery is None:
        return []
    return discovery.discovered_peers


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


@setup_router.get("/setup/status")
async def setup_status(request: Request):
    """Unauthenticated endpoint: check whether first-run setup is complete."""
    settings: Settings = request.app.state.settings
    return {
        "setup_complete": settings.setup_complete,
        "node_id": settings.node_id if settings.setup_complete else None,
    }


@setup_router.post("/login")
async def login(request: Request):
    """Validate username/password and return node info + admin token."""
    settings: Settings = request.app.state.settings
    if not settings.setup_complete:
        raise HTTPException(status_code=400, detail="Setup not complete")
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if (
        not username
        or not password
        or not hmac.compare_digest(username.encode(), settings.admin_username.encode())
        or not verify_password(password, settings.admin_password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"status": "ok", "node_id": settings.node_id, "token": settings.admin_token}


@setup_router.post("/setup")
async def initial_setup(request: Request):
    """Bootstrap a new node or reconfigure an existing one."""
    settings: Settings = request.app.state.settings

    # After first setup, require the admin token to reconfigure.
    if settings.setup_complete:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=409,
                detail="Setup already complete. Please log in with your admin token.",
            )
        token = auth_header.removeprefix("Bearer ").strip()
        if token != settings.admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")

    body = await request.json()

    env_updates: dict[str, str] = {}
    for key in ("sync_folder", "node_id", "peers", "port", "server_url"):
        if key in body and body[key]:
            env_updates[key.upper()] = str(body[key])

    # Auto-detect LAN IP for server_url if not explicitly provided
    if "SERVER_URL" not in env_updates:
        from config import get_lan_ip

        port = env_updates.get("PORT", str(settings.port))
        env_updates["SERVER_URL"] = f"https://{get_lan_ip()}:{port}"

    if "SYNC_FOLDER" in env_updates:
        try:
            validate_folder_path(env_updates["SYNC_FOLDER"], label="sync_folder")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # Set up admin credentials (username + hashed password)
    username = body.get("username", "").strip() or "admin"
    password = body.get("password", "")
    if not settings.setup_complete:
        # First-time setup — password is required
        if not password or len(password) < 8:
            raise HTTPException(
                status_code=422,
                detail="Password must be at least 8 characters",
            )
        env_updates["ADMIN_USERNAME"] = username
        env_updates["ADMIN_PASSWORD_HASH"] = hash_password(password)

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

    device_id = (
        get_device_id(new_settings.ssl_cert)
        if Path(new_settings.ssl_cert).is_file()
        else None
    )

    return {
        "status": "ok",
        "node_id": new_settings.node_id,
        "admin_token": new_settings.admin_token,
        "device_id": device_id,
    }
