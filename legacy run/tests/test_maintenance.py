"""Regression coverage for bounded computation and single-read model loading."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning.contract import POLICY_CONTRACT_VERSION
from learning.model import MLP, load_deployable_policy
from simulation.observations import wrap_angle


class MaintenanceTests(unittest.TestCase):
    def test_angle_boundaries_preserve_sign(self):
        for value, expected in [(180, 180), (-180, -180), (540, 180),
                                (-540, -180), (181, -179), (-181, 179)]:
            self.assertEqual(wrap_angle(value), expected)

    def test_huge_finite_angles_finish_and_remain_bounded(self):
        for value in (1e100, -1e100, 1e308, -1e308):
            self.assertLessEqual(abs(wrap_angle(value)), 180)
        for value in (math.inf, -math.inf, math.nan):
            with self.assertRaises(ValueError):
                wrap_angle(value)

    def test_deployable_policy_is_read_once(self):
        model = MLP([8, 24, 16, 3])
        payload = {"sizes": model.sizes, "weights": model.weights,
                   "biases": model.biases, "training_metadata": {
                       "policy_contract_version": POLICY_CONTRACT_VERSION,
                       "deployable": True, "route_conditioned": True}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            read = Path.read_text
            with patch.object(Path, "read_text", autospec=True, side_effect=read) as reads:
                with patch.dict("os.environ", {"CARLA_NEURAL_VISUAL": "0"}):
                    loaded = load_deployable_policy(path, require_route_conditioned=True)
            self.assertEqual(reads.call_count, 1)
            self.assertEqual(loaded.predict([0] * 8), model.predict([0] * 8))
