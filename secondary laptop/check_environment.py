"""Report Python and optional learning-library availability."""
import importlib.util
import json
from pathlib import Path
import platform

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    print(json.dumps({
        "project": str(root),
        "python": platform.python_version(),
        "packages": {name: importlib.util.find_spec(name) is not None
                     for name in ("torch", "numpy", "gymnasium")},
        "training": "disabled; future trainer will start from scratch",
        "connection": "paired TLS client available; physical-PC verification required",
        "pretrained_weights_loaded": False,
    }, indent=2))
