"""TLS and address restrictions for the private two-device link."""
import ipaddress
from pathlib import Path
import ssl

PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"))


def local_address(value):
    address = ipaddress.IPv4Address(value)
    if str(address) == "127.0.0.1" or any(address in network for network in PRIVATE_NETWORKS):
        return str(address)
    raise ValueError("Use an explicit private IPv4 address or 127.0.0.1, not a wildcard/public address")


def server_context(directory):
    directory = Path(directory)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(directory / "server-cert.pem"), str(directory / "server-key.pem"))
    return context


def load_token(directory):
    token = (Path(directory) / "token.txt").read_text(encoding="ascii").strip()
    if len(token) < 32 or not token.isascii():
        raise ValueError("Invalid pairing token; generate credentials before starting")
    return token
