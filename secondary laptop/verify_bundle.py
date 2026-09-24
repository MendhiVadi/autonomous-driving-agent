"""Verify copied source/pairing files against this package's SHA-256 manifest."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
REQUIRED_FILES = frozenset({
    "check_environment.py", "connect.cmd", "diagnose.py", "probe.py", "verify_bundle.py",
    "START_HERE.md", "scripts/network_info.ps1", "tests/run_tests.py",
    "src/rl_client/__init__.py", "src/rl_client/client.py",
    "src/rl_client/transport.py", "src/rl_client/wire.py",
    "credentials/server-cert.pem", "credentials/token.txt", "credentials/pairing.json",
})
SOURCE_SUFFIXES = {".py", ".cmd", ".ps1", ".md", ".json"}
GENERATED_FOLDERS = {"__pycache__", ".venv", ".git", "runs", "checkpoints", "logs"}


def verify(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not REQUIRED_FILES.issubset(manifest):
        raise ValueError("manifest is missing required client source or pairing files")
    for name, expected in manifest.items():
        relative = PurePosixPath(name)
        if (not name or relative.is_absolute() or relative.as_posix() != name
                or ".." in relative.parts or "\\" in name or ":" in name):
            raise ValueError("invalid package path")
        if "server-key" in name.casefold():
            raise ValueError("server private key must not be on this PC")
        if (not isinstance(expected, str) or len(expected) != 64
                or any(character not in "0123456789abcdef" for character in expected)):
            raise ValueError("invalid SHA-256 checksum in manifest")
        target = (root / name).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("package path is missing or outside the client folder")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError(f"checksum mismatch: {name}")
    for directory, folders, files in os.walk(root):
        parts = Path(directory).relative_to(root).parts
        if not parts or parts[0] != "credentials":
            folders[:] = [name for name in folders if name not in GENERATED_FOLDERS]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root)
            if "server-key" in name.casefold():
                raise ValueError("server private key must not be on this PC")
            if relative.as_posix() == "MANIFEST.json":
                continue
            if path.suffix.casefold() in SOURCE_SUFFIXES or relative.parts[0] == "credentials":
                if relative.as_posix() not in manifest:
                    raise ValueError(f"file is not listed in manifest: {relative.as_posix()}")
    return len(manifest)


def main():
    try:
        count = verify()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"FAIL: {exc}") from None
    print(f"PASS: {count} packaged files verified; no server private key")


if __name__ == "__main__":
    main()
