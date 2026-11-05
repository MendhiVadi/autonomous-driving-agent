"""The bundled bootstrap policy must load through the real loader and drive a route.

A kinematic bicycle car follows a planned route (straight, 90-degree turn,
straight) through the same chain the cockpit uses: route-conditioned
observation, normalisation, the saved network, lane assistance, stall recovery,
speed limiting and the steering/throttle limiters. This is a CARLA-free check
that the fallback weights produce sensible, bounded driving; it is not a claim
about real simulator behaviour.
"""
import json
import math
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from cockpit.graphics import (apply_scene_streaming_limit, apply_speed_sensitive_steering,  # noqa: E402
                              apply_turn_stability)
from learning.assistance import (apply_lane_assistance, apply_stall_recovery,  # noqa: E402
                                 is_stall_candidate, limit_neural_speed)
from learning.contract import POLICY_CONTRACT_VERSION, normalize_features  # noqa: E402
from learning.model import load_deployable_policy  # noqa: E402
from simulation.observations import wrap_angle  # noqa: E402

POLICY = ROOT / "nn_policy_bootstrap.json"
DT = 0.05
WHEELBASE_M = 2.8
MAX_WHEEL_ANGLE_DEG = 70.0
TARGET_KMH = 30.0
LOOKAHEAD_WAYPOINTS = 4   # 8 m at the planner's 2 m spacing, as in the cockpit


def build_route():
    """Straight 60 m, a 90-degree right-hand bend of radius 20 m, then straight 60 m."""
    points = [(x, 0.0, 0.0) for x in range(0, 60, 2)]
    radius = 20.0
    for index in range(1, 16):
        angle = (math.pi / 2) * index / 15
        points.append((60 + radius * math.sin(angle), radius - radius * math.cos(angle), math.degrees(angle)))
    for step in range(1, 31):
        points.append((60 + radius, radius + 2.0 * step, 90.0))
    return points


def observe(route, index, x, y, yaw_deg, speed_kmh, red=0.0, obstacle=80.0):
    """Mirror simulation.observations.make_observation for a route-conditioned car."""
    lane_x, lane_y, lane_yaw = route[index]
    right = (-math.sin(math.radians(lane_yaw)), math.cos(math.radians(lane_yaw)))
    lateral = (x - lane_x) * right[0] + (y - lane_y) * right[1]
    ref_x, ref_y, _ = route[min(index + LOOKAHEAD_WAYPOINTS, len(route) - 1)]
    desired = math.degrees(math.atan2(ref_y - y, ref_x - x))
    heading = wrap_angle(yaw_deg - desired)
    curvature = wrap_angle(desired - lane_yaw) / 45.0
    return [lateral, heading, speed_kmh, TARGET_KMH, obstacle, red, curvature, 1.0 if speed_kmh < 1.0 else 0.0]


class Car:
    def __init__(self, x=0.0, y=0.0, yaw_deg=0.0):
        self.x, self.y, self.yaw, self.speed = x, y, math.radians(yaw_deg), 0.0

    def step(self, throttle, brake, steer):
        acceleration = 3.5 * throttle - 8.0 * brake - 0.25 - 0.015 * self.speed
        self.speed = max(0.0, self.speed + acceleration * DT)
        wheel = math.radians(steer * MAX_WHEEL_ANGLE_DEG)
        self.yaw += self.speed / WHEELBASE_M * math.tan(wheel) * DT
        self.x += self.speed * math.cos(self.yaw) * DT
        self.y += self.speed * math.sin(self.yaw) * DT

    @property
    def speed_kmh(self):
        return self.speed * 3.6

    @property
    def yaw_deg(self):
        return math.degrees(self.yaw)


def cockpit_controls(model, features, speed_kmh, stalled_for_s, start_assist):
    """Exactly the post-processing the neural cockpit applies to a prediction."""
    prediction = model.predict(normalize_features(features))
    accelerator = max(0.0, min(1.0, float(prediction[1])))
    brake = max(0.0, min(1.0, float(prediction[2])))
    steering = max(-1.0, min(1.0, float(prediction[0])))
    steering, _correction, assisted_target = apply_lane_assistance(features, steering)
    accelerator, brake, start_assist = apply_stall_recovery(
        features, accelerator, brake, stalled_for_s, active=start_assist,
        maximum_lane_error_m=1.6, max_accelerator=0.2 if abs(features[0]) > 1.2 else 0.35)
    if brake < 0.45:
        brake = 0.0
    accelerator, brake = limit_neural_speed(accelerator, brake, features[2], assisted_target)
    if brake > 0.05:
        accelerator = 0.0
    control = SimpleNamespace(throttle=accelerator, brake=brake, steer=steering)
    control, _ = apply_speed_sensitive_steering(control, speed_kmh)
    control, _ = apply_turn_stability(control, speed_kmh)
    control, _ = apply_scene_streaming_limit(control, speed_kmh)
    return control, start_assist


class BootstrapPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CARLA_NEURAL_VISUAL"] = "0"
        cls.model = load_deployable_policy(POLICY, require_route_conditioned=True)

    def test_artifact_is_honest_about_its_origin(self):
        metadata = json.loads(POLICY.read_text(encoding="utf-8"))["training_metadata"]
        self.assertEqual(metadata["policy_contract_version"], POLICY_CONTRACT_VERSION)
        self.assertEqual(metadata["source"], "synthetic_bootstrap_teacher")
        self.assertTrue(metadata["deployable"] and metadata["route_conditioned"])
        self.assertLess(metadata["metrics"]["steering_mae"], 0.05)

    def test_config_prefers_the_real_model_and_falls_back_to_bootstrap(self):
        candidates = json.loads((ROOT / "config" / "runtime.json").read_text(encoding="utf-8"))["legacy_policy_candidates"]
        self.assertEqual(candidates, ["nn_policy_colab.json", "nn_policy_bootstrap.json"])

    def test_steering_direction_and_stop_requests_are_sane(self):
        clear = [0.0, 0.0, 30.0, 30.0, 80.0, 0.0, 0.0, 0.0]
        steer_left = self.model.predict(normalize_features([1.5, 12.0, 30.0, 30.0, 80.0, 0.0, 0.0, 0.0]))[0]
        steer_right = self.model.predict(normalize_features([-1.5, -12.0, 30.0, 30.0, 80.0, 0.0, 0.0, 0.0]))[0]
        self.assertLess(steer_left, -0.25)      # right of the route and pointing right: turn left
        self.assertGreater(steer_right, 0.25)
        standing = self.model.predict(normalize_features([0.0, 0.0, 0.0, 30.0, 80.0, 0.0, 0.0, 1.0]))
        self.assertGreater(standing[1], 0.5)    # clear road ahead: pull away
        self.assertLess(standing[2], 0.2)
        red = self.model.predict(normalize_features(clear[:5] + [1.0, 0.0, 0.0]))
        self.assertGreater(red[2], 0.7)         # red light: brake hard
        self.assertLess(red[1], 0.1)
        blocked = self.model.predict(normalize_features([0.0, 0.0, 30.0, 30.0, 5.0, 0.0, 0.0, 0.0]))
        self.assertGreater(blocked[2], 0.7)     # car 5 m ahead: brake hard

    def test_follows_a_route_with_a_right_angle_turn(self):
        route = build_route()
        car = Car()
        index, stalled_since, start_assist = 0, None, False
        peak_speed, worst_lane, time_s = 0.0, 0.0, 0.0
        for _ in range(int(60 / DT)):
            # advance_route_index: nearest upcoming waypoint, never backwards
            index = min(range(index, min(len(route), index + 20)),
                        key=lambda i: math.hypot(route[i][0] - car.x, route[i][1] - car.y))
            if index >= len(route) - 2:
                break
            features = observe(route, index, car.x, car.y, car.yaw_deg, car.speed_kmh)
            stalled_since = (time_s if stalled_since is None else stalled_since) if is_stall_candidate(
                features[2], 0.0, 0.0) else (None if not start_assist else stalled_since)
            control, start_assist = cockpit_controls(
                self.model, features, car.speed_kmh,
                0.0 if stalled_since is None else time_s - stalled_since, start_assist)
            car.step(control.throttle, control.brake, control.steer)
            time_s += DT
            peak_speed = max(peak_speed, car.speed_kmh)
            worst_lane = max(worst_lane, abs(features[0]))
        self.assertGreaterEqual(index, len(route) - 2, f"stopped at waypoint {index} after {time_s:.1f} s")
        self.assertGreater(peak_speed, 20.0)
        self.assertLess(worst_lane, 1.5, "left the lane far enough for the safety supervisor to brake")
        self.assertLess(time_s, 45.0)

    def test_stops_for_a_red_light_and_a_car_ahead(self):
        for state in ([0.0, 0.0, 28.0, 30.0, 80.0, 1.0, 0.0, 0.0], [0.0, 0.0, 28.0, 30.0, 5.0, 0.0, 0.0, 0.0]):
            with self.subTest(state=state):
                control, _ = cockpit_controls(self.model, state, state[2], 0.0, False)
                self.assertEqual(control.throttle, 0.0)
                self.assertGreater(control.brake, 0.5)


if __name__ == "__main__":
    unittest.main()
