"""Local entry point. No sibling source directories are added to imports."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from sim_host.manual import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
