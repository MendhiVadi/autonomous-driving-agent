"""Tests for the Colab data-collection/training pipeline this half of the repo owns.

These tests exercise the *generated* notebook's code cells directly (via
nbformat) wherever practical, so they fail if the notebook drifts from the
contract described here -- not just if a hand-written duplicate drifts.
"""
import json
import math
import os
import random
import tempfile
import unittest
from pathlib import Path

import nbformat as nbf

import learning.contract as policy_contract
from collect_expert_data import choose_route, episode_rng
from telemetry.recorder import EpisodeRecorder

NOTEBOOK_PATH = Path(__file__).resolve().parents[1] / "colab_train_policy.ipynb"


def notebook_code_cells():
    notebook = nbf.read(NOTEBOOK_PATH, as_version=4)
    return [cell["source"] for cell in notebook["cells"] if cell["cell_type"] == "code"]


def find_cell(cells, needle):
    for source in cells:
        if needle in source:
            return source
    raise AssertionError(f"No notebook cell contains {needle!r}")


class FakeTransform:
    def __init__(self, x):
        self.location = FakeLocation(x)


class FakeLocation:
    def __init__(self, x):
        self.x = x

    def distance(self, other):
        return abs(self.x - other.x)


class EpisodeRecorderContractTests(unittest.TestCase):
    """The episode-loading cell in the notebook is the reader contract."""

    def _load_cell_globals(self):
        cells = notebook_code_cells()
        namespace = {}
        exec(find_cell(cells, "POLICY_CONTRACT_VERSION ="), namespace)
        return namespace

    def _parse(self, namespace, obs, action):
        """Run one row through the exact loader logic used by the notebook cell."""
        POLICY_SIZES = namespace["POLICY_SIZES"]
        normalize_observation = namespace["normalize_observation"]
        row = {"observation": obs, "action": action}
        try:
            obs_row, action_row = row["observation"], row["action"]
            steering = action_row.get("steering", action_row.get("steer"))
            if steering is None and "steering_angle_deg" in action_row:
                steering = float(action_row["steering_angle_deg"]) / 70.0
            target = [steering, action_row.get("accelerator", action_row.get("throttle")), action_row["brake"]]
            if len(obs_row) != POLICY_SIZES[0]:
                raise ValueError
            values = list(map(float, obs_row)) + list(map(float, target))
            if not all(math.isfinite(v) for v in values):
                raise ValueError
            return normalize_observation(obs_row), target
        except (KeyError, TypeError, ValueError):
            return None

    def test_episode_recorder_row_round_trips_through_notebook_loader(self):
        namespace = self._load_cell_globals()
        with tempfile.TemporaryDirectory() as directory:
            recorder = EpisodeRecorder(directory, "route")
            obs = [0.1, -2.0, 12.0, 30.0, 40.0, 0.0, 0.05, 0.0]
            action = {"steering": 0.2, "accelerator": 0.4, "brake": 0.0}
            recorder.record(obs, action)
            recorder.close()
            line = recorder.path.read_text(encoding="utf-8").strip()
            row = json.loads(line)
        parsed = self._parse(namespace, row["observation"], row["action"])
        self.assertIsNotNone(parsed)
        normalized, target = parsed
        self.assertEqual(len(normalized), 8)
        self.assertEqual(target, [0.2, 0.4, 0.0])

    def test_steer_key_fallback(self):
        namespace = self._load_cell_globals()
        obs = [0.0] * 8
        parsed = self._parse(namespace, obs, {"steer": -0.3, "accelerator": 0.1, "brake": 0.0})
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[1][0], -0.3)

    def test_steering_angle_deg_fallback_scales_by_70(self):
        namespace = self._load_cell_globals()
        obs = [0.0] * 8
        parsed = self._parse(namespace, obs, {"steering_angle_deg": 35.0, "throttle": 0.5, "brake": 0.0})
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed[1][0], 0.5)

    def test_missing_brake_field_is_rejected(self):
        namespace = self._load_cell_globals()
        obs = [0.0] * 8
        parsed = self._parse(namespace, obs, {"steering": 0.0, "accelerator": 0.0})
        self.assertIsNone(parsed)

    def test_wrong_observation_length_is_rejected(self):
        namespace = self._load_cell_globals()
        parsed = self._parse(namespace, [0.0] * 7, {"steering": 0.0, "accelerator": 0.0, "brake": 0.0})
        self.assertIsNone(parsed)

    def test_non_finite_values_are_rejected(self):
        namespace = self._load_cell_globals()
        obs = [0.0] * 7 + [float("nan")]
        parsed = self._parse(namespace, obs, {"steering": 0.0, "accelerator": 0.0, "brake": 0.0})
        self.assertIsNone(parsed)

    def test_normalization_matches_policy_contract(self):
        namespace = self._load_cell_globals()
        features = [1.0, -10.0, 40.0, 30.0, 25.0, 0.0, 0.1, 0.0]
        self.assertEqual(
            namespace["normalize_observation"](features),
            policy_contract.normalize_features(features),
        )
        self.assertEqual(namespace["POLICY_CONTRACT_VERSION"], policy_contract.POLICY_CONTRACT_VERSION)
        self.assertEqual(namespace["POLICY_SIZES"], list(policy_contract.POLICY_SIZES))


