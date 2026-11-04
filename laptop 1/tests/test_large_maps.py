from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from sim_host.profiles import installed_map_path
from sim_host.world import load_map, warm_up_tiles


class LargeMapTests(unittest.TestCase):
    def world(self):
        world = Mock()
        world.get_settings.side_effect = lambda: SimpleNamespace(synchronous_mode=False)
        world.get_actors.return_value.filter.return_value = []
        world.get_map.return_value.name = "/Game/Carla/Maps/Town02_Opt"
        return world

    def test_invalid_names_rejected_before_filesystem_lookup(self):
        for name in ("../Town13", "Town13 -dx12", "Town13_Tile_0_0", "C:/Town13", "Town13\"", ""):
            with self.assertRaises(ValueError):
                installed_map_path("unused", name)

    def test_root_world_is_resolved_unambiguously(self):
        with tempfile.TemporaryDirectory() as temporary:
            maps = Path(temporary) / "CarlaUE4/Content/Carla/Maps"
            (maps / "Town13").mkdir(parents=True)
            (maps / "Town13/Town13.umap").touch()
            self.assertEqual(installed_map_path(temporary, "Town13"), "/Game/Carla/Maps/Town13/Town13")
            (maps / "Town13.umap").touch()
            with self.assertRaises(ValueError):
                installed_map_path(temporary, "Town13")

    def test_large_map_bounds_initial_streaming_without_disabling_graphics(self):
        world = self.world()
        client = Mock()
        client.get_world.return_value = world
        carla = SimpleNamespace(MapLayer=SimpleNamespace(All="all"))
        load_map(client, "Town13", carla)
        settings = world.apply_settings.call_args.args[0]
        self.assertFalse(settings.spectator_as_ego)
        self.assertEqual(settings.tile_stream_distance, 650)
        self.assertFalse(hasattr(settings, "no_rendering_mode"))
        client.load_world.assert_called_once_with("Town13", reset_settings=False, map_layers="all")

    def test_busy_world_is_not_modified(self):
        world = self.world()
        world.get_settings.side_effect = None
        world.get_settings.return_value = SimpleNamespace(synchronous_mode=True)
        client = Mock()
        client.get_world.return_value = world
        with self.assertRaises(RuntimeError):
            load_map(client, "Town13", Mock())
        world.apply_settings.assert_not_called()
        client.load_world.assert_not_called()

    def test_small_maps_do_not_use_long_tile_warmup(self):
        world = self.world()
        warm_up_tiles(world, Mock(), Mock(), Mock())
        world.tick.assert_not_called()

    def test_failed_map_load_attempts_settings_restore(self):
        world = self.world()
        client = Mock()
        client.get_world.return_value = world
        client.load_world.side_effect = RuntimeError("map timeout")
        with self.assertRaises(RuntimeError):
            load_map(client, "Town13", Mock())
        self.assertEqual(world.apply_settings.call_count, 2)

    def warmup_objects(self):
        world, vehicle, client = Mock(), Mock(), Mock()
        vehicle.get_transform.return_value = SimpleNamespace(
            location=10, get_forward_vector=lambda: 1,
            rotation=SimpleNamespace(yaw=0))
        carla = SimpleNamespace(VehicleControl=lambda **kw: kw,
                                Location=lambda **kw: kw["z"],
                                Rotation=lambda **kw: kw,
                                Transform=lambda location, rotation: (location, rotation))
        return world, vehicle, client, carla

    def test_warmup_holds_brakes_and_restores_short_timeout(self):
        world, vehicle, client, carla = self.warmup_objects()
        warm_up_tiles(world, vehicle, client, carla, "Town13")
        vehicle.apply_control.assert_called_once_with({"brake": 1.0, "hand_brake": True})
        self.assertEqual([call.args[0] for call in world.tick.call_args_list], [60, 10, 10, 10])
        self.assertEqual([call.args[0] for call in client.set_timeout.call_args_list], [60, 10, 5])
        world.get_map.assert_not_called()

    def test_failed_tile_tick_restores_timeout_without_retry(self):
        world, vehicle, client, carla = self.warmup_objects()
        world.tick.side_effect = RuntimeError("tile timeout")
        with self.assertRaisesRegex(RuntimeError, "tile timeout"):
            warm_up_tiles(world, vehicle, client, carla, "Town13")
        world.tick.assert_called_once_with(60)
        self.assertEqual([call.args[0] for call in client.set_timeout.call_args_list], [60, 5])
