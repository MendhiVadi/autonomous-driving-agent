"""Independent standard-library client checks; no model or simulator required."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
