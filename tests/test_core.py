"""Fast regression tests for logic that does not require a running CARLA server."""
import importlib.util
import json
import math
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

from telemetry.recorder import EpisodeRecorder
from collect_expert_data import choose_route
from telemetry.dashboard import summarize, write_dashboard
from learning.model import (MLP, load_deployable_policy)
from learning.assistance import (apply_stall_recovery)
from simulation.observations import (make_observation)
from vehicle.safety import SafetySupervisor
from vehicle.control import VehicleCommand, steering_angle_from_lane_error
from runtime.watchdog import CommandWatchdog
from runtime.paths import carla_root
from simulation.features import _choose_continuation
from learning.contract import POLICY_CONTRACT_VERSION, normalize_features
from simulation.routes import _load_agents
from vehicle.transmission import (EngineRpmEstimator, ManualTransmissionConfig,
                                 automatic_gear_for_speed, estimate_engine_rpm,
                                 gear_redline_speed_kmh,
                                 recommended_shift)
from runtime.gesture import GESTURE_BIAS_CAP, policy_bias_from_payload
from runtime.health import HealthEvent, evaluate_health
from stack_supervisor import (Component, RestartPolicy, Supervisor,
                              build_components, carla_rpc_probe, parse_args as supervisor_args)


CARLA_ROOT = carla_root()


def load_spawn_module():
    from cockpit import session
    return session


class FakeWorld:
    def __init__(self, results):
        self.results = iter(results)
        self.attempts = 0

    def try_spawn_actor(self, _blueprint, _point):
        self.attempts += 1
        return next(self.results)


class FakeLocation:
    def __init__(self, x):
        self.x = x

    def distance(self, other):
        return abs(self.x - other.x)


class FakeTransform:
    def __init__(self, x):
        self.location = FakeLocation(x)


class FakeRotation:
    def __init__(self, yaw):
        self.yaw = yaw


class FakeRouteTransform:
    def __init__(self, yaw):
        self.rotation = FakeRotation(yaw)


class FakeWaypoint:
    def __init__(self, yaw):
        self.transform = FakeRouteTransform(yaw)


class FakeVector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z

    def __sub__(self, other):
        return FakeVector(self.x - other.x, self.y - other.y, self.z - other.z)


class FakeDrivingTransform:
    def __init__(self):
        self.location = FakeVector()
        self.rotation = FakeRotation(0.0)

    def get_right_vector(self):
        return FakeVector(y=1.0)

    def get_forward_vector(self):
        return FakeVector(x=1.0)


class FakeDrivingWaypoint:
    def __init__(self):
        self.transform = FakeDrivingTransform()

    def next(self, _distance):
        return []


class FakeDrivingMap:
    def get_waypoint(self, _location, project_to_road=True):
        return FakeDrivingWaypoint()


class FakeDrivingWorld:
    def get_map(self):
        return FakeDrivingMap()


class FakeDrivingVehicle:
    id = 1

    def get_transform(self):
        return FakeDrivingTransform()

    def get_velocity(self):
        return FakeVector()

    def get_traffic_light_state(self):
        return "green"


class FakePygame:
    K_w = 1
    K_UP = 2
    K_s = 3
    K_DOWN = 4
    K_a = 5
    K_LEFT = 6
    K_d = 7
    K_RIGHT = 8
    K_LSHIFT = 9
    K_LCTRL = 10
    K_SPACE = 11


class FakeKeys:
    def __init__(self, pressed=()):
        self.pressed = set(pressed)

    def __getitem__(self, key):
        return key in self.pressed


