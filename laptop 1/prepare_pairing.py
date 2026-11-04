"""Generate local TLS pairing material once; never overwrite existing keys."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess

ROOT = Path(__file__).resolve().parent


def protect_directory(directory):
    if os.name == "nt":
        result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True,
                                capture_output=True, text=True)
        sid = next(csv.reader(io.StringIO(result.stdout)))[1]
        project = str(ROOT.parent).replace("'", "''")
        # Use the Windows PowerShell .NET API directly: inherited PowerShell 7
        # module paths can prevent Get-Acl's module from loading in 5.1.
        command = "([System.IO.Directory]::GetAccessControl('" + project + "')).GetOwner([System.Security.Principal.SecurityIdentifier]).Value"
        owner = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                               check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r",
                        *[f"*{identity}:(OI)(CI)F" for identity in sorted({sid, owner, "S-1-5-18"})]],
                       check=True, capture_output=True)
    else:
        directory.chmod(0o700)


def prepare(directory, openssl=None):
    directory = Path(directory).resolve()
    required = ("server-cert.pem", "server-key.pem", "token.txt", "pairing.json")
    existing = directory.exists()
    if existing:
        if not all((directory / name).is_file() for name in required):
            raise RuntimeError("Incomplete credentials directory; preserving it. Choose a new directory or inspect it manually.")
    else:
        executable = openssl or shutil.which("openssl")
        if not executable and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/openssl.exe"
            executable = str(candidate) if candidate.is_file() else None
        if not executable:
            raise RuntimeError("OpenSSL is required only on this host to generate the certificate")
        directory.mkdir(parents=True, exist_ok=False)
        protect_directory(directory)
        subprocess.run([executable, "req", "-x509", "-newkey", "rsa:3072", "-sha256", "-days", "30",
                        "-noenc", "-subj", "/CN=carla-sim-host",
                        "-addext", "subjectAltName=DNS:carla-sim-host",
                        "-addext", "extendedKeyUsage=serverAuth",
                        "-keyout", str(directory / "server-key.pem"),
                        "-out", str(directory / "server-cert.pem")], check=True, capture_output=True)
        with (directory / "token.txt").open("x", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(48) + "\n")
        pem = (directory / "server-cert.pem").read_text(encoding="ascii")
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
        metadata = {"server_name": "carla-sim-host", "certificate_sha256": fingerprint,
                    "port": 8765, "valid_days_at_creation": 30}
        with (directory / "pairing.json").open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(directory / "server-cert.pem"), str(directory / "server-key.pem"))
    metadata = json.loads((directory / "pairing.json").read_text(encoding="utf-8"))
    actual = hashlib.sha256(ssl.PEM_cert_to_DER_cert((directory / "server-cert.pem").read_text(encoding="ascii"))).hexdigest()
    if metadata["certificate_sha256"] != actual:
        raise RuntimeError("Pairing metadata does not match certificate")
    return {"ready": True, "reused": existing, "credentials": str(directory), "certificate_sha256": actual}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "credentials")
    parser.add_argument("--openssl")
    args = parser.parse_args()
    print(json.dumps(prepare(args.directory, args.openssl), indent=2))