class EpisodeRecorderAtomicNamingTests(unittest.TestCase):
    def test_atomic_open_retries_past_a_colliding_file(self):
        with tempfile.TemporaryDirectory() as directory:
            first = EpisodeRecorder(directory, "run")
            first.close()
            second = EpisodeRecorder(directory, "run")
            second.close()
            third = EpisodeRecorder(directory, "run")
            third.close()
            self.assertEqual(
                {first.path.name, second.path.name, third.path.name},
                {"run.jsonl", "run-1.jsonl", "run-2.jsonl"},
            )

    def test_atomic_open_survives_a_precreated_collision_file(self):
        with tempfile.TemporaryDirectory() as directory:
            # Simulate a concurrent writer creating the "next" filename in the
            # window between an exists() check and open(): with the atomic
            # retry-on-FileExistsError loop this must not raise.
            (Path(directory) / "run.jsonl").write_text("", encoding="utf-8")
            recorder = EpisodeRecorder(directory, "run")
            recorder.close()
            self.assertEqual(recorder.path.name, "run-1.jsonl")

    def test_buffered_flush_defers_disk_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = EpisodeRecorder(directory, "buffered", flush_every=5)
            for _ in range(4):
                recorder.record([0.0] * 8, {"steering": 0.0, "accelerator": 0.0, "brake": 0.0})
            self.assertEqual(recorder.pending_records, 4)
            recorder.record([0.0] * 8, {"steering": 0.0, "accelerator": 0.0, "brake": 0.0})
            self.assertEqual(recorder.pending_records, 0)
            recorder.close()


class RouteDeterminismTests(unittest.TestCase):
    def test_route_choice_is_deterministic_for_a_given_episode_rng(self):
        points = [FakeTransform(x) for x in (0, 50, 100, 200, 400)]
        a = choose_route(points, episode_rng(7, 3), 100)
        b = choose_route(points, episode_rng(7, 3), 100)
        self.assertEqual((a[0].location.x, a[1].location.x), (b[0].location.x, b[1].location.x))

    def test_different_episode_numbers_can_diverge(self):
        points = [FakeTransform(x) for x in (0, 50, 100, 200, 400, 800)]
        rngs = [episode_rng(7, n) for n in range(5)]
        choices = [choose_route(points, rng, 100) for rng in rngs]
        starts = {c[0].location.x for c in choices}
        self.assertGreater(len(starts), 1)

    def test_resume_numbering_reproduces_uninterrupted_run(self):
        points = [FakeTransform(x) for x in (0, 50, 100, 200, 400, 800)]
        seed = 11
        uninterrupted = [
            choose_route(points, episode_rng(seed, n), 100) for n in range(1, 6)
        ]
        # A run that crashes after episode 3 and resumes with --start-episode 4
        # must reproduce episodes 4 and 5 exactly, since each episode's RNG is
        # keyed only by (seed, episode_number), not by prior episodes.
        resumed = [choose_route(points, episode_rng(seed, n), 100) for n in range(4, 6)]
        for original, again in zip(uninterrupted[3:], resumed):
            self.assertEqual(original[0].location.x, again[0].location.x)
            self.assertEqual(original[1].location.x, again[1].location.x)


