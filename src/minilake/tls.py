"""Self-signed TLS certificate generation for minilake's native HTTPS support.

minilake can serve HTTPS directly (e.g. on :8443) so the Databricks CLI — which
expects an `https://` host — can talk to it without a separate TLS proxy.

Two modes, both handled by `resolve_cert`:

1. **Bring-your-own cert** — point `MINILAKE_SSL_CERTFILE`/`MINILAKE_SSL_KEYFILE`
   at a cert already issued by a CA your machine trusts (e.g. an internal CA).
   The CLI then trusts minilake with no extra steps.
2. **Auto-generated self-signed** — if TLS is enabled and no cert is provided,
   a self-signed cert (with the configured SANs) is generated once under
   `<data_dir>/certs/` and reused across restarts. Trust it on the client with
   `export SSL_CERT_FILE=<data_dir>/certs/minilake.crt` (Go/Databricks CLI reads
   this) or by importing it into the OS trust store.
"""

import datetime
import ipaddress
import logging
from pathlib import Path
from typing import Iterable, List, Tuple

logger = logging.getLogger(__name__)


def _san_entries(sans: Iterable[str]) -> list:
    """Turn a list of host strings into x509 SAN entries (IP vs DNS aware)."""
    from cryptography import x509

    entries: list = []
    for raw in sans:
        host = raw.strip()
        if not host:
            continue
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            entries.append(x509.DNSName(host))
    return entries


def generate_self_signed(cert_path: Path, key_path: Path, sans: Iterable[str], common_name: str = "minilake") -> None:
    """Write a fresh self-signed cert + key (PEM) covering `sans`."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        # Apple/macOS (enforced by Go's darwin verifier) rejects TLS server certs
        # whose validity exceeds 398 days as "not standards compliant". Stay under
        # it; `resolve_cert` regenerates the cert once it nears expiry.
        .not_valid_after(now + datetime.timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName(_san_entries(sans)), critical=False)
        # CA:TRUE so the cert can act as its own trust anchor when a client trusts
        # it directly (e.g. via SSL_CERT_FILE / keychain import).
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass


def _still_valid(cert_path: Path, min_days_left: int = 2) -> bool:
    """True if the on-disk cert is loadable and not about to expire."""
    from cryptography import x509

    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    except Exception:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return cert.not_valid_after_utc > now + datetime.timedelta(days=min_days_left)


def resolve_cert(
    provided_cert: Path | None,
    provided_key: Path | None,
    cert_dir: Path,
    sans: List[str],
) -> Tuple[Path, Path]:
    """Return (cert_path, key_path) to serve, generating a self-signed pair if
    none was provided. An explicit cert/key always wins (bring-your-own-CA)."""
    if provided_cert and provided_key:
        if not provided_cert.exists() or not provided_key.exists():
            raise FileNotFoundError(f"SSL cert/key not found: {provided_cert}, {provided_key}")
        logger.info(f"TLS: using provided certificate {provided_cert}")
        return provided_cert, provided_key

    cert_path = cert_dir / "minilake.crt"
    key_path = cert_dir / "minilake.key"
    if cert_path.exists() and key_path.exists() and _still_valid(cert_path):
        logger.info(f"TLS: reusing self-signed certificate {cert_path}")
        return cert_path, key_path

    generate_self_signed(cert_path, key_path, sans)
    logger.info(f"TLS: generated self-signed certificate {cert_path} (SANs: {', '.join(sans)})")
    return cert_path, key_path
