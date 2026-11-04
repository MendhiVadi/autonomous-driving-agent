"""Launch only this application's gateway; never starts a trainer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from sim_host.gateway import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
