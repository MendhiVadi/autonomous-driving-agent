"""Stationary route-start alignment maths, without a simulator."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from cockpit.navigation import heading_delta_deg, route_start_alignment  # noqa: E402
from cockpit.options import parse_args  # noqa: E402
from cockpit.world import wait_until_settled  # noqa: E402


def plan_with_yaws(yaws):
    return [(SimpleNamespace(transform=SimpleNamespace(rotation=SimpleNamespace(yaw=yaw))), None)
            for yaw in yaws]


class HeadingTests(unittest.TestCase):
    def test_delta_takes_the_short_way_round(self):
        self.assertAlmostEqual(heading_delta_deg(10, 350), 20)
        self.assertAlmostEqual(heading_delta_deg(350, 10), -20)
        self.assertAlmostEqual(abs(heading_delta_deg(0, 180)), 180)
        self.assertAlmostEqual(heading_delta_deg(-170, 170), 20)

    def test_facing_the_route_needs_no_alignment(self):
        plan = plan_with_yaws([90.0] * 8)
        self.assertIsNone(route_start_alignment(plan, 90.0))
        self.assertIsNone(route_start_alignment(plan, 90.0 + 59.0))
        self.assertIsNone(route_start_alignment(plan, 90.0 - 60.0))

    def test_car_facing_away_is_realigned_to_the_route_heading(self):
        plan = plan_with_yaws([90.0] * 8)
        delta, desired = route_start_alignment(plan, 265.0)   # the ~175 degree Town13 case
        self.assertAlmostEqual(abs(delta), 175.0)
        self.assertEqual(desired, 90.0)
        self.assertIsNotNone(route_start_alignment(plan, 90.0 + 61.0))

    def test_short_plans_are_not_judged(self):
        self.assertIsNone(route_start_alignment(plan_with_yaws([90.0] * 4), 270.0))

    def test_alignment_uses_the_waypoint_ahead_not_the_first(self):
        plan = plan_with_yaws([200.0, 200.0, 200.0, 200.0, 90.0, 90.0])
        self.assertIsNone(route_start_alignment(plan, 90.0))


class SettleTests(unittest.TestCase):
    def test_waits_for_a_bouncing_spawn_to_stop(self):
        speeds = iter([6.8, 4.1, 1.5, 0.4])
        current = [next(speeds)]
        ticks = []

        def advance():
            ticks.append(1)
            current[0] = next(speeds)

        self.assertTrue(wait_until_settled(lambda: current[0], advance))
        self.assertEqual(len(ticks), 3)

    def test_already_stationary_does_not_tick(self):
        ticks = []
        self.assertTrue(wait_until_settled(lambda: 0.0, lambda: ticks.append(1)))
        self.assertEqual(ticks, [])

    def test_gives_up_when_the_car_keeps_moving(self):
        now = [0.0]

        def advance():
            now[0] += 1.0

        self.assertFalse(wait_until_settled(lambda: 9.0, advance, max_seconds=3.0, clock=lambda: now[0]))
        self.assertEqual(now[0], 3.0)


class DiagnosticOptionTests(unittest.TestCase):
    def test_diagnostic_options_have_safe_defaults_and_validate(self):
        args = parse_args([])
        self.assertEqual(args.diagnostic_yaw_offset, 0.0)
        self.assertIsNone(args.scripted_keys)
        with self.assertRaises(SystemExit):
            parse_args(["--diagnostic-yaw-offset", "nan"])



class CarlaApiUsageTests(unittest.TestCase):
    """The cockpit once called vehicle.set_velocity, which CARLA 0.9.16 does not have."""

    def test_every_vehicle_method_the_cockpit_calls_exists(self):
        import re
        import carla
        source = (Path(__file__).resolve().parents[1] / "app" / "cockpit" / "session.py").read_text(encoding="utf-8")
        called = set(re.findall(r"\bvehicle\.([a-z_]+)\(", source))
        self.assertIn("apply_control", called)
        missing = sorted(name for name in called if not hasattr(carla.Vehicle, name))
        self.assertEqual(missing, [])

    def test_world_methods_the_cockpit_calls_exist(self):
        import re
        import carla
        source = (Path(__file__).resolve().parents[1] / "app" / "cockpit" / "session.py").read_text(encoding="utf-8")
        called = set(re.findall(r"\bworld\.([a-z_]+)\(", source))
        self.assertIn("tick", called)
        missing = sorted(name for name in called if not hasattr(carla.World, name))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
