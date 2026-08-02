from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from acars_bridge.tap.hosts import TAP_HOSTS


def ensure_tap_certs(directory: Path) -> tuple[Path, Path, Path]:
    """Return (ca_cert, server_cert, server_key), creating them if needed."""
    directory.mkdir(parents=True, exist_ok=True)
    ca_cert = directory / "tap-ca.pem"
    ca_key = directory / "tap-ca-key.pem"
    server_cert = directory / "tap-server.pem"
    server_key = directory / "tap-server-key.pem"

    if not (ca_cert.exists() and ca_key.exists()):
        _write_ca(ca_cert, ca_key)
    if not (server_cert.exists() and server_key.exists()):
        _write_server(ca_cert, ca_key, server_cert, server_key)
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


def _write_server(ca_cert: Path, ca_key: Path, cert_path: Path, key_path: Path) -> None:
    ca = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    ca_private = serialization.load_pem_private_key(ca_key.read_bytes(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ACARS Print Bridge"),
            x509.NameAttribute(NameOID.COMMON_NAME, "www.hoppie.nl"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    san = x509.SubjectAlternativeName([x509.DNSName(h) for h in TAP_HOSTS])
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
