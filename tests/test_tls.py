"""Unit tests for minilake.tls — self-signed cert generation & resolution.

Pure unit tests (no server): they validate the cert minilake serves natively on
HTTPS so the Databricks CLI can reach it without a TLS proxy.
"""

import datetime

import pytest

from minilake import tls

cryptography = pytest.importorskip("cryptography")
from cryptography import x509  # noqa: E402
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID  # noqa: E402


def _load(cert_path):
    return x509.load_pem_x509_certificate(cert_path.read_bytes())


def test_generate_self_signed_has_sans_and_short_validity(tmp_path):
    cert = tmp_path / "minilake.crt"
    key = tmp_path / "minilake.key"
    tls.generate_self_signed(cert, key, ["localhost", "127.0.0.1", "minilake.local"])

    assert cert.exists() and key.exists()
    parsed = _load(cert)

    san = parsed.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    dns = san.get_values_for_type(x509.DNSName)
    assert "localhost" in dns and "minilake.local" in dns

    # serverAuth EKU present
    eku = parsed.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku

    # Apple/macOS rejects TLS certs valid > 398 days.
    lifetime = parsed.not_valid_after_utc - parsed.not_valid_before_utc
    assert lifetime < datetime.timedelta(days=398)


def test_resolve_cert_prefers_provided(tmp_path):
    cert = tmp_path / "byo.crt"
    key = tmp_path / "byo.key"
    tls.generate_self_signed(cert, key, ["localhost"])

    got_cert, got_key = tls.resolve_cert(cert, key, tmp_path / "auto", ["localhost"])
    assert got_cert == cert and got_key == key
    assert not (tmp_path / "auto").exists()  # no auto-gen when BYO provided


def test_resolve_cert_autogenerates_and_reuses(tmp_path):
    cert_dir = tmp_path / "certs"
    c1, k1 = tls.resolve_cert(None, None, cert_dir, ["localhost", "127.0.0.1"])
    assert c1.exists() and k1.exists()
    serial1 = _load(c1).serial_number

    # Second call reuses the same (still-valid) cert, not a fresh one.
    c2, _ = tls.resolve_cert(None, None, cert_dir, ["localhost", "127.0.0.1"])
    assert _load(c2).serial_number == serial1


def test_resolve_cert_regenerates_when_expired(tmp_path, monkeypatch):
    cert_dir = tmp_path / "certs"
    c1, _ = tls.resolve_cert(None, None, cert_dir, ["localhost"])
    serial1 = _load(c1).serial_number

    # Force the validity check to treat the cert as expired.
    monkeypatch.setattr(tls, "_still_valid", lambda *a, **k: False)
    c2, _ = tls.resolve_cert(None, None, cert_dir, ["localhost"])
    assert _load(c2).serial_number != serial1
