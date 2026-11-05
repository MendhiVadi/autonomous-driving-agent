"""Run the offline regression tests; no CARLA server, no data changes.

    <CARLA_ROOT>\\carla_env\\Scripts\\python.exe tools\\verify.py

When the real ``carla`` package is not importable (a machine without CARLA),
the lightweight stub in ``tests/stubs`` stands in for its value types so the
suite still runs; tests that need the real API skip themselves.
"""
import importlib.util
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'app'))
sys.path.insert(0, str(root / 'tools'))
if importlib.util.find_spec('carla') is None:
    sys.path.insert(0, str(root / 'tests' / 'stubs'))
    print('[verify] real carla package not found; using tests/stubs/carla.py', flush=True)
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
