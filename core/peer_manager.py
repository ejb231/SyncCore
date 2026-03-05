"""Peer registry, health checking, rate limiting, and announcement."""

from __future__ import annotations

import ssl
import threading
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

import httpx

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

        ssl_cert = settings.ssl_cert
        verify_tls = getattr(settings, "verify_tls", False)
        if verify_tls and Path(ssl_cert).is_file():
            verify = ssl.create_default_context(cafile=ssl_cert)
        else:
            verify = False
        self._http = client_factory or httpx.Client(
            timeout=10.0,
            verify=verify,
            headers={"x-api-key": settings.api_key},
        )

        for url in settings.peer_list:
            self._peers[url] = PeerRecord(url=url, node_id="static")
            log.info("Static peer loaded: %s", url)

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

        if not self._verify_peer(url):
            return False, "Peer failed verification handshake"

        with self._lock:
            if url in self._peers:
                self._peers[url].touch()
                log.info("Peer re-registered: %s (%s)", url, node_id)
            else:
                self._peers[url] = PeerRecord(url=url, node_id=node_id)
                log.info("New peer registered: %s (%s)", url, node_id)

        return True, "Registered"

    def remove(self, url: str) -> None:
        with self._lock:
            self._peers.pop(url.rstrip("/"), None)

    def _verify_peer(self, url: str) -> bool:
        """Confirm the remote is a real SyncCore node with a matching API key."""
        try:
            resp = self._http.get(urljoin(url, "/health"))
            if resp.status_code != 200:
                log.warning(
                    "Peer %s failed health check: HTTP %d", url, resp.status_code
                )
                return False
            resp = self._http.get(urljoin(url, "/index"))
            if resp.status_code == 403:
                log.warning("Peer %s rejected our API key", url)
                return False
            if resp.status_code != 200:
                log.warning(
                    "Peer %s failed index check: HTTP %d", url, resp.status_code
                )
                return False
            return True
        except httpx.RequestError as exc:
            log.warning("Peer %s unreachable during verification: %s", url, exc)
            return False

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
                    resp = self._http.get(urljoin(url, "/health"))
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
        for url in self.active_urls:
            try:
                resp = self._http.post(
                    urljoin(url, "/peers/register"),
                    json={"url": my_url, "node_id": my_id},
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
        if isinstance(self._http, httpx.Client):
            self._http.close()
        log.info("Peer manager stopped")
