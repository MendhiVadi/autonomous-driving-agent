"""Package a self-contained client for the other PC; never copy the server key."""
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
CLIENT = ROOT / "secondary laptop"
HOST = ROOT / "primary laptop"
PUBLIC_PAIRING = ("server-cert.pem", "token.txt", "pairing.json")


def private_directory(path):
    path.mkdir(exist_ok=False)
    if os.name == "nt":
        output = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True)
        sid = next(csv.reader(io.StringIO(output.stdout)))[1]
        project = str(ROOT).replace("'", "''")
        # Avoid PowerShell module discovery across inherited 5.1/7 environments.
        command = "([System.IO.Directory]::GetAccessControl('" + project + "')).GetOwner([System.Security.Principal.SecurityIdentifier]).Value"
        owner = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                               check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                        *[f"*{identity}:(OI)(CI)F" for identity in sorted({sid, owner, "S-1-5-18"})]],
                       check=True, capture_output=True)
    else:
        path.chmod(0o700)


def main():
    credentials = CLIENT / "credentials"
    for name in PUBLIC_PAIRING:
        if not (HOST / "credentials" / name).is_file():
            raise RuntimeError("Run the host's prepare_pairing.py first")
    if not credentials.exists():
        private_directory(credentials)
    for name in PUBLIC_PAIRING:
        source = HOST / "credentials" / name
        target = credentials / name
        if target.exists():
            if target.read_bytes() != source.read_bytes():
                raise RuntimeError("Existing client pairing differs; refusing to overwrite it")
        else:
            with target.open("xb") as stream:
                stream.write(source.read_bytes())
    destination = ROOT / "handoff"
    if not destination.exists():
        private_directory(destination)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive = destination / f"secondary-pc-{stamp}.zip"
    files = []
    for path in CLIENT.rglob("*"):
        relative = path.relative_to(CLIENT)
        if not path.is_file() or set(relative.parts).intersection({"__pycache__", ".venv", "runs", "checkpoints", "logs", "credentials"}):
            continue
        if path.suffix not in {".py", ".cmd", ".ps1", ".md", ".json"}:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(CLIENT.resolve()):
            raise RuntimeError("Linked source is not portable")
        files.append(path)
    files += [credentials / name for name in PUBLIC_PAIRING]
    manifest = {}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            name = path.relative_to(CLIENT).as_posix()
            data = path.read_bytes()
            manifest[name] = hashlib.sha256(data).hexdigest()
            bundle.writestr("secondary laptop/" + name, data)
        bundle.writestr("secondary laptop/MANIFEST.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or any("server-key" in name for name in bundle.namelist()):
            raise RuntimeError("Bundle verification failed")
    print(json.dumps({"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size,
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "contains_client_secret": True, "contains_server_private_key": False}, indent=2))


if __name__ == "__main__":
    main()
