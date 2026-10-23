"""Independent TLS verification; no server key or simulator dependency."""
import hashlib
import hmac
import ipaddress
from pathlib import Path
import ssl

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"))


def local_address(value):
    address = ipaddress.IPv4Address(value)
    if str(address) == "127.0.0.1" or any(address in network for network in PRIVATE_NETWORKS):
        return str(address)
    raise ValueError("Use the primary device's explicit private IPv4 address")


def secure_socket(connection, certificate):
    pem = Path(certificate).read_text(encoding="ascii")
    expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest()
    # Deliberately do not inherit SSLKEYLOGFILE or the system CA collection.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=pem)
    wrapped = context.wrap_socket(connection, server_hostname="carla-sim-host")
    try:
        actual = hashlib.sha256(wrapped.getpeercert(binary_form=True)).digest()
        if not hmac.compare_digest(actual, expected):
            raise ssl.SSLCertVerificationError("Server certificate does not match the paired device")
        return wrapped
    except Exception:
        wrapped.close()
        raise


def load_token(directory):
    token = (Path(directory) / "token.txt").read_text(encoding="ascii").strip()
    if len(token) < 32 or not token.isascii():
        raise ValueError("Invalid pairing token")
    return token
