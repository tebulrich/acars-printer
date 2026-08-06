from __future__ import annotations

from pathlib import Path

from cryptography import x509

from acars_bridge.network import all_tap_hosts
from acars_bridge.tap.tls_certs import ensure_tap_certs


def test_ensure_tap_certs_san_covers_all_providers(tmp_path: Path):
    ca, server, key = ensure_tap_certs(tmp_path, common_name="acars.sayintentions.ai")
    assert ca.exists() and server.exists() and key.exists()
    cert = x509.load_pem_x509_certificate(server.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    names = set(san.value.get_values_for_type(x509.DNSName))
    assert set(all_tap_hosts()).issubset(names)
    cn = cert.subject.get_attributes_for_oid(
        x509.oid.NameOID.COMMON_NAME
    )[0].value
    assert cn == "acars.sayintentions.ai"


def test_ensure_tap_certs_rewrites_cn_on_network_switch(tmp_path: Path):
    ensure_tap_certs(tmp_path, common_name="www.hoppie.nl")
    ensure_tap_certs(tmp_path, common_name="acars.sayintentions.ai")
    cert = x509.load_pem_x509_certificate((tmp_path / "tap-server.pem").read_bytes())
    cn = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value
    assert cn == "acars.sayintentions.ai"
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    names = list(san.value.get_values_for_type(x509.DNSName))
    assert names[0] == "acars.sayintentions.ai"


def test_ensure_tap_certs_upgrades_incomplete_san(tmp_path: Path):
    # First create a leaf that only covers Hoppie (simulates pre-SI install).
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    import datetime as dt

    ca, server, key = ensure_tap_certs(tmp_path)
    ca_cert = x509.load_pem_x509_certificate(ca.read_bytes())
    ca_key_path = tmp_path / "tap-ca-key.pem"
    ca_private = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.UTC)
    narrow = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "www.hoppie.nl")])
        )
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("www.hoppie.nl")]),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_private, hashes.SHA256())
    )
    key.write_bytes(
        leaf_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    server.write_bytes(narrow.public_bytes(serialization.Encoding.PEM))

    ensure_tap_certs(tmp_path)
    refreshed = x509.load_pem_x509_certificate(server.read_bytes())
    san = refreshed.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    names = set(san.value.get_values_for_type(x509.DNSName))
    assert "acars.sayintentions.ai" in names
