"""Stable command entry point for the local CARLA cockpit."""
import sys

from cockpit.session import main


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"CARLA error: {exc}", file=sys.stderr)
        sys.exit(1)
