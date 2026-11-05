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
    prepare_state_world, carla_rpc_probe, tick_with_patience, wait_for_carla)


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

class PatientTickTests(unittest.TestCase):
    def test_returns_the_frame_when_the_first_tick_succeeds(self):
        world = Mock()
        world.tick.return_value = 42
        stalls = []
        self.assertEqual(tick_with_patience(world, 2.0, max_wait_s=10.0, on_stall=stalls.append), 42)
        world.tick.assert_called_once_with(2.0)
        self.assertEqual(stalls, [])

    def test_slow_frames_are_retried_and_reported_until_one_arrives(self):
        world = Mock()
        world.tick.side_effect = [RuntimeError('time-out of 2000ms'), RuntimeError('time-out of 2000ms'), 7]
        now = [0.0]

        def clock():
            now[0] += 2.0
            return now[0]
        stalls = []
        self.assertEqual(tick_with_patience(world, 2.0, max_wait_s=30.0, on_stall=stalls.append, clock=clock), 7)
        self.assertEqual(world.tick.call_count, 3)
        self.assertEqual(len(stalls), 2)
        self.assertTrue(all(0 < value < 30 for value in stalls))

    def test_gives_up_after_the_ceiling_with_the_simulator_error_attached(self):
        world = Mock()
        world.tick.side_effect = RuntimeError('time-out of 2000ms')
        now = [0.0]

        def clock():
            now[0] += 20.0
            return now[0]
        with self.assertRaisesRegex(RuntimeError, 'no frame for') as raised:
            tick_with_patience(world, 2.0, max_wait_s=30.0, clock=clock)
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertLessEqual(world.tick.call_count, 3)

    def test_rejects_invalid_timeouts(self):
        for timeout, ceiling in ((0, 10), (float('nan'), 10), (2, 0), (2, float('inf'))):
            with self.subTest(timeout=timeout, ceiling=ceiling), self.assertRaises(ValueError):
                tick_with_patience(Mock(), timeout, max_wait_s=ceiling)


class WaitForCarlaTests(unittest.TestCase):
    def test_returns_as_soon_as_the_probe_answers(self):
        answers = iter([False, False, True])
        slept = []
        now = [0.0]

        def clock():
            return now[0]

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds
        self.assertTrue(wait_for_carla(seconds=15.0, interval_s=2.0, probe=lambda h, p: next(answers),
                                       clock=clock, sleep=sleep))
        self.assertEqual(slept, [2.0, 2.0])

    def test_gives_up_when_the_budget_runs_out(self):
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds
        self.assertFalse(wait_for_carla(seconds=5.0, interval_s=2.0, probe=lambda h, p: False,
                                        clock=lambda: now[0], sleep=sleep))
        self.assertGreaterEqual(now[0], 5.0)

    def test_zero_budget_still_probes_once(self):
        calls = []
        self.assertTrue(wait_for_carla(seconds=0.0, probe=lambda h, p: calls.append((h, p)) or True,
                                       sleep=lambda s: self.fail('must not sleep')))
        self.assertEqual(calls, [('127.0.0.1', 2000)])

    def test_rejects_invalid_budget(self):
        for seconds, interval in ((-1, 2), (float('nan'), 2), (5, 0)):
            with self.subTest(seconds=seconds, interval=interval), self.assertRaises(ValueError):
                wait_for_carla(seconds=seconds, interval_s=interval, probe=lambda h, p: True)


if __name__ == '__main__':
    unittest.main()
