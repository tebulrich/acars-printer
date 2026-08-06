from __future__ import annotations

import datetime as dt
import subprocess
from collections.abc import Sequence
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from acars_bridge.network import all_tap_hosts


def ensure_tap_certs(
    directory: Path,
    *,
    common_name: str | None = None,
) -> tuple[Path, Path, Path]:
    """Return (ca_cert, server_cert, server_key), creating/refreshing as needed.

    SAN always covers every known ACARS provider host. ``common_name`` should be
    the *active* upstream hostname so picky TLS stacks (and CN-only checks) match
    SayIntentions vs Hoppie when the network setting changes.
    """
    directory.mkdir(parents=True, exist_ok=True)
    ca_cert = directory / "tap-ca.pem"
    ca_key = directory / "tap-ca-key.pem"
    server_cert = directory / "tap-server.pem"
    server_key = directory / "tap-server-key.pem"
    required = all_tap_hosts()
    cn = (common_name or "").strip() or required[0]
    dns_names = _ordered_dns_names(cn, required)

    if not (ca_cert.exists() and ca_key.exists()):
        _write_ca(ca_cert, ca_key)
    if (
        not (server_cert.exists() and server_key.exists())
        or not _cert_covers(server_cert, required)
        or _cert_common_name(server_cert) != cn
    ):
        _write_server(
            ca_cert,
            ca_key,
            server_cert,
            server_key,
            dns_names=dns_names,
            common_name=cn,
        )
    return ca_cert, server_cert, server_key


def install_ca_trust(ca_cert: Path) -> str | None:
    """Install CA into Windows trust stores. Returns error or None.

    Sims often ignore the per-user store; when we run elevated we also install
    into the Local Machine Root store so HTTPS MITM is trusted.
    """
    try:
        if not os_name_is_windows():
            return "Install the CA cert into your OS trust store manually."

        errors: list[str] = []
        # Machine store first (needs Admin — we already require that for the tap).
        for args in (
            ["certutil", "-addstore", "Root", str(ca_cert)],
            ["certutil", "-user", "-addstore", "Root", str(ca_cert)],
        ):
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                errors.append(detail or f"certutil exit {completed.returncode}")
        # Succeed if at least one store accepted the CA.
        if len(errors) == 2:
            return " | ".join(errors)
        return None
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def os_name_is_windows() -> bool:
    import os

    return os.name == "nt"


def _ordered_dns_names(common_name: str, required: Sequence[str]) -> tuple[str, ...]:
    rest = [h for h in required if h != common_name]
    if common_name in required:
        return (common_name, *rest)
    return (common_name, *required)


def _cert_covers(cert_path: Path, required: Sequence[str]) -> bool:
    try:
        names = _cert_dns_names(cert_path)
    except Exception:  # noqa: BLE001
        return False
    return set(required).issubset(names)


def _cert_dns_names(cert_path: Path) -> set[str]:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return set()
    return set(ext.value.get_values_for_type(x509.DNSName))


def _cert_common_name(cert_path: Path) -> str | None:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if not attrs:
        return None
    return str(attrs[0].value)


def _write_ca(cert_path: Path, key_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ACARS Print Bridge"),
            x509.NameAttribute(NameOID.COMMON_NAME, "ACARS Print Bridge Tap CA"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _write_server(
    ca_cert: Path,
    ca_key: Path,
    cert_path: Path,
    key_path: Path,
    *,
    dns_names: Sequence[str],
    common_name: str,
) -> None:
    ca = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    ca_private = serialization.load_pem_private_key(ca_key.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ACARS Print Bridge"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    san = x509.SubjectAlternativeName([x509.DNSName(h) for h in dns_names])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(san, critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_private, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
