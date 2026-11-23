"""Certificado TLS autoassinado do servidor.

A chave privada é gerada NO servidor e nunca sai dele (fica em DATA_DIR, dentro do
volume). O agente do aluno confia no servidor fixando (pinning) a impressão digital
SHA-256 do certificado — por isso o certificado não precisa ser de uma autoridade
pública, e um PC invasor (que não tem este certificado) é recusado pelo agente.
"""
import datetime
import hashlib
import ipaddress
import os
import socket

from config import DATA_DIR

CERT_PATH = os.path.join(DATA_DIR, "cert.pem")
KEY_PATH = os.path.join(DATA_DIR, "key.pem")


def _local_ips():
    ips = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(info[4][0])
    except OSError:
        pass
    return ips


def _generate(cert_path: str, key_path: str) -> None:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GestorLab")])
    san = [x509.DNSName("localhost")]
    for ip in _local_ips():
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    tmp_key = key_path + ".tmp"
    with open(tmp_key, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    os.replace(tmp_key, key_path)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    tmp_cert = cert_path + ".tmp"
    with open(tmp_cert, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    os.replace(tmp_cert, cert_path)


def fingerprint(cert_path: str = CERT_PATH) -> str:
    """Impressão digital SHA-256 do certificado (DER), em hex minúsculo — o valor que
    vai em server_cert_sha256 no config do agente."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    with open(cert_path, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def ensure_cert() -> tuple:
    """Garante o par certificado/chave em DATA_DIR (gera na primeira vez) e devolve
    (cert_path, key_path, fingerprint_sha256)."""
    if not (os.path.exists(CERT_PATH) and os.path.exists(KEY_PATH)):
        _generate(CERT_PATH, KEY_PATH)
    return CERT_PATH, KEY_PATH, fingerprint(CERT_PATH)
