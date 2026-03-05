"""Peer registry, health checking, rate limiting, and announcement.

Peers authenticate via RSA-PSS signed requests (``X-Device-ID``,
``X-Timestamp``, ``X-Signature`` headers).  Legacy ``X-API-Key`` headers
are still sent for backward compatibility.
"""

from __future__ import annotations

import ssl
import threading
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

import httpx

from utils.certs import get_device_id, sign_request
from utils.logging import get_logger

log = get_logger("peers")

HEALTH_CHECK_INTERVAL = 30.0
MAX_CONSECUTIVE_FAILURES = 3
RATE_LIMIT_WINDOW = 60.0
RATE_LIMIT_MAX_REQUESTS = 10


class PeerRecord:
    """Lightweight in-memory representation of a known peer."""

    __slots__ = ("url", "node_id", "registered_at", "last_seen", "failures")

    def __init__(self, url: str, node_id: str) -> None:
        self.url = url
        self.node_id = node_id
        self.registered_at = time.time()
        self.last_seen = time.time()
        self.failures = 0

    def touch(self) -> None:
        self.last_seen = time.time()
        self.failures = 0

    def fail(self) -> None:
        self.failures += 1

    @property
    def alive(self) -> bool:
        return self.failures < MAX_CONSECUTIVE_FAILURES


class RateLimiter:
    """Sliding-window rate limiter keyed by IP or identifier."""

    def __init__(
        self, window: float = RATE_LIMIT_WINDOW, limit: int = RATE_LIMIT_MAX_REQUESTS
    ) -> None:
        self._window = window
        self._limit = limit
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            timestamps = self._hits[key]
            timestamps[:] = [t for t in timestamps if now - t < self._window]
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            return True


