"""Trusted-peer storage — certificate-pinning trust store.

Each trusted peer is identified by its **Device ID** (SHA-256 fingerprint of
its TLS certificate).  The store persists to a JSON file and is fully
thread-safe so the server, peer manager, and management API can all access
it concurrently.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from utils.logging import get_logger

log = get_logger("trust")


class TrustStore:
    """Thread-safe JSON-backed store of trusted peer identities."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._peers: dict[str, dict] = {}
        self._pending: dict[str, dict] = {}  # awaiting user approval
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text("utf-8"))
                self._peers = data.get("peers", {})
                self._pending = data.get("pending", {})
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load trust store: %s", exc)

    def _save(self) -> None:
        """Atomic-write the store to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"peers": self._peers, "pending": self._pending}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), "utf-8")
        # os.replace is atomic on most file-systems
        os.replace(str(tmp), str(self._path))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_trusted(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._peers

    def get_public_key(self, device_id: str) -> str | None:
        with self._lock:
            peer = self._peers.get(device_id)
            return peer["public_key_pem"] if peer else None

    def get_peer(self, device_id: str) -> dict | None:
        with self._lock:
            info = self._peers.get(device_id)
            if info:
                return {"device_id": device_id, **info}
            return None

    @property
    def trusted_peers(self) -> list[dict]:
        with self._lock:
            return [{"device_id": did, **info} for did, info in self._peers.items()]

    @property
    def pending_requests(self) -> list[dict]:
        with self._lock:
            return [{"device_id": did, **info} for did, info in self._pending.items()]

    @property
    def trusted_device_ids(self) -> set[str]:
        with self._lock:
            return set(self._peers.keys())

    @property
    def trusted_urls(self) -> list[str]:
        with self._lock:
            return [info["url"] for info in self._peers.values()]

    # ------------------------------------------------------------------
    # Trust management
    # ------------------------------------------------------------------

    def trust_peer(
        self,
        device_id: str,
        url: str,
        node_id: str,
        public_key_pem: str,
    ) -> None:
        """Immediately trust a peer (used during pairing or approval)."""
        with self._lock:
            self._peers[device_id] = {
                "url": url,
                "node_id": node_id,
                "public_key_pem": public_key_pem,
                "approved_at": time.time(),
                "last_seen": time.time(),
            }
            self._pending.pop(device_id, None)
            self._save()
        log.info("Trusted peer: %s (%s) at %s", device_id[:16], node_id, url)

    def revoke_peer(self, device_id: str) -> bool:
        """Remove a peer from the trusted set."""
        with self._lock:
            removed = self._peers.pop(device_id, None)
            if removed:
                self._save()
                log.info(
                    "Revoked trust for: %s (%s)", device_id[:16], removed.get("node_id")
                )
                return True
            return False

    def update_peer_url(self, device_id: str, url: str) -> None:
        """Update a trusted peer's URL (e.g. after IP change)."""
        with self._lock:
            if device_id in self._peers:
                self._peers[device_id]["url"] = url
                self._peers[device_id]["last_seen"] = time.time()
                self._save()

    def touch(self, device_id: str) -> None:
        """Mark a trusted peer as recently seen (no disk write)."""
        with self._lock:
            if device_id in self._peers:
                self._peers[device_id]["last_seen"] = time.time()

    # ------------------------------------------------------------------
    # Pending approval requests
    # ------------------------------------------------------------------

    def add_pending(
        self,
        device_id: str,
        url: str,
        node_id: str,
        public_key_pem: str,
    ) -> None:
        """Record an incoming pairing request awaiting user approval."""
        with self._lock:
            # Don't overwrite an already-trusted peer
            if device_id in self._peers:
                return
            self._pending[device_id] = {
                "url": url,
                "node_id": node_id,
                "public_key_pem": public_key_pem,
                "requested_at": time.time(),
            }
            self._save()
        log.info(
            "Pending trust request from: %s (%s) at %s", device_id[:16], node_id, url
        )

    def approve_pending(self, device_id: str) -> bool:
        """Approve a pending request — moves it to trusted peers."""
        with self._lock:
            pending = self._pending.get(device_id)
            if not pending:
                return False
            self._peers[device_id] = {
                "url": pending["url"],
                "node_id": pending["node_id"],
                "public_key_pem": pending["public_key_pem"],
                "approved_at": time.time(),
                "last_seen": time.time(),
            }
            del self._pending[device_id]
            self._save()
        log.info("Approved peer: %s (%s)", device_id[:16], pending["node_id"])
        return True

    def reject_pending(self, device_id: str) -> bool:
        """Reject and discard a pending trust request."""
        with self._lock:
            if device_id in self._pending:
                del self._pending[device_id]
                self._save()
                return True
            return False

    def cleanup_stale_pending(self, max_age: float = 3600.0) -> int:
        """Remove pending requests older than *max_age* seconds."""
        now = time.time()
        removed = 0
        with self._lock:
            stale = [
                did
                for did, info in self._pending.items()
                if now - info.get("requested_at", 0) > max_age
            ]
            for did in stale:
                del self._pending[did]
                removed += 1
            if removed:
                self._save()
        return removed
