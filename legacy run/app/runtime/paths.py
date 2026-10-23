"""Paths local to this application; never search sibling workspaces."""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "config" / "runtime.json"


def settings():
    configuration = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(configuration, dict):
        raise ValueError("Runtime configuration must be a JSON object")
    return configuration


def carla_root():
    configured = os.environ.get("CARLA_ROOT") or settings().get("carla_root")
    if not isinstance(configured, str) or not configured.strip():
        raise ValueError("carla_root must be a non-empty path")
    expanded = os.path.expandvars(configured)
    if "%" in expanded or "$" in expanded:
        raise ValueError("Unresolved variable in carla_root")
    path = Path(expanded).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def default_policy_path():
    """Select an explicitly configured legacy artifact; never scan other projects."""
    configured = settings().get("legacy_policy_candidates")
    if not isinstance(configured, list) or not configured:
        raise ValueError("legacy_policy_candidates must be a non-empty list")
    root = PROJECT_ROOT.resolve()
    candidates = []
    for item in configured:
        if (not isinstance(item, str) or not item.strip() or
                Path(item).is_absolute() or Path(item).drive or ":" in item):
            raise ValueError("Model candidates must be relative paths inside this application")
        candidate = (root / item).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("Model candidate escapes this application")
        if candidate.is_file() and candidate.stat().st_nlink > 1:
            raise ValueError("Model candidate must be an independent file, not a hard link")
        candidates.append(candidate)
    return next((path for path in candidates if path.is_file()), candidates[0])