class CoreLogicTests(unittest.TestCase):
    def test_gesture_policy_bias_is_bounded_and_directional(self):
        bias = policy_bias_from_payload({
            "tracking": True,
            "bias": {
                "turn_left": 9.0,
                "lane_change_left": 9.0,
                "slow_down": 9.0,
            },
        })
        self.assertEqual(bias.steering, -GESTURE_BIAS_CAP)
        self.assertEqual(bias.accelerator, -GESTURE_BIAS_CAP)
        self.assertLessEqual(bias.brake, GESTURE_BIAS_CAP)
        self.assertTrue(bias.active)

    def test_opposing_gestures_cancel_and_invalid_values_are_ignored(self):
        bias = policy_bias_from_payload({
            "tracking": True,
            "bias": {
                "turn_left": 0.1,
                "turn_right": 0.1,
                "stop": float("nan"),
            },
        })
        self.assertEqual(bias.steering, 0.0)
        self.assertEqual(bias.brake, 0.0)
        self.assertFalse(bias.active)

    def test_spawn_tries_past_occupied_points(self):
        world = FakeWorld([None, None, "vehicle"])
        result = load_spawn_module().try_spawn_vehicle(world, object(), [1, 2, 3])
        self.assertEqual(result, "vehicle")
        self.assertEqual(world.attempts, 3)

    def test_small_heading_angle_stays_in_degrees(self):
        self.assertAlmostEqual(steering_angle_from_lane_error(0.0, 0.5), 0.5)

    def test_manual_gear_is_sent_to_carla(self):
        for gear in (-1, 0, 1, 6):
            control = VehicleCommand(accelerator=0.4, gear=gear).to_carla()
            self.assertTrue(control.manual_gear_shift)
            self.assertEqual(control.gear, 1 if gear == 0 else gear)
            self.assertEqual(control.reverse, gear == -1)
            if gear == 0:
                self.assertEqual(control.throttle, 0.0)

    def test_cockpit_blocks_acceleration_in_neutral_and_park(self):
        spawn = load_spawn_module()
        keys = FakeKeys([FakePygame.K_w])
        neutral, _ = spawn.build_vehicle_control(keys, FakePygame, 0.0, selected_gear=0)
        parked, _ = spawn.build_vehicle_control(keys, FakePygame, 0.0, selected_gear=0, parked=True)
        reverse, _ = spawn.build_vehicle_control(keys, FakePygame, 0.0, selected_gear=-1)
        self.assertEqual(neutral.throttle, 0.0)
        self.assertEqual(parked.throttle, 0.0)
        self.assertTrue(parked.hand_brake)
        self.assertGreater(reverse.throttle, 0.0)
        self.assertTrue(reverse.reverse)

    def test_cockpit_key_release_has_low_latency(self):
        spawn = load_spawn_module()
        keys = spawn.HeldKeyState(tap_latch_seconds=0.0)
        keys.press(FakePygame.K_w)
        self.assertTrue(keys[FakePygame.K_w])
        keys.release(FakePygame.K_w)
        self.assertFalse(keys[FakePygame.K_w])

    def test_shift_requires_clutch_while_moving(self):
        spawn = load_spawn_module()
        self.assertTrue(spawn.can_change_gear(0.5, 0.0))
        self.assertFalse(spawn.can_change_gear(20.0, 0.0))
        self.assertTrue(spawn.can_change_gear(20.0, 1.0))

    def test_graphics_throttle_neck_is_progressive(self):
        spawn = load_spawn_module()

        class Control:
            throttle = 0.65

        below, active = spawn.apply_graphics_throttle_neck(Control(), 40.0, 45.0, 60.0)
        self.assertFalse(active)
        self.assertAlmostEqual(below.throttle, 0.65)

        middle, active = spawn.apply_graphics_throttle_neck(Control(), 52.5, 45.0, 60.0)
        self.assertTrue(active)
        self.assertAlmostEqual(middle.throttle, 0.325)

        capped, active = spawn.apply_graphics_throttle_neck(Control(), 60.0, 45.0, 60.0)
        self.assertTrue(active)
        self.assertEqual(capped.throttle, 0.0)

    def test_turn_stability_reduces_throttle_but_preserves_steering(self):
        spawn = load_spawn_module()

        class Control:
            throttle = 0.65
            steer = 0.72

        control = Control()
        stable, active = spawn.apply_turn_stability(control, 25.0)
        self.assertTrue(active)
        self.assertAlmostEqual(stable.steer, 0.72)
        self.assertLess(stable.throttle, 0.65)
        self.assertGreater(stable.throttle, 0.0)

    def test_scene_streaming_limit_brakes_above_gpu_cliff(self):
        spawn = load_spawn_module()

        class Control:
            throttle = 0.65
            brake = 0.0

        below, active = spawn.apply_scene_streaming_limit(Control(), 35.0)
        self.assertFalse(active)
        self.assertAlmostEqual(below.throttle, 0.65)

        above, active = spawn.apply_scene_streaming_limit(Control(), 50.0)
        self.assertTrue(active)
        self.assertEqual(above.throttle, 0.0)
        self.assertGreater(above.brake, 0.0)

    def test_speed_sensitive_steering_restricts_high_speed_turns(self):
        spawn = load_spawn_module()

        class Control:
            steer = 0.72

        slow, active = spawn.apply_speed_sensitive_steering(Control(), 15.0)
        self.assertFalse(active)
        self.assertAlmostEqual(slow.steer, 0.72)

        fast, active = spawn.apply_speed_sensitive_steering(Control(), 48.0)
        self.assertTrue(active)
        self.assertAlmostEqual(fast.steer, 0.22)

    def test_speedometer_has_no_leading_zeroes(self):
        spawn = load_spawn_module()
        self.assertEqual(spawn.format_speed_kmh(0), "0")
        self.assertEqual(spawn.format_speed_kmh(7.2), "7")
        self.assertEqual(spawn.format_speed_kmh(42.4), "42")
        self.assertEqual(spawn.format_speed_kmh(160), "160")

    def test_high_speed_visual_austerity_uses_hysteresis(self):
        spawn = load_spawn_module()
        self.assertFalse(spawn.visual_austerity_transition(False, 44.9, 45.0, 38.0))
        self.assertTrue(spawn.visual_austerity_transition(False, 45.0, 45.0, 38.0))
        self.assertTrue(spawn.visual_austerity_transition(True, 40.0, 45.0, 38.0))
        self.assertFalse(spawn.visual_austerity_transition(True, 38.0, 45.0, 38.0))

    def test_reduced_motion_weather_removes_animated_effects(self):
        spawn = load_spawn_module()
        original = spawn.carla.WeatherParameters(
            cloudiness=80.0, precipitation=70.0, wind_intensity=60.0,
            sun_altitude_angle=35.0, wetness=90.0, dust_storm=40.0,
        )
        reduced = spawn.reduced_motion_weather(original)
        self.assertEqual(reduced.cloudiness, 0.0)
        self.assertEqual(reduced.precipitation, 0.0)
        self.assertEqual(reduced.wind_intensity, 0.0)
        self.assertEqual(reduced.fog_density, 0.0)
        self.assertEqual(reduced.dust_storm, 0.0)
        self.assertEqual(reduced.sun_altitude_angle, original.sun_altitude_angle)
        self.assertEqual(reduced.wetness, original.wetness)

    def test_rpm_behaves_like_a_manual_powertrain(self):
        launch_rpm = estimate_engine_rpm(0.0, 1, accelerator=1.0)
        first_gear_rpm = estimate_engine_rpm(10.0, 1)
        third_gear_rpm = estimate_engine_rpm(10.0, 3)
        neutral_rpm = estimate_engine_rpm(0.0, 0, accelerator=1.0)
        self.assertGreater(launch_rpm, 2000.0)
        self.assertGreater(first_gear_rpm, third_gear_rpm)
        self.assertGreater(neutral_rpm, launch_rpm)
        estimator = EngineRpmEstimator()
        first = estimator.update(0.0, 1, accelerator=1.0, dt=0.1)
        second = estimator.update(0.0, 1, accelerator=1.0, dt=0.1)
        self.assertGreater(second, first)
        self.assertLess(second, launch_rpm + 1.0)
        self.assertEqual(recommended_shift(2, 6000, 0.8), "SHIFT NOW")

    def test_six_speed_ratios_use_every_gear_before_top_speed(self):
        config = ManualTransmissionConfig()
        speeds = [gear_redline_speed_kmh(gear, config) for gear in range(1, 7)]
        self.assertEqual(len(config.gear_ratios) - 2, 6)
        self.assertTrue(all(a < b for a, b in zip(speeds, speeds[1:])))
        expected_redline_speeds = [12.0, 20.0, 28.0, 36.0, 42.0, 48.0]
        for actual, expected in zip(speeds, expected_redline_speeds):
            self.assertAlmostEqual(actual, expected, delta=0.05)
        expected_limits = [12.0, 20.0, 28.0, 36.0, 42.0]
        self.assertEqual(
            [config.gear_speed_ranges_kmh[gear][1] for gear in range(1, 6)],
            expected_limits,
        )

    def test_long_map_segment_crossing_vehicle_is_visible(self):
        spawn = load_spawn_module()
        self.assertTrue(spawn.segment_intersects_local_radius((-200, 0), (200, 0), 70))
        self.assertFalse(spawn.segment_intersects_local_radius((100, 100), (200, 200), 70))

    def test_interactive_map_coordinates_round_trip(self):
        spawn = load_spawn_module()
        segments = [((-100.0, -50.0), (300.0, 150.0))]
        bounds = spawn.map_bounds_from_segments(segments)
        pixel = spawn.world_to_map_pixel((75.0, 25.0), bounds, (1280, 720))
        world = spawn.map_pixel_to_world(pixel, bounds, (1280, 720))
        self.assertAlmostEqual(world[0], 75.0)
        self.assertAlmostEqual(world[1], 25.0)

    def test_route_driver_uses_all_six_gears(self):
        spawn = load_spawn_module()
        self.assertEqual(spawn.automatic_route_gear(0.0), 1)
        self.assertEqual(spawn.automatic_route_gear(11.9), 1)
        self.assertEqual(spawn.automatic_route_gear(12.0), 2)
        self.assertEqual(spawn.automatic_route_gear(20.0), 3)
        self.assertEqual(spawn.automatic_route_gear(28.0), 4)
        self.assertEqual(spawn.automatic_route_gear(36.0), 5)
        self.assertEqual(spawn.automatic_route_gear(42.0), 6)
        self.assertEqual(spawn.automatic_route_gear(48.0), 6)

    def test_carla_neutral_representation_is_not_reported_as_mismatch(self):
        spawn = load_spawn_module()
        self.assertTrue(spawn.gearbox_state_matches(0, 1))
        self.assertTrue(spawn.gearbox_state_matches(-1, -1))
        self.assertFalse(spawn.gearbox_state_matches(2, 1))

    def test_supervisor_fails_safe_on_non_finite_command(self):
        command, reasons = SafetySupervisor().apply(
            VehicleCommand(accelerator=math.nan), {"speed_kmh": 10.0}
        )
        self.assertEqual(reasons, ["invalid_telemetry_or_command"])
        self.assertEqual(command.brake, 1.0)
        self.assertTrue(command.hand_brake)

    def test_supervisor_brakes_on_real_command_age(self):
        command, reasons = SafetySupervisor().apply(
            VehicleCommand(accelerator=0.5), {"speed_kmh": 10.0, "command_age_s": 1.0, "lane_error_m": 0.0, "obstacle_distance_m": 80.0, "red_light": False, "collision": False}
        )
        self.assertIn("stale_command", reasons)
        self.assertEqual(command.accelerator, 0.0)
        self.assertEqual(command.brake, 1.0)

    def test_observation_uses_configured_target_speed(self):
        vehicle = FakeDrivingVehicle()
        observation = make_observation(
            vehicle, FakeDrivingWorld(), "red", [vehicle], target_speed_kmh=27.0,
        )
        self.assertEqual(observation[3], 27.0)

    def test_route_conditioned_observation_points_toward_route_waypoint(self):
        vehicle = FakeDrivingVehicle()
        reference = FakeDrivingWaypoint()
        reference.transform.location = FakeVector(y=10.0)
        observation = make_observation(
            vehicle, FakeDrivingWorld(), "red", [vehicle],
            target_speed_kmh=45.0, reference_waypoint=reference,
        )
        self.assertAlmostEqual(observation[1], -90.0)
        self.assertAlmostEqual(observation[6], 2.0)

    def test_map_route_loader_requires_route_conditioned_policy(self):
        spawn = load_spawn_module()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-route-conditioned.json"
            model = MLP([8, 24, 16, 3])
            path.write_text(json.dumps({
                "sizes": model.sizes,
                "weights": model.weights,
                "biases": model.biases,
                "training_metadata": {
                    "policy_contract_version": POLICY_CONTRACT_VERSION,
                    "deployable": True,
                    "route_conditioned": False,
                },
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "route-conditioned"):
                spawn.load_deployable_route_policy(path)

    def test_destination_selection_reuses_preloaded_road_graph(self):
        spawn = load_spawn_module()
        planner = Mock()
        planner.trace_route.return_value = ['prepared route']
        with patch('cockpit.navigation.make_neural_route_planner') as rebuild:
            result = spawn.plan_neural_route(Mock(), 'start', 'destination', planner=planner)
        self.assertEqual(result, ['prepared route'])
        planner.trace_route.assert_called_once_with('start', 'destination')
        rebuild.assert_not_called()

    def test_stall_recovery_waits_then_adds_bounded_accelerator(self):
        clear_standstill = [0.1, 1.0, 0.0, 35.0, 80.0, 0.0, 0.0, 1.0]
        accelerator, brake, active = apply_stall_recovery(
            clear_standstill, 0.0, 0.02, stalled_for_s=1.0,
        )
        self.assertEqual(accelerator, 0.0)
        self.assertEqual(brake, 0.02)
        self.assertFalse(active)
        accelerator, brake, active = apply_stall_recovery(
            clear_standstill, 0.0, 0.02, stalled_for_s=2.1,
        )
        self.assertTrue(active)
        self.assertGreaterEqual(accelerator, 0.12)
        self.assertLessEqual(accelerator, 0.35)
        self.assertEqual(brake, 0.0)

    def test_stall_recovery_never_overrides_a_hazard_or_stop_request(self):
        cases = [
            [0.1, 1.0, 0.0, 35.0, 6.0, 0.0, 0.0, 1.0],
            [0.1, 1.0, 0.0, 35.0, 80.0, 1.0, 0.0, 1.0],
            [1.5, 1.0, 0.0, 35.0, 80.0, 0.0, 0.0, 1.0],
            [0.1, 20.0, 0.0, 35.0, 80.0, 0.0, 0.0, 1.0],
        ]
        for features in cases:
            with self.subTest(features=features):
                accelerator, brake, active = apply_stall_recovery(
                    features, 0.0, 0.0, stalled_for_s=10.0, active=True,
                )
                self.assertEqual(accelerator, 0.0)
                self.assertFalse(active)
        accelerator, brake, active = apply_stall_recovery(
            [0.0, 0.0, 10.0, 35.0, 80.0, 0.0, 0.0, 0.0],
            0.0, 0.6, stalled_for_s=10.0, active=True,
        )
        self.assertEqual(accelerator, 0.0)
        self.assertEqual(brake, 0.6)
        self.assertFalse(active)

    def test_stall_recovery_releases_stuck_brake_only_after_longer_delay(self):
        clear_standstill = [0.0, 0.0, 0.0, 35.0, 80.0, 0.0, 0.0, 1.0]
        accelerator, brake, active = apply_stall_recovery(
            clear_standstill, 0.0, 0.96, stalled_for_s=4.9,
        )
        self.assertEqual((accelerator, brake, active), (0.0, 0.96, False))
        accelerator, brake, active = apply_stall_recovery(
            clear_standstill, 0.0, 0.96, stalled_for_s=5.1,
        )
        self.assertTrue(active)
        self.assertGreater(accelerator, 0.0)
        self.assertEqual(brake, 0.0)

    def test_stall_recovery_releases_at_cruising_speed(self):
        features = [0.0, 0.0, 30.0, 35.0, 80.0, 0.0, 0.0, 0.0]
        accelerator, brake, active = apply_stall_recovery(
            features, 0.0, 0.0, stalled_for_s=10.0, active=True,
        )
        self.assertEqual(accelerator, 0.0)
        self.assertFalse(active)

    def test_policy_rejects_wrong_layer_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"sizes": [2, 1], "weights": [[[1.0]]], "biases": [[0.0]]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                MLP.load(path)

    def test_policy_rejects_wrong_input_length(self):
        with self.assertRaisesRegex(ValueError, "Expected 8 policy inputs"):
            MLP([8, 24, 16, 3]).predict([0.0] * 7)

    def test_policy_rejects_contract_version_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-contract.json"
            model = MLP([8, 24, 16, 3])
            payload = {"sizes": model.sizes, "weights": model.weights,
                       "biases": model.biases,
                       "training_metadata": {
                           "policy_contract_version": POLICY_CONTRACT_VERSION + 1}}
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Policy contract mismatch"):
                MLP.load(path)

    def test_policy_rejects_missing_contract_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            model = MLP([8, 24, 16, 3])
            path.write_text(json.dumps({
                "sizes": model.sizes,
                "weights": model.weights,
                "biases": model.biases,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Policy contract mismatch"):
                MLP.load(path)

    def test_runtime_rejects_non_deployable_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smoke.json"
            model = MLP([8, 24, 16, 3])
            path.write_text(json.dumps({
                "sizes": model.sizes,
                "weights": model.weights,
                "biases": model.biases,
                "training_metadata": {
                    "policy_contract_version": POLICY_CONTRACT_VERSION,
                    "deployable": False,
                },
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not marked deployable"):
                load_deployable_policy(path)

    def test_shared_automatic_gear_uses_requested_bands(self):
        expected = {0.0: 1, 11.9: 1, 12.0: 2, 20.0: 3,
                    28.0: 4, 36.0: 5, 42.0: 6, 48.0: 6}
        for speed, gear in expected.items():
            self.assertEqual(automatic_gear_for_speed(speed), gear)

    def test_shared_normalization_contract_validates_shape(self):
        self.assertEqual(len(normalize_features([0, 0, 0, 35, 80, 0, 0, 1])), 8)
        with self.assertRaises(ValueError):
            normalize_features([0] * 7)

    def test_independent_command_watchdog_triggers_and_rearms(self):
        triggered = threading.Event()
        watchdog = CommandWatchdog(timeout_s=0.05, poll_interval_s=0.01)
        watchdog.start(triggered.set)
        try:
            watchdog.command_received()
            self.assertTrue(triggered.wait(0.5))
            self.assertTrue(watchdog.status()["triggered"])
            triggered.clear()
            watchdog.command_received()
            self.assertTrue(watchdog.status()["healthy"])
            self.assertTrue(triggered.wait(0.5))
        finally:
            watchdog.stop()

    def test_route_continuation_uses_previous_waypoint_heading(self):
        cursor = FakeWaypoint(90)
        straight_from_cursor = FakeWaypoint(100)
        closer_to_original_ego = FakeWaypoint(10)
        selected = _choose_continuation(cursor, [closer_to_original_ego, straight_from_cursor])
        self.assertIs(selected, straight_from_cursor)

    def test_route_planner_loads_bundled_agents_path(self):
        _load_agents()
        expected = str(CARLA_ROOT / "PythonAPI" / "carla")
        self.assertIn(expected, __import__("sys").path)
        from agents.navigation.global_route_planner import GlobalRoutePlanner
        self.assertIsNotNone(GlobalRoutePlanner)

    def test_recorder_does_not_overwrite_same_named_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            first = EpisodeRecorder(directory, "run")
            first.close()
            second = EpisodeRecorder(directory, "run")
            second.close()
            self.assertNotEqual(first.path, second.path)

    def test_recorder_preserves_training_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = EpisodeRecorder(directory, "training")
            recorder.record([0.0] * 8, {"steering": 0.1}, metadata={"route_id": "route-1"})
            path = recorder.path
            recorder.close()
            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["metadata"]["route_id"], "route-1")

    def test_expert_route_respects_minimum_distance(self):
        start, destination = choose_route(
            [FakeTransform(0), FakeTransform(10), FakeTransform(200)],
            __import__("random").Random(7),
            150,
        )
        self.assertGreaterEqual(start.location.distance(destination.location), 150)

    def test_dashboard_uses_recorded_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            episode = Path(directory) / "episode.jsonl"
            rows = [
                {"telemetry": {"speed_kmh": 10, "distance_m": 2, "elapsed_s": 1,
                               "obstacle_distance_m": 20, "collision": False,
                               "lane_departure": False}},
                {"telemetry": {"speed_kmh": 20, "distance_m": 5, "elapsed_s": 2,
                               "obstacle_distance_m": 8, "collision": False,
                               "lane_departure": True}, "event": ["lane_departure"]},
            ]
            episode.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            result = summarize(episode)
            self.assertEqual(result["distance_m"], 5)
            self.assertEqual(result["average_speed_kmh"], 15)
            self.assertEqual(result["lane_departures"], 1)
            self.assertFalse(result["success"])
            output = Path(directory) / "dashboard.html"
            write_dashboard([episode], output)
            page = output.read_text(encoding="utf-8")
            self.assertIn("Driving evaluation", page)
            self.assertIn("REVIEW", page)


class SupervisorCommandLineTests(unittest.TestCase):
    """The launcher passes these through, so a broken flag breaks every launch."""

    def _carla_argv(self, argv):
        components = {item.name: item for item in build_components(supervisor_args(argv))}
        return [str(part) for part in components["carla"].argv]

    def test_default_renderer_matches_validated_map_launcher(self):
        self.assertIn("-dx11", self._carla_argv([]))

    def test_opengl_is_selectable(self):
        # Regression: --render-api once took "-opengl" as its value, and argparse
        # reads a dash-prefixed value as the next option, so "--opengl" from the
        # launcher aborted the supervisor before it started anything.
        argv = self._carla_argv(["--render-api", "opengl"])
        self.assertIn("-opengl", argv)
        self.assertNotIn("-dx12", argv)

    def test_every_renderer_choice_parses(self):
        for name in ("dx12", "dx11", "opengl", "vulkan"):
            with self.subTest(renderer=name):
                self.assertIn("-" + name, self._carla_argv(["--render-api", name]))

    def test_launcher_flags_are_accepted_together(self):
        args = supervisor_args(["--no-thermal-guard", "--render-api", "opengl",
                                "--no-orphan-sweep", "--max-log-mb", "10"])
        self.assertTrue(args.no_thermal_guard)
        self.assertTrue(args.no_orphan_sweep)
        self.assertEqual(args.max_log_mb, 10.0)

    def test_the_neural_driver_depends_only_on_carla(self):
        components = {item.name: item for item in build_components(supervisor_args([]))}
        self.assertEqual(set(components["neural"].depends_on), {"carla"})


class CarlaLivenessTests(unittest.TestCase):
    def test_open_listener_with_dead_rpc_is_not_ready(self):
        with patch('carla.Client') as client:
            client.return_value.get_server_version.side_effect = RuntimeError('timeout')
            self.assertFalse(carla_rpc_probe('127.0.0.1', 2000))

    def test_world_that_stops_ticking_is_not_ready(self):
        with patch('carla.Client') as client:
            world = client.return_value.get_world.return_value
            world.get_settings.return_value.synchronous_mode = False
            world.wait_for_tick.side_effect = RuntimeError('timeout')
            self.assertFalse(carla_rpc_probe('127.0.0.1', 2000))

    def test_advancing_world_is_ready(self):
        with patch('carla.Client') as client:
            world = client.return_value.get_world.return_value
            world.get_settings.return_value.synchronous_mode = False
            self.assertTrue(carla_rpc_probe('127.0.0.1', 2000))
            world.wait_for_tick.assert_called_once_with(seconds=3.0)


class HealthGuardTests(unittest.TestCase):
    """The thermal cooldown that keeps a relaunch from re-triggering a crash."""

    def test_no_events_is_safe(self):
        verdict = evaluate_health([])
        self.assertTrue(verdict.safe)
        self.assertEqual(verdict.cooldown_remaining_s, 0.0)

    def test_recent_thermal_fault_blocks_launch(self):
        verdict = evaluate_health([HealthEvent("thermal", age_s=120.0)])
        self.assertFalse(verdict.safe)
        self.assertAlmostEqual(verdict.cooldown_remaining_s, 1800.0 - 120.0)
        self.assertIn("thermal", verdict.reason)

    def test_old_thermal_fault_no_longer_blocks(self):
        self.assertTrue(evaluate_health([HealthEvent("thermal", age_s=4000.0)]).safe)

    def test_hardware_fault_has_the_longer_cooldown(self):
        self.assertFalse(evaluate_health([HealthEvent("hardware", age_s=2000.0)]).safe)
        self.assertTrue(evaluate_health([HealthEvent("thermal", age_s=2000.0)]).safe)

    def test_application_hang_alone_does_not_block(self):
        # A hung process is the supervisor to restart, not a reason to keep the
        # whole stack down.
        self.assertTrue(evaluate_health([HealthEvent("hang", age_s=10.0)]).safe)

    def test_the_longest_remaining_cooldown_wins(self):
        verdict = evaluate_health([HealthEvent("thermal", age_s=1700.0),
                                   HealthEvent("hardware", age_s=100.0)])
        self.assertFalse(verdict.safe)
        self.assertAlmostEqual(verdict.cooldown_remaining_s, 3500.0)
        self.assertIn("hardware", verdict.reason)

    def test_cooldowns_are_configurable(self):
        verdict = evaluate_health([HealthEvent("thermal", age_s=120.0)],
                                  cooldowns={"thermal": 60.0})
        self.assertTrue(verdict.safe)


class RestartPolicyTests(unittest.TestCase):
    def test_first_start_is_immediate(self):
        policy = RestartPolicy()
        policy.record_start()
        self.assertEqual(policy.delay_s(), 0.0)

    def test_backoff_grows_then_caps(self):
        policy = RestartPolicy(base_delay_s=5.0, max_delay_s=40.0)
        delays = []
        for _ in range(8):
            policy.record_start()
            delays.append(policy.delay_s())
        self.assertEqual(delays[:5], [0.0, 5.0, 10.0, 20.0, 40.0])
        self.assertTrue(all(delay == 40.0 for delay in delays[4:]))

    def test_a_long_healthy_run_clears_the_failure_count(self):
        policy = RestartPolicy(healthy_after_s=300.0)
        for _ in range(4):
            policy.record_start()
        policy.record_exit(uptime_s=600.0)
        self.assertEqual(policy.failures, 0)

    def test_a_short_run_keeps_counting_toward_giving_up(self):
        policy = RestartPolicy(max_failures=3, healthy_after_s=300.0)
        for _ in range(4):
            policy.record_start()
            policy.record_exit(uptime_s=1.0)
        self.assertTrue(policy.exhausted())


class FakeProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class RecordingSupervisor(Supervisor):
    """Supervisor with process spawning replaced, so tick() logic can be tested."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.starts = []

    def log(self, message):
        pass

    def start(self, component):
        self.starts.append(component.name)
        component.process = FakeProcess()
        component.started_at = time.monotonic()
        component.probe_failures = 0
        component.policy.record_start()


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        # stop() tree-kills via taskkill. A unit test must never shell out to a
        # real process killer, so record the pids instead.
        import stack_supervisor

        self.killed = []
        real = stack_supervisor.terminate_tree
        stack_supervisor.terminate_tree = lambda pid, timeout_s=10.0: (
            self.killed.append(pid) or True)
        self.addCleanup(lambda: setattr(stack_supervisor, "terminate_tree", real))

    def _component(self, name, **kwargs):
        return Component(name=name, argv=["noop"], cwd=Path("."),
                         log_path=Path(tempfile.gettempdir()) / (name + ".log"), **kwargs)

    def _supervisor(self, components, thermal_guard=False):
        return RecordingSupervisor(components, log_dir=Path(tempfile.gettempdir()),
                                   thermal_guard=thermal_guard)

    def test_a_component_that_was_never_started_is_started(self):
        supervisor = self._supervisor([self._component("gesture")])
        supervisor.tick()
        self.assertEqual(supervisor.starts, ["gesture"])

    def test_a_dead_component_is_restarted(self):
        component = self._component("gesture")
        supervisor = self._supervisor([component])
        supervisor.tick()
        component.process.returncode = 18  # EXIT_CAMERA_STALLED
        component.policy.base_delay_s = 0.0
        supervisor.tick()
        self.assertEqual(supervisor.starts, ["gesture", "gesture"])

    def test_an_unresponsive_but_live_component_is_recycled(self):
        # The 2026-09-09 shape: the process is alive and still holding its port,
        # but has stopped answering. A PID check alone would call this healthy.
        component = self._component("gesture", probe=lambda: False, ready_grace_s=0.0,
                                    probe_failures_allowed=1)
        component.policy.base_delay_s = 0.0
        supervisor = self._supervisor([component])
        supervisor.tick()
        first = component.process
        supervisor.tick()   # probe failure 1 - tolerated
        self.assertIs(component.process, first)
        supervisor.tick()   # probe failure 2 - over the allowance, recycled
        self.assertIsNone(component.process)
        supervisor.tick()   # restarted
        self.assertEqual(supervisor.starts, ["gesture", "gesture"])
        # The whole tree must be killed: terminate() alone would only reach the
        # venv redirector stub and orphan the interpreter doing the work.
        self.assertIn(first.pid, self.killed)

    def test_a_recovering_probe_clears_the_failure_count(self):
        answers = [False, True]
        component = self._component("gesture", probe=lambda: answers.pop(0),
                                    ready_grace_s=0.0, probe_failures_allowed=1)
        supervisor = self._supervisor([component])
        supervisor.tick()
        supervisor.tick()
        self.assertEqual(component.probe_failures, 1)
        supervisor.tick()
        self.assertEqual(component.probe_failures, 0)

    def test_an_unready_dependency_holds_a_component_back(self):
        carla = self._component("carla", probe=lambda: False, ready_grace_s=0.0,
                                probe_failures_allowed=0)
        neural = self._component("neural", depends_on=("carla",))
        supervisor = self._supervisor([neural, carla])
        supervisor.tick()
        carla.probe_failures = 5   # carla is not ready
        supervisor.starts.clear()
        neural.process = None
        supervisor.tick()
        self.assertNotIn("neural", supervisor.starts)

    def test_a_component_that_keeps_dying_is_given_up_on(self):
        component = self._component("gesture")
        component.policy = RestartPolicy(base_delay_s=0.0, max_failures=2, healthy_after_s=999.0)
        supervisor = self._supervisor([component])
        for _ in range(6):
            supervisor.tick()
            if component.process is not None:
                component.process.returncode = 1
        self.assertTrue(component.gave_up)
        self.assertLessEqual(len(supervisor.starts), 3)

    def test_the_grace_window_does_not_fake_readiness(self):
        # The bug this replaces: readiness was inferred from "still inside the
        # grace window", so the launcher announced READY and the neural driver
        # started while CARLA was minutes away from accepting connections.
        component = self._component("carla", probe=lambda: False, ready_grace_s=999.0)
        supervisor = self._supervisor([component])
        supervisor.tick()
        self.assertTrue(component.is_running())
        self.assertFalse(component.is_ready())

    def test_readiness_arrives_only_when_the_probe_succeeds(self):
        answers = [False, False, True]
        component = self._component("carla", probe=lambda: answers.pop(0), ready_grace_s=999.0)
        supervisor = self._supervisor([component])
        supervisor.tick()                      # starts it; no probe on the start tick
        self.assertFalse(component.is_ready())
        supervisor.tick()                      # probe -> False
        self.assertFalse(component.is_ready())
        supervisor.tick()                      # probe -> False
        self.assertFalse(component.is_ready())
        supervisor.tick()                      # probe -> True
        self.assertTrue(component.is_ready())

    def test_a_dependent_component_waits_for_a_real_probe_success(self):
        carla_up = [False, False, True, True, True, True]
        carla = self._component("carla", probe=lambda: carla_up.pop(0), ready_grace_s=999.0)
        neural = self._component("neural", depends_on=("carla",))
        supervisor = self._supervisor([neural, carla])
        supervisor.tick()                      # carla starts; neural held back
        self.assertEqual(supervisor.starts, ["carla"])
        supervisor.tick()                      # carla probe -> False
        supervisor.tick()                      # carla probe -> False
        self.assertEqual(supervisor.starts, ["carla"])
        supervisor.tick()                      # carla probe -> True, now ready
        self.assertTrue(carla.is_ready())
        supervisor.tick()                      # neural is finally allowed to start
        self.assertIn("neural", supervisor.starts)

    def test_a_probe_failure_inside_the_grace_window_is_not_counted(self):
        component = self._component("carla", probe=lambda: False, ready_grace_s=999.0,
                                    probe_failures_allowed=0)
        supervisor = self._supervisor([component])
        supervisor.tick()
        first = component.process
        for _ in range(5):
            supervisor.tick()
        self.assertEqual(component.probe_failures, 0)
        self.assertIs(component.process, first)

    def test_an_oversized_log_is_rotated_on_start(self):
        # The neural driver writes a telemetry line about twice a second, so an
        # unrotated log would eventually fill the disk and take the stack down
        # for a new reason.
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "neural.log"
            log_path.write_text("x" * 2048, encoding="utf-8")
            component = self._component("neural")
            component.log_path = log_path
            supervisor = self._supervisor([component])
            supervisor.max_log_bytes = 1024
            supervisor.rotate_log(log_path)
            self.assertFalse(log_path.exists())
            self.assertTrue(Path(str(log_path) + ".1").exists())

    def test_a_small_log_is_left_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "neural.log"
            log_path.write_text("small", encoding="utf-8")
            supervisor = self._supervisor([self._component("neural")])
            supervisor.max_log_bytes = 1024
            supervisor.rotate_log(log_path)
            self.assertTrue(log_path.exists())
            self.assertFalse(Path(str(log_path) + ".1").exists())

    def test_rotation_keeps_a_bounded_number_of_generations(self):
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "neural.log"
            supervisor = self._supervisor([self._component("neural")])
            supervisor.max_log_bytes = 16
            supervisor.log_generations = 3
            for _ in range(6):
                log_path.write_text("y" * 64, encoding="utf-8")
                supervisor.rotate_log(log_path)
            kept = sorted(item.name for item in Path(folder).iterdir())
            self.assertEqual(kept, ["neural.log.1", "neural.log.2", "neural.log.3"])

    def test_rotation_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "neural.log"
            log_path.write_text("z" * 4096, encoding="utf-8")
            supervisor = self._supervisor([self._component("neural")])
            supervisor.max_log_bytes = 0
            supervisor.rotate_log(log_path)
            self.assertTrue(log_path.exists())

    def test_a_thermal_hold_prevents_any_start(self):
        component = self._component("gesture")
        supervisor = self._supervisor([component], thermal_guard=True)
        supervisor._thermal_block_until = time.monotonic() + 60.0
        supervisor.tick()
        self.assertEqual(supervisor.starts, [])


if __name__ == "__main__":
    unittest.main()
