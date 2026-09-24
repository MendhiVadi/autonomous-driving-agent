import math
import unittest

from sim_host.environment import EpisodeEnvironment, action_values, safe_action, validate_snapshot
from sim_host.rehearsal import RehearsalBackend
from sim_host.wire import ProtocolError


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.backend = RehearsalBackend()
        self.env = EpisodeEnvironment(self.backend)
        self.env.reset(seed=7)
        self.addCleanup(self.env.close)

    def test_repeatable_seed(self):
        a = self.env.reset(seed=44)
        self.env.step({"throttle": .2, "brake": 0, "steer": 0})
        self.assertEqual(a, self.env.reset(seed=44))
        self.assertNotEqual(a, self.env.reset(seed=45))

    def test_invalid_actions_brake_and_require_reset(self):
        for value in (True, float("nan"), float("inf"), 10**400, -1, 2, "0.2"):
            with self.subTest(value=str(value)[:20]):
                self.env.reset()
                with self.assertRaises(ProtocolError):
                    self.env.step({"throttle": value, "brake": 0, "steer": 0})
                self.assertFalse(self.env.active)
                self.assertEqual(self.backend.last_action["brake"], 1)

    def test_exact_action_fields(self):
        with self.assertRaises(ProtocolError):
            action_values({"throttle": 0, "brake": 0, "steer": 0, "reverse": True})

    def test_brake_priority_and_limits_are_reported(self):
        requested = {"throttle": 1, "brake": .5, "steer": 1}
        result = self.env.step(requested)
        self.assertEqual(result["info"]["requested_action"], requested)
        self.assertEqual(result["info"]["applied_action"], {"throttle": 0, "brake": .5, "steer": .7})
        self.assertIn("control_limits", result["info"]["interventions"])

    def test_red_light_overrides_throttle(self):
        self.env.reset(scenario="red_light")
        result = self.env.step({"throttle": .2, "brake": 0, "steer": 0})
        self.assertEqual(result["observation"]["speed_mps"], 0)
        self.assertIn("signal_stop", result["info"]["interventions"])

    def test_obstacle_stopping_distance(self):
        self.env.state["speed_mps"] = 4
        self.env.state["obstacle_distance_m"] = 5
        applied, reasons = safe_action({"throttle": .2, "brake": 0, "steer": 0}, self.env.state)
        self.assertEqual(applied["brake"], 1)
        self.assertIn("obstacle_stop", reasons)

    def test_speed_limit(self):
        self.env.state["speed_mps"] = 10
        applied, reasons = safe_action({"throttle": .2, "brake": 0, "steer": 0}, self.env.state)
        self.assertEqual(applied["throttle"], 0)
        self.assertIn("speed_limit", reasons)

    def test_time_limit_truncates_and_brakes(self):
        self.env.reset(max_steps=1)
        result = self.env.step({"throttle": 0, "brake": 1, "steer": 0})
        self.assertFalse(result["terminated"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["info"]["reason"], "step_limit")
        with self.assertRaises(ProtocolError):
            self.env.step({"throttle": 0, "brake": 1, "steer": 0})

    def test_stopping_forever_does_not_earn_reward(self):
        total = 0
        for _ in range(200):
            result = self.env.step({"throttle": 0, "brake": 1, "steer": 0})
            total += result["reward"]
        self.assertTrue(result["truncated"])
        self.assertEqual(result["info"]["reason"], "no_progress")
        self.assertLess(total, 0)

    def test_collision_takes_precedence_over_completion(self):
        self.backend.scenario = "obstacle"
        self.backend.x = self.backend.route_length
        self.env.best_progress = self.backend.x
        result = self.env.step({"throttle": 0, "brake": 1, "steer": 0})
        self.assertEqual(result["info"]["reason"], "collision")
        self.assertLess(result["reward"], 0)

    def test_retracing_route_does_not_pay_twice(self):
        self.env.best_progress = 5
        self.backend.x = 4
        result = self.env.step({"throttle": .2, "brake": 0, "steer": 0})
        self.assertEqual(result["info"]["reward_parts"]["new_progress"], 0)

    def test_invalid_reset_and_observation(self):
        for kw in ({"seed": True}, {"max_steps": 0}, {"scenario": []}, {"seed": -1}):
            with self.assertRaises(ProtocolError):
                self.env.reset(**kw)
        state = dict(self.env.state, speed_mps=math.nan)
        with self.assertRaises(ProtocolError):
            validate_snapshot(state)

    def test_backend_fault_aborts(self):
        def broken(action):
            raise RuntimeError("simulator unavailable")
        self.backend.step = broken
        with self.assertRaises(RuntimeError):
            self.env.step({"throttle": .2, "brake": 0, "steer": 0})
        self.assertFalse(self.env.active)
        self.assertEqual(self.backend.last_action["brake"], 1)
