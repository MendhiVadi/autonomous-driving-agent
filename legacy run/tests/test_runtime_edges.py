"""Failures at runtime boundaries; no running simulator is required."""
import math
import threading
import unittest
from unittest.mock import Mock, patch

from runtime.watchdog import CommandWatchdog, LinkWatchdog
from scenic_drive import steering_step


class RuntimeEdgeTests(unittest.TestCase):
    def test_missing_first_command_triggers_braking(self):
        braked = threading.Event()
        watchdog = CommandWatchdog(.02, .005)
        watchdog.start(braked.set)
        try:
            self.assertTrue(braked.wait(.3), "No first command must not disable the watchdog")
        finally:
            watchdog.stop()

    def test_still_running_callback_is_not_forgotten_during_stop(self):
        watchdog = CommandWatchdog(.02, .005)
        worker = Mock()
        worker.is_alive.return_value = True
        watchdog._thread = worker
        watchdog.stop()
        self.assertIs(watchdog._thread, worker)
        with self.assertRaises(RuntimeError):
            watchdog.start(lambda: None)

    def test_restart_resets_the_previous_trip(self):
        watchdog = CommandWatchdog(.02, .005)
        first, second = threading.Event(), threading.Event()
        try:
            watchdog.start(first.set)
            watchdog.command_received()
            self.assertTrue(first.wait(.3))
            watchdog.stop()
            watchdog.start(second.set)
            self.assertTrue(second.wait(.3))
        finally:
            watchdog.stop()

    def test_watchdog_rejects_non_callable_callback(self):
        watchdog = CommandWatchdog()
        try:
            with self.assertRaises(ValueError):
                watchdog.start(None)
        finally:
            watchdog.stop()

    def test_link_needs_both_messages_even_near_clock_origin(self):
        with patch("runtime.watchdog.time.monotonic", return_value=.1):
            link = LinkWatchdog()
            self.assertFalse(link.healthy())
            link.heartbeat()
            self.assertFalse(link.healthy())
            link.command_received()
            self.assertTrue(link.healthy())

    def test_invalid_steering_values_fail_before_controls_are_built(self):
        for args in [(math.nan, 0, .01), (math.inf, 1, .01),
                     (0, 1, math.nan), (0, 1, math.inf), (0, 3, .01),
                     (0, 1, -.01), (True, 0, .01)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                steering_step(*args)

    def test_recentering_also_clamps_previous_out_of_range_steering(self):
        self.assertLessEqual(abs(steering_step(20, 0, .01)), .7)
