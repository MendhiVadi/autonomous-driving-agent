"""Command entry point for the neural-driving cockpit (small and large maps)."""
import sys

from cockpit.session import main


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"CARLA error: {exc}", file=sys.stderr)
        sys.exit(1)
