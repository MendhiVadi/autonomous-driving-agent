import math
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from sim_host.manual import steering_step
from sim_host.profiles import PRESENTATION
from sim_host.watchdog import CommandWatchdog
from sim_host.world import cleanup_actions, require_idle_world


class HostTests(unittest.TestCase):
    def test_full_graphics_profile_preserves_foliage_and_wind(self):
        args = PRESENTATION.server_arguments()
        self.assertIn("-quality-level=Epic", args)
        self.assertIn("-windowed", args)
        self.assertEqual(PRESENTATION.wind, 65)
        self.assertFalse(any("foliage.DensityScale 0" in arg for arg in args))
        with self.assertRaises(ValueError):
            PRESENTATION.server_arguments("unknown")

    def test_steering_is_bounded_and_recenters(self):
        self.assertAlmostEqual(steering_step(0, 1, 1 / 30), .05)
        self.assertEqual(steering_step(.69, 1, 10), .7)
        self.assertEqual(steering_step(-.69, -1, 10), -.7)
        self.assertEqual(steering_step(.05, 0, 1 / 30), 0)

    def test_unreal_switches_match_the_working_native_launch_format(self):
        self.assertEqual(PRESENTATION.server_command_line(),
                         '-windowed -dx11 -quality-level=Epic -ResX=1280 -ResY=720 '
                         '-fps=30 -carla-rpc-port=2000 -ExecCmds="t.MaxFPS 30"')

    def test_another_tick_owner_is_rejected_before_actor_queries(self):
        world = Mock()
        world.get_settings.return_value = SimpleNamespace(synchronous_mode=True)
        with self.assertRaises(RuntimeError):
            require_idle_world(world)
        world.get_actors.assert_not_called()

    def test_existing_vehicle_is_rejected(self):
        world = Mock()
        world.get_settings.return_value = SimpleNamespace(synchronous_mode=False)
        world.get_actors.return_value.filter.side_effect = lambda name: [1] if name == "vehicle.*" else []
        with self.assertRaises(RuntimeError):
            require_idle_world(world)

    def test_cleanup_continues_after_failure(self):
        later = Mock()
        cleanup_actions([("failed", Mock(side_effect=RuntimeError("test"))),
                         ("later", later)])
        later.assert_called_once()

    def test_watchdog_calls_brake_when_publication_stops(self):
        braked = threading.Event()
        watchdog = CommandWatchdog(timeout_s=.02, poll_interval_s=.005)
        watchdog.start(braked.set)
        try:
            watchdog.command_received()
            self.assertTrue(braked.wait(1))
            self.assertTrue(watchdog.status()["triggered"])
        finally:
            watchdog.stop()

    def test_invalid_watchdog_timeouts_are_rejected(self):
        for value in (0, -1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                CommandWatchdog(timeout_s=value)
