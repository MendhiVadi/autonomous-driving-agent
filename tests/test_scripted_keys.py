"""Scripted diagnostic key replay: parsing and timing, without a simulator."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pygame  # noqa: E402

from cockpit.viewport_input import ScriptedDrivingKeys, parse_key_schedule  # noqa: E402


class KeyScheduleTests(unittest.TestCase):
    def test_valid_schedule_is_normalised(self):
        schedule = parse_key_schedule('[[1, 3.5, ["W", "d"]], [4, 5, ["space"]]]')
        self.assertEqual(schedule, [(1.0, 3.5, ("w", "d")), (4.0, 5.0, ("space",))])

    def test_bad_schedules_are_rejected(self):
        for bad in ('{}', '[[1,2]]', '[[2,1,["w"]]]', '[[-1,2,["w"]]]', '[[0,1,[]]]',
                    '[[0,1,[3]]]', '[[true,2,["w"]]]', '[["a",2,["w"]]]', '[[0,Infinity,["w"]]]'):
            with self.assertRaises(ValueError, msg=bad):
                parse_key_schedule(bad)

    def test_replay_follows_the_clock_and_reports_focus(self):
        now = [100.0]
        keys = ScriptedDrivingKeys(pygame, parse_key_schedule('[[1, 3, ["w", "d"]], [5, 6, ["s"]]]'),
                                   lambda: now[0])
        self.assertFalse(keys[pygame.K_w])          # not started: nothing pressed
        keys.start()
        self.assertTrue(keys.focused())
        for offset, w, d, s in ((0.5, False, False, False), (1.0, True, True, False),
                                (2.9, True, True, False), (3.0, False, False, False),
                                (5.5, False, False, True), (6.0, False, False, False)):
            now[0] = 100.0 + offset
            self.assertEqual((keys[pygame.K_w], keys[pygame.K_d], keys[pygame.K_s]), (w, d, s), offset)
        self.assertFalse(keys[pygame.K_UP])

    def test_named_keys_resolve_and_unknown_names_fail_fast(self):
        now = [0.0]
        keys = ScriptedDrivingKeys(pygame, parse_key_schedule(
            '[[0, 1, ["up", "left", "space", "down", "right"]]]'), lambda: now[0])
        keys.start()
        for key in (pygame.K_UP, pygame.K_LEFT, pygame.K_SPACE, pygame.K_DOWN, pygame.K_RIGHT):
            self.assertTrue(keys[key], key)
        self.assertFalse(keys[pygame.K_w])
        bad = ScriptedDrivingKeys(pygame, parse_key_schedule('[[0, 1, ["warp"]]]'), lambda: 0.0)
        with self.assertRaises(ValueError):
            bad.start()


if __name__ == "__main__":
    unittest.main()
