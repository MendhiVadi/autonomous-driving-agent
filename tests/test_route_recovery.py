"""Stuck-car recovery decisions, without a simulator."""
import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from cockpit import recovery  # noqa: E402
from learning.assistance import apply_stall_recovery  # noqa: E402


class Point:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z

    def distance(self, other):
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2) ** 0.5


def plan_along_x(count, spacing=2.0, yaw=0.0):
    return [(SimpleNamespace(transform=SimpleNamespace(
        location=Point(i * spacing, 0.0), rotation=SimpleNamespace(yaw=yaw))), None) for i in range(count)]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ConstantsTests(unittest.TestCase):
    def test_start_delays_match_the_assistance_defaults(self):
        defaults = inspect.signature(apply_stall_recovery).parameters
        self.assertEqual(defaults["activation_delay_s"].default, recovery.START_DELAY_S)
        self.assertEqual(defaults["brake_override_delay_s"].default, recovery.START_BRAKE_DELAY_S)
        self.assertEqual(recovery.start_wait_total(0.96), recovery.START_BRAKE_DELAY_S)
        self.assertEqual(recovery.start_wait_total(0.1), recovery.START_DELAY_S)

    def test_off_route_limits_follow_lane_assist(self):
        self.assertFalse(recovery.is_off_route([1.5, 5.0], lane_assist=True))
        self.assertTrue(recovery.is_off_route([1.7, 5.0], lane_assist=True))
        self.assertTrue(recovery.is_off_route([1.5, 5.0], lane_assist=False))
        self.assertTrue(recovery.is_off_route([0.0, -15.5], lane_assist=True))
        self.assertFalse(recovery.is_off_route([-1.0, 14.0], lane_assist=False))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.monitor = recovery.OffRouteMonitor(clock=self.clock)

    def test_counts_down_then_becomes_ready(self):
        report = self.monitor.update(True, True, False)
        self.assertEqual(report["phase"], "waiting")
        self.clock.now += 1.0
        self.assertAlmostEqual(self.monitor.update(True, True, False)["elapsed_s"], 1.0)
        self.clock.now += 2.0
        self.assertEqual(self.monitor.update(True, True, False)["phase"], "ready")

    def test_motion_or_returning_to_route_resets_the_clock(self):
        self.monitor.update(True, True, False)
        self.clock.now += 2.5
        self.assertEqual(self.monitor.update(False, True, False)["phase"], "idle")
        self.clock.now += 0.1
        self.assertAlmostEqual(self.monitor.update(True, True, False)["elapsed_s"], 0.0)
        self.assertEqual(self.monitor.update(True, False, False)["phase"], "idle")

    def test_collision_obstacle_or_red_light_are_never_recovered(self):
        self.monitor.update(True, True, False)
        self.clock.now += 10.0
        self.assertEqual(self.monitor.update(True, True, True)["phase"], "idle")

    def test_allowance_runs_out_after_three_attempts(self):
        for _ in range(3):
            self.monitor.update(True, True, False)
            self.clock.now += 3.1
            self.assertEqual(self.monitor.update(True, True, False)["phase"], "ready")
            self.monitor.record_attempt()
        self.monitor.update(True, True, False)
        self.clock.now += 5.0
        self.assertEqual(self.monitor.update(True, True, False)["phase"], "exhausted")
        self.monitor.reset_route()
        self.assertEqual(self.monitor.update(True, True, False)["phase"], "waiting")


class SnapTests(unittest.TestCase):
    def test_picks_the_nearest_waypoint_at_or_ahead_of_the_route_index(self):
        plan = plan_along_x(40)
        index = recovery.choose_snap_index(plan, Point(20.0, 3.0), route_index=5)
        self.assertEqual(index, 10)

    def test_never_snaps_backwards_past_the_route_index(self):
        plan = plan_along_x(40)
        self.assertEqual(recovery.choose_snap_index(plan, Point(0.0, 2.0), route_index=8), 8)

    def test_too_far_from_the_route_returns_none(self):
        plan = plan_along_x(40)
        self.assertIsNone(recovery.choose_snap_index(plan, Point(20.0, 60.0), route_index=0))
        self.assertIsNone(recovery.choose_snap_index([], Point(0, 0), 0))

    def test_pose_is_lifted_and_faces_the_route(self):
        plan = plan_along_x(5, yaw=90.0)
        (x, y, z), yaw = recovery.snap_pose(plan, 3, lift_m=0.3)
        self.assertEqual((x, y, yaw), (6.0, 0.0, 90.0))
        self.assertAlmostEqual(z, 0.3)

    def test_occupied_target_is_detected(self):
        target = Point(0, 0)
        self.assertTrue(recovery.spot_is_free(target, [Point(10, 0)]))
        self.assertFalse(recovery.spot_is_free(target, [Point(10, 0), Point(2, 1)]))
        self.assertTrue(recovery.spot_is_free(target, []))


class ReportTests(unittest.TestCase):
    def test_wait_report_is_bounded_and_page_ready(self):
        report = recovery.wait_report("realign", "R" * 80, 9.0, 3.0)
        self.assertEqual(report["kind"], "realign")
        self.assertEqual(len(report["label"]), 40)
        self.assertEqual(report["elapsed_s"], 3.0)
        self.assertEqual(report["total_s"], 3.0)
        self.assertGreater(recovery.wait_report("start", "x", -2, 0)["total_s"], 0)


if __name__ == "__main__":
    unittest.main()
