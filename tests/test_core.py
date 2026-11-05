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
from learning.model import (MLP, load_deployable_policy)
from learning.assistance import (apply_stall_recovery)
from simulation.observations import (make_observation)
from vehicle.safety import SafetySupervisor
from vehicle.control import VehicleCommand, steering_angle_from_lane_error
from runtime.watchdog import CommandWatchdog
from learning.contract import POLICY_CONTRACT_VERSION, normalize_features
from vehicle.transmission import (EngineRpmEstimator, ManualTransmissionConfig,
                                 automatic_gear_for_speed, estimate_engine_rpm,
                                 gear_redline_speed_kmh,
                                 recommended_shift)
from runtime.health import HealthEvent, evaluate_health
from simulation.environment import carla_rpc_probe


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

if __name__ == "__main__":
    unittest.main()
