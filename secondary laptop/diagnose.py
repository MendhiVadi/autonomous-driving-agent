"""Run bounded reset/step diagnostics with fixed vehicle controls."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from rl_client.client import RemoteEnvironment
from rl_client.transport import load_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--credentials", type=Path, default=Path(__file__).resolve().parent / "credentials")
    parser.add_argument("--steps", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--scenario", choices=("lane_follow", "red_light", "obstacle"), default="lane_follow")
    parser.add_argument("--allow-motion", action="store_true", help="Apply fixed throttle 0.2; default stays braked")
    args = parser.parse_args()
    if not 1 <= args.steps <= 200:
        parser.error("Diagnostic steps must be between 1 and 200")
    token = load_token(args.credentials) if args.tls else os.environ.get("SIM_GATEWAY_TOKEN", "")
    certificate = args.credentials / "server-cert.pem" if args.tls else None
    with RemoteEnvironment(token, host=args.host, port=args.port, certificate=certificate) as env:
        observation, info = env.reset(seed=args.seed, scenario=args.scenario, max_steps=args.steps)
        print(json.dumps({"reset": info, "observation": observation, "training": False}), flush=True)
        action = {"throttle": 0.2 if args.allow_motion else 0.0,
                  "brake": 0.0 if args.allow_motion else 1.0, "steer": 0.0}
        for _ in range(args.steps):
            observation, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break
        print(json.dumps({"steps": info["step"], "reason": info["reason"],
                          "observation": observation, "training": False}), flush=True)


if __name__ == "__main__":
    main()
