"""Self-signed TLS certificate generation and device-identity helpers.

Each SyncCore node is identified by a **Device ID** — the SHA-256 fingerprint
of its TLS certificate, formatted as ``XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX``.
Peers authenticate each other by signing requests with their private key and
verifying signatures against the pinned public key stored in the trust store.
"""

from __future__ import annotations

import base64
import datetime
import ipaddress
import os
import platform
import subprocess
import time
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as _padding, rsa
from cryptography.x509.oid import NameOID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _restrict_windows_acl(path: Path) -> None:
    """Restrict a file to the current user only via icacls on Windows."""
    try:
        username = os.environ.get("USERNAME", "")
        if not username:
            return
        # Remove inherited permissions, grant full control only to current user
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(R)"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass  # best-effort; don't block startup


# ---------------------------------------------------------------------------
# Certificate generation
# ---------------------------------------------------------------------------


def generate_self_signed_cert(
    cert_path: str | Path,
    key_path: str | Path,
    cn: str = "SyncCore",
    days: int = 365,
) -> None:
    """Create a 2048-bit RSA key + self-signed X.509 cert with localhost SAN."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("*.local"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    Path(key_path).write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    Path(cert_path).write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # Restrict private key permissions.
    if platform.system() == "Windows":
        _restrict_windows_acl(Path(key_path))
    else:
        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o644)


def ensure_certs(cert_path: str | Path, key_path: str | Path) -> bool:
    """Generate certs if they don't already exist. Returns True if created."""
    cert_path, key_path = Path(cert_path), Path(key_path)
    if cert_path.is_file() and key_path.is_file():
        return False
    generate_self_signed_cert(cert_path, key_path)
    return True


# ---------------------------------------------------------------------------
# Device identity — derived from the certificate fingerprint
# ---------------------------------------------------------------------------


def get_device_id(cert_path: str | Path) -> str:
    """Compute the Device ID from the SHA-256 fingerprint of a certificate.

    Returns a string like ``A1B2C3D4-E5F6A7B8-C9D0E1F2-A3B4C5D6``.
    """
    cert_pem = Path(cert_path).read_bytes()
    cert = x509.load_pem_x509_certificate(cert_pem)
    fingerprint = cert.fingerprint(hashes.SHA256())
    hex_str = fingerprint.hex().upper()
    # Use the first 32 hex chars (128 bits) — plenty for uniqueness
    chunks = [hex_str[i : i + 8] for i in range(0, 32, 8)]
    return "-".join(chunks)


def get_public_key_pem(cert_path: str | Path) -> str:
    """Extract the PEM-encoded public key from a certificate file."""
    cert_pem = Path(cert_path).read_bytes()
    cert = x509.load_pem_x509_certificate(cert_pem)
    return (
        cert.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


# ---------------------------------------------------------------------------
# Request signing and verification (RSA-PSS + SHA-256)
# ---------------------------------------------------------------------------


def sign_request(
    key_path: str | Path, device_id: str, method: str, path: str
) -> dict[str, str]:
    """Produce authentication headers for an outgoing peer request.

    Returns a dict with ``X-Device-ID``, ``X-Timestamp``, and ``X-Signature``.
    """
    timestamp = str(int(time.time()))
    message = f"{device_id}:{timestamp}:{method.upper()}:{path}".encode()

    key_pem = Path(key_path).read_bytes()
    private_key = serialization.load_pem_private_key(key_pem, password=None)
    signature = private_key.sign(
        message,
        _padding.PSS(
            mgf=_padding.MGF1(hashes.SHA256()),
            salt_length=_padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "X-Device-ID": device_id,
        "X-Timestamp": timestamp,
        "X-Signature": base64.b64encode(signature).decode(),
    }


def verify_signature(public_key_pem: str, message: bytes, signature: bytes) -> bool:
    """Verify an RSA-PSS signature against a PEM-encoded public key.

    Returns True if valid, False otherwise.
    """
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        public_key.verify(
            signature,
            message,
            _padding.PSS(
                mgf=_padding.MGF1(hashes.SHA256()),
                salt_length=_padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False
