"""Failure and ownership regressions for the state-input environment."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from simulation.environment import (state_input_world, require_idle_world,
    cleanup_actions, paced_tick, input_heartbeat_ready, write_input_heartbeat,
    prepare_state_world)
from stack_supervisor import build_components, parse_args, carla_rpc_probe
from neural_drive_agent import (run as run_neural)


class InputEnvironmentTests(unittest.TestCase):
    def world(self):
        settings = SimpleNamespace(synchronous_mode=False, no_rendering_mode=False,
            fixed_delta_seconds=None, substepping=False,
            max_substep_delta_time=0.01, max_substeps=10)
        world = Mock()
        world.get_settings.side_effect = lambda: copy.deepcopy(settings)
        world.apply_settings.side_effect = lambda s: settings.__dict__.update(vars(s))
        world.get_actors.return_value.filter.return_value = []
        return world, settings

    def test_fixed_physics_and_weather_restore_after_body_failure(self):
        world, settings = self.world()
        original = vars(settings).copy()
        weather = world.get_weather.return_value
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            with state_input_world(world, Mock()):
                self.assertTrue(settings.no_rendering_mode)
                self.assertTrue(settings.synchronous_mode)
                self.assertEqual(settings.fixed_delta_seconds, 0.05)
                raise RuntimeError('failure')
        self.assertEqual(vars(settings), original)
        world.set_weather.assert_called_with(weather)

    def test_reject_other_actors_before_world_mutation(self):
        for pattern in ('vehicle.*', 'sensor.camera.*', 'sensor.*', 'walker.*'):
            with self.subTest(pattern=pattern):
                world, _ = self.world()
                world.get_actors.return_value.filter.side_effect = lambda p: [object()] if p == pattern else []
                with self.assertRaises(RuntimeError):
                    with state_input_world(world, Mock()):
                        self.fail('must not enter')
                world.apply_settings.assert_not_called()
                world.set_weather.assert_not_called()

    def test_reject_other_tick_owner_before_mutation(self):
        world, settings = self.world()
        settings.synchronous_mode = True
        with self.assertRaisesRegex(RuntimeError, 'Another client'):
            require_idle_world(world)
        world.apply_settings.assert_not_called()

    def test_weather_failure_cannot_skip_settings_restore(self):
        world, settings = self.world()
        original = vars(settings).copy()
        world.set_weather.side_effect = RuntimeError('disconnected')
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            with state_input_world(world, Mock()):
                pass
        self.assertEqual(vars(settings), original)

    def test_cleanup_continues_after_destroy_error(self):
        broken = Mock(side_effect=RuntimeError('server down'))
        next_action = Mock()
        cleanup_actions([('sensor', broken), ('vehicle', next_action)])
        next_action.assert_called_once()

    def test_ticks_are_paced_without_catchup_bursts(self):
        for elapsed, expected_sleep in ((0.01, 0.04), (0.2, 0.0)):
            world = Mock()
            with patch('simulation.environment.time.monotonic', return_value=10 + elapsed), \
                    patch('simulation.environment.time.sleep') as sleep:
                paced_tick(world, 2.0, 10.0)
                world.tick.assert_called_once_with(2.0)
                self.assertAlmostEqual(sleep.call_args.args[0], expected_sleep)

    def test_heartbeat_rejects_stale_prior_run_future_or_broken_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'health.json'
            with patch('simulation.environment.time.monotonic', return_value=100.0):
                self.assertFalse(input_heartbeat_ready(path, 95.0))
                write_input_heartbeat(path, 10)
                self.assertTrue(input_heartbeat_ready(path, 95.0))
                self.assertFalse(input_heartbeat_ready(path, 101.0))
                for stamp in (80, 110, float('nan')):
                    path.write_text(json.dumps(dict(updated_monotonic=stamp, frame=10)), encoding="utf-8")
                    self.assertFalse(input_heartbeat_ready(path, 0))
                path.write_text('{broken', encoding="utf-8")
                self.assertFalse(input_heartbeat_ready(path, 0))

    def test_stalled_synchronous_server_is_unhealthy_without_ticking_it(self):
        with patch('carla.Client') as client:
            world = client.return_value.get_world.return_value
            world.get_settings.return_value.synchronous_mode = True
            world.wait_for_tick.side_effect = RuntimeError('no owner')
            self.assertFalse(carla_rpc_probe('127.0.0.1', 2000))
            world.tick.assert_not_called()

    def test_custom_port_reaches_both_server_and_driver(self):
        components = build_components(parse_args(['--rpc-port', '2100']))
        server, neural = components
        self.assertIn('-carla-rpc-port=2100', server.argv)
        self.assertEqual(neural.argv[neural.argv.index('--map') + 1], 'Town02_Opt')
        self.assertEqual(neural.argv[neural.argv.index('--port') + 1], '2100')
        self.assertIsNotNone(neural.probe)

    def test_map_load_preserves_disabled_renderer_and_rejects_busy_world(self):
        world, settings = self.world()
        world.get_map.return_value.name = 'Carla/Maps/Town10HD_Opt'
        client = Mock()
        client.get_world.return_value = world
        client.load_world.return_value = world
        def load(*args, **kwargs):
            self.assertTrue(settings.no_rendering_mode)
            self.assertFalse(kwargs['reset_settings'])
            return world
        client.load_world.side_effect = load
        carla = Mock()
        self.assertIs(prepare_state_world(client, carla, 'Town02_Opt'), world)
        client.load_world.assert_called_once_with('Town02_Opt', reset_settings=False,
                                                 map_layers=carla.MapLayer.NONE)
        client.reset_mock()
        settings.synchronous_mode = True
        with self.assertRaisesRegex(RuntimeError, 'Another client'):
            prepare_state_world(client, carla, 'Town05')
        client.load_world.assert_not_called()

    def test_neural_missing_policy_never_connects_to_simulator(self):
        with tempfile.TemporaryDirectory() as directory, patch('carla.Client') as client:
            args = SimpleNamespace(bootstrap_train=False,
                carla_root=r'C:\CARLA\CARLA_0.9.16',
                policy=str(Path(directory) / 'missing.json'))
            with self.assertRaises(FileNotFoundError):
                run_neural(args)
            client.assert_not_called()

    def test_neural_vehicle_is_cleaned_if_physics_configuration_fails(self):
        world, settings = self.world()
        world.get_map.return_value.get_spawn_points.return_value = [object()]
        original = vars(settings).copy()
        vehicle = world.try_spawn_actor.return_value
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'test-placeholder.json'
            policy.write_text('{}', encoding="utf-8")
            args = SimpleNamespace(bootstrap_train=False,
                carla_root=r'C:\CARLA\CARLA_0.9.16',
                policy=str(policy), host='127.0.0.1', port=2000, map=None)
            with patch('carla.Client'), \
                    patch('neural_drive_agent.load_deployable_policy'), \
                    patch('neural_drive_agent.prepare_state_world', return_value=world), \
                    patch('vehicle.transmission.configure_vehicle_six_speed_physics',
                          side_effect=RuntimeError('physics failure')):
                with self.assertRaisesRegex(RuntimeError, 'physics failure'):
                    run_neural(args)
            vehicle.destroy.assert_called_once()
            self.assertEqual(vars(settings), original)


if __name__ == '__main__':
    unittest.main()
