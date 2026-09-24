"""Check a generated client ZIP in isolation and exercise its encrypted link."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="carla-client-package-") as temporary:
        directory = Path(temporary).resolve()
        with zipfile.ZipFile(args.archive) as bundle:
            for entry in bundle.infolist():
                target = (directory / entry.filename).resolve()
                if not target.is_relative_to(directory) or "server-key" in entry.filename:
                    raise RuntimeError("Unsafe or private-server content in client bundle")
                if entry.file_size > 5_000_000:
                    raise RuntimeError("Unexpected large dependency/model in client bundle")
            bundle.extractall(directory)
        client = directory / "secondary laptop"
        for script in ("verify_bundle.py", "check_environment.py", "tests/run_tests.py"):
            subprocess.run([sys.executable, "-I", "-B", str(client / script)], cwd=client,
                           check=True, timeout=30)
        subprocess.run([sys.executable, "-I", "-B", str(ROOT / "check_local_link.py"),
                        "--tls", "--client-root", str(client)], cwd=directory, check=True, timeout=35)
    print("PASS: independent transferred client, manifest, offline tests and encrypted rehearsal")


if __name__ == "__main__":
    main()
