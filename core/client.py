"""HTTP(S) client that pushes file changes to peer SyncCore nodes.

Outgoing requests are authenticated using RSA-PSS signatures derived from
the node's TLS private key.  Each request carries ``X-Device-ID``,
``X-Timestamp``, and ``X-Signature`` headers that the remote server
verifies against its trust store.

Legacy ``X-API-Key`` header auth is still sent alongside signatures for
backward compatibility with older peers.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from utils.certs import get_device_id, sign_request
from utils.file_ops import compress, should_compress
from utils.logging import get_logger

log = get_logger("client")


def _make_ssl_ctx(cert_path: str, verify: bool = False):
    """Build an SSL context.

    With *verify=False* (default), disables certificate verification
    for self-signed peer connections.  Set *verify=True* when all
    nodes share a common CA certificate.
    """
    if not verify:
        return False
    if Path(cert_path).is_file():
        return ssl.create_default_context(cafile=cert_path)
    return True  # fall back to system CA store


class SyncClient:
    """Uploads and deletes files on one or more peer nodes."""

    def __init__(self, settings, peer_manager=None) -> None:
        self.settings = settings
        self._peer_manager = peer_manager
        verify_tls = getattr(settings, "verify_tls", False)
        self._device_id = get_device_id(settings.ssl_cert)
        self._key_path = settings.ssl_key
        self._client = httpx.Client(
            timeout=60.0,
            verify=_make_ssl_ctx(settings.ssl_cert, verify=verify_tls),
        )
        if not verify_tls:
            log.info("TLS verification disabled (self-signed certs)")
        self._static_targets: list[str] = (
            settings.peer_list if settings.peer_list else [settings.server_url]
        )

    def _auth_headers(self, method: str, path: str, query: str = "") -> dict[str, str]:
        """Generate certificate-based authentication headers for a request."""
        return sign_request(self._key_path, self._device_id, method, path, query)

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def targets(self) -> list[str]:
        """Return peer URLs from the peer manager, falling back to static config."""
        if self._peer_manager:
            dynamic = self._peer_manager.active_urls
            if dynamic:
                return dynamic
        return self._static_targets

    def upload_file(
        self,
        file_path: str,
        relative_path: str,
        base_hash: str | None = None,
    ) -> None:
        raw = Path(file_path).read_bytes()
        use_compression = should_compress(relative_path, len(raw))
        payload = compress(raw) if use_compression else raw

        data = {
            "path": relative_path,
            "origin": self.settings.node_id,
            "compressed": "true" if use_compression else "false",
        }
        if base_hash:
            data["base_hash"] = base_hash

        for target in self.targets:
            url = urljoin(target, "/upload")
            path = urlparse(url).path
            try:
                files = {"file": (os.path.basename(file_path), payload)}
                headers = self._auth_headers("POST", path)
                resp = self._client.post(url, data=data, files=files, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                if body.get("status") == "conflict":
                    log.warning(
                        "Conflict on %s at %s -> %s",
                        relative_path,
                        target,
                        body.get("conflict_file"),
                    )
                else:
                    log.info("Uploaded %s -> %s", relative_path, target)
            except httpx.HTTPStatusError as exc:
                log.error(
                    "HTTP %d from %s for %s",
                    exc.response.status_code,
                    target,
                    relative_path,
                )
                raise
            except httpx.RequestError as exc:
                log.error(
                    "Network error uploading %s to %s: %s", relative_path, target, exc
                )
                raise

    def delete_file(self, relative_path: str) -> None:
        for target in self.targets:
            url = urljoin(target, "/delete")
            path = urlparse(url).path
            query = urlencode([("path", relative_path)])
            try:
                headers = self._auth_headers("DELETE", path, query)
                resp = self._client.delete(
                    url, params={"path": relative_path}, headers=headers
                )
                resp.raise_for_status()
                log.info("Deleted %s on %s", relative_path, target)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    log.debug("Already gone on %s: %s", target, relative_path)
                else:
                    log.error(
                        "HTTP %d from %s deleting %s",
                        exc.response.status_code,
                        target,
                        relative_path,
                    )
                    raise
            except httpx.RequestError as exc:
                log.error(
                    "Network error deleting %s on %s: %s", relative_path, target, exc
                )
                raise

    def fetch_index(self, target: str | None = None) -> list[dict]:
        url = urljoin(target or self.targets[0], "/index")
        path = urlparse(url).path
        headers = self._auth_headers("GET", path)
        resp = self._client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def download_file_bytes(self, target: str, relative_path: str) -> bytes | None:
        """Download raw bytes from a peer's /download endpoint.

        Returns *None* if the peer doesn't support the endpoint (404).
        Raises on other HTTP/network errors.
        """
        url = urljoin(target, "/download")
        url_path = urlparse(url).path
        query = urlencode([("path", relative_path)])
        try:
            headers = self._auth_headers("GET", url_path, query)
            resp = self._client.get(
                url, params={"path": relative_path}, headers=headers
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.content
        except httpx.RequestError as exc:
            log.error(
                "Network error downloading %s from %s: %s", relative_path, target, exc
            )
            raise

    def close(self) -> None:
        self._client.close()