class PeerManager:
    """Thread-safe registry of discovered peers with background health checks."""

    def __init__(self, settings, client_factory=None) -> None:
        self.settings = settings
        self._peers: dict[str, PeerRecord] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._health_thread: threading.Thread | None = None
        self.rate_limiter = RateLimiter()
        self.max_peers: int = getattr(settings, "max_peers", 20)
        self._client_factory = client_factory
        self._device_id = get_device_id(settings.ssl_cert)
        self._key_path = settings.ssl_key
        self._http = self._make_http_client()

        for url in settings.peer_list:
            self._peers[url] = PeerRecord(url=url, node_id="static")
            log.info("Static peer loaded: %s", url)

    def _auth_headers(self, method: str, path: str, query: str = "") -> dict[str, str]:
        """Generate cert-based auth headers for an outgoing request."""
        return sign_request(self._key_path, self._device_id, method, path, query)

    def _make_http_client(self) -> httpx.Client:
        """Create a fresh httpx client (or return the injected factory)."""
        if self._client_factory is not None:
            return self._client_factory
        ssl_cert = self.settings.ssl_cert
        verify_tls = getattr(self.settings, "verify_tls", False)
        if verify_tls and Path(ssl_cert).is_file():
            verify = ssl.create_default_context(cafile=ssl_cert)
        else:
            verify = False
        return httpx.Client(
            timeout=10.0,
            verify=verify,
        )

    def _ensure_http(self) -> httpx.Client:
        """Return the httpx client, recreating it if it was closed."""
        if self._http.is_closed:
            self._http = self._make_http_client()
        return self._http

    @property
    def active_urls(self) -> list[str]:
        with self._lock:
            return [p.url for p in self._peers.values() if p.alive]

    @property
    def all_peers(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "url": p.url,
                    "node_id": p.node_id,
                    "alive": p.alive,
                    "last_seen": p.last_seen,
                    "failures": p.failures,
                }
                for p in self._peers.values()
            ]

    def register(self, url: str, node_id: str, requester_ip: str) -> tuple[bool, str]:
        """Register a peer after rate-limit and verification checks."""
        if not self.rate_limiter.allow(requester_ip):
            return False, "Rate limit exceeded"
        if node_id == self.settings.node_id:
            return False, "Cannot register self"

        url = url.rstrip("/")

        with self._lock:
            if len(self._peers) >= self.max_peers and url not in self._peers:
                return False, f"Peer limit reached ({self.max_peers})"

        ok, reason = self._verify_peer(url)
        if not ok:
            return False, reason

        with self._lock:
            if url in self._peers:
                self._peers[url].touch()
                log.info("Peer re-registered: %s (%s)", url, node_id)
            else:
                self._peers[url] = PeerRecord(url=url, node_id=node_id)
                log.info("New peer registered: %s (%s)", url, node_id)

        return True, "Registered"

    def register_skip_verify(self, url: str, node_id: str) -> tuple[bool, str]:
        """Register a peer without verification (used for invite-code pairing)."""
        url = url.rstrip("/")
        with self._lock:
            if len(self._peers) >= self.max_peers and url not in self._peers:
                return False, f"Peer limit reached ({self.max_peers})"
            if url in self._peers:
                self._peers[url].touch()
                log.info("Peer re-registered (invite): %s (%s)", url, node_id)
            else:
                self._peers[url] = PeerRecord(url=url, node_id=node_id)
                log.info("New peer registered (invite): %s (%s)", url, node_id)
        return True, "Registered"

    def remove(self, url: str) -> None:
        with self._lock:
            self._peers.pop(url.rstrip("/"), None)

    def _verify_peer(self, url: str) -> tuple[bool, str]:
        """Confirm the remote is a real SyncCore node.

        Checks /health (unauthenticated) and /index (authenticated).
        Returns (ok, reason) so callers can surface precise feedback.
        """
        try:
            http = self._ensure_http()
            resp = http.get(urljoin(url, "/health"))
            if resp.status_code != 200:
                reason = f"Not a SyncCore node (health check returned HTTP {resp.status_code})"
                log.warning("Peer %s: %s", url, reason)
                return False, reason
            index_path = "/index"
            headers = self._auth_headers("GET", index_path)
            resp = http.get(urljoin(url, index_path), headers=headers)
            if resp.status_code == 403:
                reason = (
                    "Peer rejected our identity \u2014 we may not be trusted yet. "
                    "Ask the remote user to approve this device, or use an invite code."
                )
                log.warning("Peer %s: %s", url, reason)
                return False, reason
            if resp.status_code != 200:
                reason = f"Unexpected response from peer (index check returned HTTP {resp.status_code})"
                log.warning("Peer %s: %s", url, reason)
                return False, reason
            return True, "Verified"
        except httpx.ConnectError:
            reason = (
                "Cannot connect \u2014 check the URL and ensure the peer is running"
            )
            log.warning("Peer %s: %s", url, reason)
            return False, reason
        except httpx.TimeoutException:
            reason = "Connection timed out \u2014 the peer may be behind a firewall or unreachable"
            log.warning("Peer %s: %s", url, reason)
            return False, reason
        except httpx.RequestError as exc:
            reason = f"Network error: {exc}"
            log.warning("Peer %s unreachable during verification: %s", url, exc)
            return False, reason

    def _health_loop(self) -> None:
        """Periodically ping all known peers and remove dead ones."""
        while not self._stop.is_set():
            self._stop.wait(HEALTH_CHECK_INTERVAL)
            if self._stop.is_set():
                break

            with self._lock:
                urls = [(p.url, p) for p in self._peers.values()]

            for url, peer in urls:
                try:
                    http = self._ensure_http()
                    resp = http.get(urljoin(url, "/health"))
                    if resp.status_code == 200:
                        with self._lock:
                            peer.touch()
                    else:
                        with self._lock:
                            peer.fail()
                        log.warning(
                            "Peer %s health check failed: HTTP %d",
                            url,
                            resp.status_code,
                        )
                except httpx.RequestError:
                    with self._lock:
                        peer.fail()
                    log.warning("Peer %s unreachable", url)

                if not peer.alive:
                    log.warning(
                        "Peer %s marked dead after %d failures - removing",
                        url,
                        peer.failures,
                    )
                    self.remove(url)

    def announce_to_peers(self) -> None:
        """Broadcast our own URL and node_id to every active peer."""
        my_url = self.settings.server_url
        my_id = self.settings.node_id
        register_path = "/peers/register"
        for url in self.active_urls:
            try:
                http = self._ensure_http()
                headers = self._auth_headers("POST", register_path)
                resp = http.post(
                    urljoin(url, register_path),
                    json={"url": my_url, "node_id": my_id},
                    headers=headers,
                )
                if resp.status_code == 200:
                    log.info("Announced to %s", url)
                else:
                    log.warning(
                        "Announce to %s returned HTTP %d", url, resp.status_code
                    )
            except httpx.RequestError as exc:
                log.warning("Could not announce to %s: %s", url, exc)

    def start(self) -> None:
        self._stop.clear()
        self._ensure_http()  # recreate if closed by a prior stop()
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="peer-health"
        )
        self._health_thread.start()
        log.info(
            "Peer health checker started (interval=%ds)", int(HEALTH_CHECK_INTERVAL)
        )

    def stop(self) -> None:
        self._stop.set()
        if self._health_thread:
            self._health_thread.join(timeout=5)
        if isinstance(self._http, httpx.Client) and not self._http.is_closed:
            self._http.close()
        log.info("Peer manager stopped")
