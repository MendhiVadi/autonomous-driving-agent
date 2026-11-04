"""Adapter boundary tests using fake CARLA objects; these do not launch CARLA."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from sim_host.carla_backend import CarlaBackend
from sim_host.wire import ProtocolError


class CarlaBackendTests(unittest.TestCase):
    def backend(self):
        backend = CarlaBackend.__new__(CarlaBackend)
        backend.vehicle = Mock(id=1)
        backend.sensor = Mock(id=2)
        backend.control_lock = threading.Lock()
        backend.world = Mock()
        backend.carla = SimpleNamespace(VehicleControl=lambda **kw: kw)
        return backend

    def test_unexpected_vehicle_refuses_to_tick(self):
        backend = self.backend()
        backend.world.get_actors.return_value.filter.side_effect = lambda pattern: [Mock(id=99)] if pattern == "vehicle.*" else []
        with self.assertRaises(RuntimeError):
            backend.step({"throttle": .2, "brake": 0, "steer": 0})
        backend.vehicle.apply_control.assert_not_called()
        backend.world.tick.assert_not_called()

    def test_owned_actors_are_allowed_and_one_step_ticks_once(self):
        backend = self.backend()
        backend.world.get_actors.return_value.filter.side_effect = lambda pattern: (
            [backend.vehicle] if pattern == "vehicle.*" else [backend.sensor] if pattern == "sensor.*" else [])
        backend.snapshot = Mock(return_value={"checked": True})
        self.assertEqual(backend.step({"throttle": 0, "brake": 1, "steer": 0}), {"checked": True})
        backend.world.tick.assert_called_once_with(5)
        backend.vehicle.apply_control.assert_called_once_with({"throttle": 0, "brake": 1, "steer": 0, "reverse": False})

    def test_episode_cleanup_attempts_vehicle_after_sensor_failure(self):
        backend = self.backend()
        sensor, vehicle = backend.sensor, backend.vehicle
        sensor.stop.side_effect = RuntimeError("sensor disconnected")
        backend._destroy_episode()
        sensor.destroy.assert_called_once()
        vehicle.destroy.assert_called_once()
        self.assertIsNone(backend.vehicle)
        self.assertIsNone(backend.sensor)

    def test_unsupported_scenario_does_not_change_world(self):
        backend = self.backend()
        with self.assertRaises(ProtocolError):
            backend.reset(1, "obstacle")
        backend.vehicle.apply_control.assert_not_called()

    def test_invalid_fixed_spawn_does_not_create_or_tick(self):
        backend = self.backend()
        backend.world.get_actors.return_value.filter.return_value = []
        backend.map = Mock()
        backend.map.get_spawn_points.return_value = [object(), object()]
        backend.spawn_index = 2
        with self.assertRaisesRegex(ValueError, "outside this map"):
            backend.reset(7, "lane_follow")
        backend.world.try_spawn_actor.assert_not_called()
        backend.world.tick.assert_not_called()

    def test_fixed_spawn_never_falls_back_to_a_different_area(self):
        backend = self.backend()
        backend.world.get_actors.return_value.filter.return_value = []
        first, second = object(), object()
        backend.map = Mock()
        backend.map.get_spawn_points.return_value = [first, second]
        backend.spawn_index = 1
        backend._route = Mock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "No clear same-lane route"):
            backend.reset(7, "lane_follow")
        backend._route.assert_called_once_with(second)
        backend.world.try_spawn_actor.assert_not_called()
        backend.world.tick.assert_not_called()

    def test_close_restores_settings_after_weather_failure(self):
        backend = self.backend()
        backend.original_settings = object()
        backend.original_weather = object()
        world = backend.world
        world.set_weather.side_effect = RuntimeError("weather failure")
        backend.close()
        world.apply_settings.assert_called_once_with(backend.original_settings)
        self.assertIsNone(backend.world)
