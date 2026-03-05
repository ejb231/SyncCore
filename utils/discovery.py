"""LAN peer auto-discovery via UDP multicast."""

from __future__ import annotations

import json
import socket
import struct
import threading
import time

from utils.logging import get_logger

log = get_logger("discovery")

MULTICAST_GROUP = "239.255.77.88"
MULTICAST_PORT = 5888
BROADCAST_INTERVAL = 15.0


class LANDiscovery:
    """Broadcast and discover SyncCore nodes on the local network."""

    def __init__(self, node_id: str, server_url: str, port: int) -> None:
        self.node_id = node_id
        self.server_url = server_url
        self.port = port
        self._discovered: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._send_thread: threading.Thread | None = None
        self._recv_thread: threading.Thread | None = None

    @property
    def discovered_peers(self) -> list[dict]:
        """Return list of recently discovered peers (seen within last 60s)."""
        now = time.time()
        with self._lock:
            stale = [
                k for k, v in self._discovered.items() if now - v["last_seen"] > 60
            ]
            for k in stale:
                del self._discovered[k]
            return list(self._discovered.values())

    def _build_message(self) -> bytes:
        payload = {
            "service": "synccore",
            "node_id": self.node_id,
            "url": self.server_url,
            "port": self.port,
            "ts": time.time(),
        }
        return json.dumps(payload).encode("utf-8")

    def _send_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    sock.sendto(
                        self._build_message(), (MULTICAST_GROUP, MULTICAST_PORT)
                    )
                except OSError as exc:
                    log.debug("Discovery broadcast failed: %s", exc)
                self._stop.wait(BROADCAST_INTERVAL)
        finally:
            sock.close()

    def _recv_loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", MULTICAST_PORT))
        except OSError as exc:
            log.warning("Cannot bind discovery listener: %s", exc)
            sock.close()
            return

        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError as exc:
            log.warning("Cannot join multicast group: %s", exc)
            sock.close()
            return

        sock.settimeout(2.0)
        try:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("service") != "synccore":
                        continue
                    if msg.get("node_id") == self.node_id:
                        continue  # Ignore our own broadcasts
                    peer_url = msg.get("url", "")
                    node_id = msg.get("node_id", "")
                    if peer_url and node_id:
                        with self._lock:
                            self._discovered[peer_url] = {
                                "url": peer_url,
                                "node_id": node_id,
                                "ip": addr[0],
                                "last_seen": time.time(),
                            }
                except socket.timeout:
                    continue
                except (json.JSONDecodeError, OSError):
                    continue
        finally:
            sock.close()

    def start(self) -> None:
        self._stop.clear()
        self._send_thread = threading.Thread(
            target=self._send_loop, daemon=True, name="discovery-send"
        )
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True, name="discovery-recv"
        )
        self._send_thread.start()
        self._recv_thread.start()
        log.info(
            "LAN discovery started (multicast %s:%d)",
            MULTICAST_GROUP,
            MULTICAST_PORT,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._send_thread:
            self._send_thread.join(timeout=3)
        if self._recv_thread:
            self._recv_thread.join(timeout=3)
        log.info("LAN discovery stopped")
