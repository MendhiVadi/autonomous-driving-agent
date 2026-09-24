"""Read-only layout, syntax, local-import and documentation-link audit."""
import ast
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
PROJECTS = {
    "legacy run": ("app", "tools", "tests", "scripts", "run", "config"),
    "primary laptop": ("src", "tests", "scripts", "config", "tools"),
    "secondary laptop": ("src", "tests", "scripts", "config"),
}
SKIP = {"__pycache__", ".venv", ".git", "logs", "backups", "exports", "episodes",
        "artifacts", "colab_artifacts", "Claude outputs", "checkpoints", "runs", "credentials", "handoff", "cache"}
LEGACY_MODULES = {"cockpit", "vehicle", "simulation", "learning", "runtime", "telemetry",
                  "neural_drive_agent", "spawn_car", "scenic_drive", "stack_supervisor",
                  "collect_expert_data", "agent_drive", "neural_presentation"}


def active_files(project):
    # Prune before descent: environments, recordings and backups can contain
    # far more files than the source being checked.
    for directory, folders, names in os.walk(project):
        folders[:] = [name for name in folders if name not in SKIP]
        for name in names:
            if name not in SKIP:
                path = Path(directory) / name
                if path.is_file():
                    yield path


def audit():
    errors = []
    counts = {"python_files": 0, "local_imports": 0, "links": 0}
    documentation = [ROOT / "README.md"]
    for name, folders in PROJECTS.items():
        project = ROOT / name
        if not project.is_dir():
            errors.append(f"Missing application: {name}")
            continue
        local_roots = [project / folder for folder in ("src", "app", "tools", "tests")]
        local_names = {p.stem for base in local_roots if base.is_dir()
                       for p in base.iterdir() if p.is_dir() or p.suffix == ".py"}
        forbidden = ({"sim_host", "rl_client"} if name == "legacy run" else
                     LEGACY_MODULES | ({"rl_client"} if name == "primary laptop" else {"sim_host"}))
        for path in active_files(project):
            relative = path.relative_to(project)
            if path.is_symlink() or path.stat().st_nlink > 1 or not path.resolve().is_relative_to(project.resolve()):
                errors.append(f"Linked file is not independent: {path}")
            if path.suffix == ".md":
                documentation.append(path)
            if path.suffix not in {".py", ".ps1", ".cmd", ".json"}:
                continue
            if len(relative.parts) > 1 and relative.parts[0] not in folders:
                continue
            source = path.read_text(encoding="utf-8-sig")
            for sibling in PROJECTS.keys() - {name}:
                if sibling.casefold() in source.casefold():
                    errors.append(f"Sibling path/reference in executable source: {path}: {sibling}")
            if path.suffix != ".py":
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                errors.append(str(exc))
                continue
            counts["python_files"] += 1
            for node in ast.walk(tree):
                imports = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                           [item.name for item in node.names] if isinstance(node, ast.Import) else [])
                for module in imports:
                    top = module.split(".")[0]
                    if top in forbidden:
                        errors.append(f"Cross-application import: {path}: {module}")
                    if top not in local_names:
                        continue
                    counts["local_imports"] += 1
                    target = Path(*module.split("."))
                    if not any((base / target).is_dir() or (base / target.with_suffix(".py")).is_file()
                               for base in local_roots):
                        errors.append(f"Missing local import: {path}: {module}")
            for match in re.finditer(r'(?:app|src|scripts|tools)[/\\][\w/\\.-]+\.(?:py|cmd|ps1)', source):
                target = project / match.group().replace("\\", "/")
                if not target.is_file():
                    errors.append(f"Missing script target: {path}: {match.group()}")
    for path in documentation:
        source = path.read_text(encoding="utf-8")
        for raw in re.findall(r'\[[^\]]*\]\(([^)]+)\)', source):
            target = unquote(raw.strip().strip("<>").split("#")[0])
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            counts["links"] += 1
            if not (path.parent / target).exists():
                errors.append(f"Broken document link: {path}: {target}")
    return counts, errors


if __name__ == "__main__":
    counts, errors = audit()
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Checked {counts}; {'FAILED' if errors else 'PASS'}")
    raise SystemExit(bool(errors))
