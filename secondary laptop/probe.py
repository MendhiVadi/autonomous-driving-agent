"""Verify TLS and authentication without resetting the simulator."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from rl_client.client import RemoteEnvironment
from rl_client.transport import load_token

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("host")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
started = time.monotonic()
with RemoteEnvironment(load_token(ROOT / "credentials"), host=args.host, port=args.port,
                       certificate=ROOT / "credentials/server-cert.pem") as environment:
    print(json.dumps({"connected": True, "verified_tls": True, "backend": environment.backend,
                      "handshake_ms": round((time.monotonic() - started) * 1000, 1),
                      "training": False}))