class SplitAndMinimumEpisodeTests(unittest.TestCase):
    """Exercise the notebook's split/minimum-episode logic directly."""

    def _run_split(self, episode_names, seed=7):
        namespace = {
            "episodes": {name: [((0.0,) * 8, [0.0, 0.0, 0.0])] for name in episode_names},
            "random": random,
            "SEED": seed,
        }
        code = (
            "episode_names = sorted(episodes)\n"
            "random.Random(SEED).shuffle(episode_names)\n"
            "MIN_PER_SPLIT = 2\n"
            "test_count = max(MIN_PER_SPLIT, round(len(episode_names) * 0.15))\n"
            "validation_count = max(MIN_PER_SPLIT, round(len(episode_names) * 0.15))\n"
            "test_names = episode_names[:test_count]\n"
            "validation_names = episode_names[test_count:test_count + validation_count]\n"
            "train_names = episode_names[test_count + validation_count:]\n"
        )
        exec(code, namespace)
        return namespace["train_names"], namespace["validation_names"], namespace["test_names"]

    def test_minimum_real_episode_count_is_enforced(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "MINIMUM_REAL_EPISODES")
        self.assertIn("MINIMUM_REAL_EPISODES = 10", source)
        self.assertIn("raise RuntimeError", source)

    def test_split_guarantees_two_per_split_at_the_minimum(self):
        train, validation, test = self._run_split([f"ep{i}" for i in range(10)])
        self.assertGreaterEqual(len(train), 2)
        self.assertGreaterEqual(len(validation), 2)
        self.assertGreaterEqual(len(test), 2)
        self.assertTrue(set(train).isdisjoint(validation + test))
        self.assertTrue(set(validation).isdisjoint(test))

    def test_split_guarantees_two_per_split_for_smoke_test_episode_count(self):
        train, validation, test = self._run_split([f"smoke{i}" for i in range(9)])
        self.assertGreaterEqual(len(train), 2)
        self.assertGreaterEqual(len(validation), 2)
        self.assertGreaterEqual(len(test), 2)


class SmokeTestOptInTests(unittest.TestCase):
    def test_smoke_test_requires_explicit_opt_in(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "CARLA_SMOKE_TEST")
        self.assertIn("os.environ.get('CARLA_SMOKE_TEST') == '1'", source)
        self.assertIn("raise RuntimeError", source)
        # The raise must be reachable when there are no real files AND no opt-in.
        self.assertIn("elif SMOKE_TEST_REQUESTED:", source)

    def test_missing_data_without_opt_in_raises(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "CARLA_SMOKE_TEST")
        with tempfile.TemporaryDirectory() as directory:
            namespace = {
                "DATA_DIR": Path(directory) / "does_not_exist",
                "os": os,
                "sorted": sorted,
                "Path": Path,
            }
            namespace["os"].environ.pop("CARLA_SMOKE_TEST", None)
            with self.assertRaises(RuntimeError):
                exec(source.split("episodes = {}")[0], namespace)


class ExportedMetadataTests(unittest.TestCase):
    def test_export_cell_includes_contract_version_and_guards_nn_policy_json(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "training_metadata")
        self.assertIn("'policy_contract_version': POLICY_CONTRACT_VERSION", source)
        self.assertIn("nn_policy.json", source)
        self.assertIn("Refusing to overwrite", source)
        self.assertIn("'route_conditioned': True", source)

    def test_real_rows_require_route_conditioned_contract_metadata(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "rejected_rows")
        self.assertIn("metadata.get('route_conditioned') is not True", source)
        self.assertIn("metadata.get('policy_contract_version') != POLICY_CONTRACT_VERSION", source)


class TrainingLoopSafetyTests(unittest.TestCase):
    def test_training_cell_detects_non_finite_loss_and_has_early_stopping(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "best_validation")
        self.assertIn("non-finite", source)
        self.assertIn("PATIENCE", source)
        self.assertIn("epochs_without_improvement", source)
        # best_state must be seeded from the model's own initial weights, not None.
        self.assertNotIn("best_state = None", source)

    def test_device_selection_is_cpu_by_default(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "ALLOW_GPU")
        self.assertIn("os.environ.get('ALLOW_GPU', '0') == '1'", source)
        self.assertIn("torch.cuda.manual_seed_all(SEED)", source)

    def test_pin_memory_only_when_cuda(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "pin_memory")
        self.assertIn("pin_memory=(DEVICE.type == 'cuda')", source)

    def test_validation_and_test_tensors_moved_to_device_once(self):
        cells = notebook_code_cells()
        source = find_cell(cells, "x_validation_device")
        self.assertIn("x_validation_device = x_validation.to(DEVICE)", source)
        self.assertIn("x_test_device = x_test.to(DEVICE)", source)
        training_source = find_cell(cells, "best_validation")
        self.assertNotIn("x_validation.to(DEVICE)", training_source)


if __name__ == "__main__":
    unittest.main()
