"""Large-map loading and tile warm-up for the manual driver, without a simulator."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from simulation.environment import (is_large_map, load_world_for_driving, map_short_name,
                                    warm_up_large_map_tiles)


class LargeMapTests(unittest.TestCase):
    def world(self, name="/Game/Carla/Maps/Town02_Opt"):
        world = Mock()
        world.get_settings.side_effect = lambda: SimpleNamespace(synchronous_mode=False)
        world.get_actors.return_value.filter.return_value = []
        world.get_map.return_value.name = name
        return world

    def test_map_names_are_normalised(self):
        self.assertEqual(map_short_name("/Game/Carla/Maps/Town13/Town13"), "Town13")
        self.assertTrue(is_large_map("Town13") and is_large_map("Carla/Maps/Town12"))
        self.assertFalse(is_large_map("Town02_Opt"))

    def test_large_map_bounds_initial_streaming_without_disabling_graphics(self):
        world = self.world()
        client = Mock()
        client.get_world.return_value = world
        carla = SimpleNamespace(MapLayer=SimpleNamespace(All="all"))
        load_world_for_driving(client, "Town13", carla)
        settings = world.apply_settings.call_args.args[0]
        self.assertFalse(settings.spectator_as_ego)
        self.assertEqual(settings.tile_stream_distance, 650)
        self.assertFalse(hasattr(settings, "no_rendering_mode"))
        client.load_world.assert_called_once_with("Town13", reset_settings=False, map_layers="all")

    def test_small_map_loads_every_layer_and_restores_optimised_scenery(self):
        world = self.world("/Game/Carla/Maps/Town02_Opt")
        client = Mock()
        client.get_world.return_value = world
        carla = SimpleNamespace(MapLayer=SimpleNamespace(All="all"))
        load_world_for_driving(client, "Town02_Opt", carla)
        client.load_world.assert_not_called()
        world.load_map_layer.assert_called_once_with("all")
        load_world_for_driving(client, "Town05", carla)
        client.load_world.assert_called_once_with("Town05", map_layers="all")

    def test_busy_world_is_not_modified(self):
        world = self.world()
        world.get_settings.side_effect = None
        world.get_settings.return_value = SimpleNamespace(synchronous_mode=True)
        client = Mock()
        client.get_world.return_value = world
        with self.assertRaises(RuntimeError):
            load_world_for_driving(client, "Town13", Mock())
        world.apply_settings.assert_not_called()
        client.load_world.assert_not_called()

    def test_failed_map_load_attempts_settings_restore(self):
        world = self.world()
        client = Mock()
        client.get_world.return_value = world
        client.load_world.side_effect = RuntimeError("map timeout")
        with self.assertRaises(RuntimeError):
            load_world_for_driving(client, "Town13", Mock())
        self.assertEqual(world.apply_settings.call_count, 2)

    def test_small_maps_do_not_use_long_tile_warmup(self):
        world = self.world()
        warm_up_large_map_tiles(world, Mock(), Mock(), Mock())
        world.tick.assert_not_called()

    def warmup_objects(self):
        world, vehicle, client = Mock(), Mock(), Mock()
        vehicle.get_transform.return_value = SimpleNamespace(
            location=10, get_forward_vector=lambda: 1, rotation=SimpleNamespace(yaw=0))
        carla = SimpleNamespace(VehicleControl=lambda **kw: kw, Location=lambda **kw: kw["z"],
                                Rotation=lambda **kw: kw, Transform=lambda location, rotation: (location, rotation))
        return world, vehicle, client, carla

    def test_warmup_holds_brakes_and_restores_short_timeout(self):
        world, vehicle, client, carla = self.warmup_objects()
        warm_up_large_map_tiles(world, vehicle, client, carla, "Town13")
        vehicle.apply_control.assert_called_once_with({"brake": 1.0, "hand_brake": True})
        self.assertEqual([call.args[0] for call in world.tick.call_args_list], [60, 10, 10, 10])
        self.assertEqual([call.args[0] for call in client.set_timeout.call_args_list], [60, 10, 5])
        world.get_map.assert_not_called()

    def test_failed_tile_tick_restores_timeout_without_retry(self):
        world, vehicle, client, carla = self.warmup_objects()
        world.tick.side_effect = RuntimeError("tile timeout")
        with self.assertRaisesRegex(RuntimeError, "tile timeout"):
            warm_up_large_map_tiles(world, vehicle, client, carla, "Town13")
        world.tick.assert_called_once_with(60)
        self.assertEqual([call.args[0] for call in client.set_timeout.call_args_list], [60, 5])


if __name__ == "__main__":
    unittest.main()
