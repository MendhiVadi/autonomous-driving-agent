"""Malformed models, configuration and recording failures."""
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from learning.assistance import apply_stall_recovery
from learning.contract import POLICY_CONTRACT_VERSION
from learning.model import MLP
from runtime import paths
from telemetry.recorder import EpisodeRecorder


class DataEdgeTests(unittest.TestCase):
    def payload(self):
        model = MLP([8, 24, 16, 3])
        return {"sizes": model.sizes, "weights": model.weights, "biases": model.biases,
                "training_metadata": {"policy_contract_version": POLICY_CONTRACT_VERSION}}

    def test_malformed_model_and_metadata_raise_clear_value_errors(self):
        for payload in (None, [], "model", {"training_metadata": [1]}):
            with self.subTest(payload=payload), patch.object(Path, "read_text", return_value=json.dumps(payload)):
                with self.assertRaises(ValueError):
                    MLP.load("unused.json")

    def test_boolean_and_unrepresentable_model_weights_are_rejected(self):
        for value in (True, 10 ** 400):
            payload = self.payload()
            payload["weights"][0][0][0] = value
            with self.subTest(value=type(value)), patch.object(Path, "read_text", return_value=json.dumps(payload)):
                with self.assertRaises(ValueError):
                    MLP.load("unused.json")

    def test_predict_rejects_invalid_inputs(self):
        model = MLP([8, 24, 16, 3])
        for value in (True, math.nan, math.inf, "1", 10 ** 400):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                model.predict([value] + [0] * 7)

    def test_predict_rejects_overflow_before_tanh_can_hide_it(self):
        model = MLP([8, 24, 16, 3])
        model.weights[0][0] = [1e308] * 8
        with self.assertRaises(ValueError):
            model.predict([1] * 8)

    def test_recovery_checks_every_observation_field(self):
        features = [0, 0, 0, 25, 80, 0, 0, 1]
        for index in range(8):
            for value in (math.nan, math.inf, True):
                bad = list(features)
                bad[index] = value
                with self.subTest(index=index, value=value):
                    self.assertEqual(apply_stall_recovery(bad, .3, 0, 3, active=True),
                                     (0, 1, False))

    def test_recovery_rejects_invalid_timers_and_limits(self):
        for option in ("stalled_for_s", "activation_delay_s", "brake_override_delay_s",
                       "max_accelerator", "maximum_lane_error_m"):
            with self.subTest(option=option):
                kwargs = {"stalled_for_s": 3, "active": True, option: math.nan}
                self.assertEqual(apply_stall_recovery([0, 0, 0, 25, 80, 0, 0, 1], .3, 0, **kwargs),
                                 (0, 1, False))

    def test_default_model_paths_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            outside = Path(temporary) / "external.json"
            outside.write_text("{}", encoding="utf-8")
            for candidates in (["../external.json"], [str(outside)], [], "model.json", [None]):
                with self.subTest(candidates=candidates), patch.object(paths, "PROJECT_ROOT", root):
                    with patch.object(paths, "settings", return_value={"legacy_policy_candidates": candidates}):
                        with self.assertRaises(ValueError):
                            paths.default_policy_path()

    def test_bad_recorder_options_create_no_episode_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            for value in (0, -1, True, math.nan, "abc"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    EpisodeRecorder(temporary, "invalid", flush_every=value)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_model_hardlink_cannot_share_mutable_weights_outside_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            outside = Path(temporary) / "external.json"
            outside.write_text("{}", encoding="utf-8")
            os.link(outside, root / "model.json")
            with patch.object(paths, "PROJECT_ROOT", root):
                with patch.object(paths, "settings", return_value={"legacy_policy_candidates": ["model.json"]}):
                    with self.assertRaises(ValueError):
                        paths.default_policy_path()

    def test_recorder_closes_handle_even_if_flush_fails(self):
        recorder = EpisodeRecorder.__new__(EpisodeRecorder)
        recorder.handle = Mock(closed=False)
        recorder.handle.flush.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            recorder.close()
        recorder.handle.close.assert_called_once()
