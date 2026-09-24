"""Rehearse two independent processes on localhost. No CARLA, model, or training.

This root maintenance utility only launches the two applications. Neither
application imports or reads its sibling's code/configuration.
"""
import json
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tls', action='store_true', help='Use paired certificates/token without changing network settings')
    parser.add_argument('--client-root', type=Path, default=ROOT / 'secondary laptop', help='Optional independently extracted client folder')
    args = parser.parse_args()
    environment = dict(os.environ, SIM_GATEWAY_TOKEN=secrets.token_urlsafe(32))
    # Deliberately contaminate PYTHONPATH: -I must ignore it in each process.
    environment["PYTHONPATH"] = str(ROOT / "legacy run" / "app")
    with tempfile.TemporaryFile(mode="w+b") as host_log:
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(ROOT / "primary laptop" / "gateway.py"),
             "--port", "0", "--max-runtime-seconds", "25"] + (["--tls"] if args.tls else []),
            cwd=ROOT / "primary laptop", env=environment, stdout=host_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 8
            ready = None
            while time.monotonic() < deadline:
                host_log.seek(0)
                first = host_log.readline()
                if first:
                    ready = json.loads(first)
                    break
                if process.poll() is not None:
                    raise RuntimeError("Host exited before readiness")
                time.sleep(.05)
            if not ready or ready.get("ready") is not True:
                raise RuntimeError("Host readiness timed out")
            for scenario in ("lane_follow", "red_light", "obstacle"):
                result = subprocess.run(
                    [sys.executable, "-I", "-B", str(args.client_root.resolve() / "diagnose.py"),
                     "--port", str(ready["port"]), "--steps", "12", "--scenario", scenario, "--allow-motion"] + (["--tls"] if args.tls else []),
                    cwd=args.client_root.resolve(), env=environment, capture_output=True, text=True, timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode:
                    raise RuntimeError(result.stderr)
                lines = [json.loads(line) for line in result.stdout.splitlines()]
                final = lines[-1]
                if final["steps"] != 12 or final["training"] or final["reason"] != "step_limit":
                    raise RuntimeError("Unexpected diagnostic result")
                if scenario == "red_light" and final["observation"]["speed_mps"] != 0:
                    raise RuntimeError("Red-light guard did not hold")
                print(f"PASS {scenario}: independent processes, 12 fixed-control steps, no training")
            print(f"PASS localhost rehearsal; TLS={args.tls}; toy backend only, no CARLA/learning frameworks loaded")
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
