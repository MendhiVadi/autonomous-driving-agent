"""Map geometry, cached neural inputs and native manual control regressions."""
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

import carla
from simulation.observations import (make_observation)
from simulation.roads import build_road_segments, RoadSegmentIndex
from scenic_drive import steering_step
from simulation.environment import prepare_state_world


def waypoint(s, x, y, lane=1, section=0):
    return SimpleNamespace(s=s, road_id=1, section_id=section, lane_id=lane,
                           transform=carla.Transform(carla.Location(x=x, y=y)))


class DrivingModeTests(unittest.TestCase):
    def test_curved_lane_uses_interior_samples_not_endpoint_chord(self):
        points = [waypoint(0, 0, 0), waypoint(3, 2, 2), waypoint(6, 4, 0)]
        road = Mock()
        road.generate_waypoints.return_value = points
        road.get_topology.return_value = [(points[0], points[-1])]
        self.assertEqual(build_road_segments(road), [((0, 0), (2, 2)), ((2, 2), (4, 0))])

    def test_lane_gaps_and_different_lanes_are_not_joined(self):
        road = Mock()
        road.generate_waypoints.return_value = [waypoint(0, 0, 0), waypoint(3, 3, 0),
            waypoint(20, 20, 0), waypoint(3, 3, 3, lane=-1)]
        road.get_topology.return_value = []
        self.assertEqual(build_road_segments(road), [((0, 0), (3, 0))])

    def test_spatial_index_includes_crossing_segments_once(self):
        segments = [((-80, 0), (80, 0)), ((1000, 0), (1003, 0)), ((-3, -3), (0, 0))]
        index = RoadSegmentIndex(segments)
        nearby = list(index.nearby(0, 0, 10))
        self.assertEqual(nearby, [segments[0], segments[2]])

    def test_cached_map_produces_identical_neural_features_without_map_rpc(self):
        vehicle, world, road = Mock(), Mock(), Mock()
        vehicle.get_transform.return_value = carla.Transform(carla.Location(x=2, y=1), carla.Rotation(yaw=5))
        vehicle.get_velocity.return_value = carla.Vector3D(x=3)
        vehicle.get_traffic_light_state.return_value = carla.TrafficLightState.Green
        wp = Mock()
        wp.transform = carla.Transform()
        wp.next.return_value = []
        road.get_waypoint.return_value = wp
        world.get_map.return_value = road
        original = make_observation(vehicle, world, carla.TrafficLightState.Red, [])
        world.get_map.reset_mock()
        cached = make_observation(vehicle, world, carla.TrafficLightState.Red, [], carla_map=road)
        self.assertEqual(original, cached)
        world.get_map.assert_not_called()

    def test_matching_optimized_map_also_unloads_scenery(self):
        world = Mock()
        settings = SimpleNamespace(synchronous_mode=False, no_rendering_mode=False)
        world.get_settings.return_value = settings
        world.get_actors.return_value.filter.return_value = []
        world.get_map.return_value.name = '/Game/Carla/Maps/Town02_Opt'
        client = Mock()
        client.get_world.return_value = world
        self.assertIs(prepare_state_world(client, carla, 'Town02_Opt'), world)
        client.load_world.assert_not_called()
        world.unload_map_layer.assert_called_once_with(carla.MapLayer.All)
        self.assertTrue(settings.no_rendering_mode)

    def test_steering_is_rate_limited_and_recenters(self):
        self.assertAlmostEqual(steering_step(0, 1, 1 / 30), .05)
        self.assertAlmostEqual(steering_step(.05, 0, 1 / 30), 0)
        self.assertEqual(steering_step(.69, 1, 10), .7)
        self.assertEqual(steering_step(-.69, -1, 10), -.7)


if __name__ == '__main__':
    unittest.main()
