"""Offline checks for cockpit layout, text fitting and camera sizing."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import pygame  # noqa: E402

from cockpit import hud  # noqa: E402
from cockpit.graphics import readback_safe_size  # noqa: E402
from vehicle.transmission import ManualTransmissionConfig  # noqa: E402


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


class ReadbackSizeTests(unittest.TestCase):
    def test_unsafe_240_wide_feed_is_widened_with_same_aspect(self):
        self.assertEqual(readback_safe_size(240, 135), (256, 144))

    def test_known_clean_sizes_are_unchanged(self):
        for size in ((320, 180), (256, 144), (192, 108), (640, 360)):
            self.assertEqual(readback_safe_size(*size), size)

    def test_every_result_has_256_byte_rows(self):
        for width in range(32, 900, 7):
            safe_width, safe_height = readback_safe_size(width, width * 9 // 16 or 1)
            self.assertEqual((safe_width * 4) % 256, 0)
            self.assertGreater(safe_height, 0)

    def test_invalid_sizes_are_rejected(self):
        with self.assertRaises(ValueError):
            readback_safe_size(0, 10)


class LayoutTests(unittest.TestCase):
    def test_zones_fit_the_window_and_do_not_overlap(self):
        for size in ((960, 540), (1280, 720), (800, 450)):
            zones = hud.compute_layout(*size, "triple")
            for name, (x, y, w, h) in zones.items():
                self.assertGreater(w, 0, name)
                self.assertGreater(h, 0, name)
                self.assertTrue(0 <= x and 0 <= y and x + w <= size[0] and y + h <= size[1], name)
            names = list(zones)
            for i, first in enumerate(names):
                for second in names[i + 1:]:
                    self.assertFalse(_overlap(zones[first], zones[second]), (size, first, second))

    def test_map_profile_uses_the_whole_lower_area_for_the_map(self):
        zones = hud.compute_layout(960, 540, "map")
        self.assertEqual(zones["front"][0], 0)
        self.assertEqual(zones["front"][2], 960)


class TextAndPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.display = pygame.display.set_mode((960, 540))
        cls.fonts = {"hud": pygame.font.Font(None, 28), "small": pygame.font.Font(None, 22),
                     "tick": pygame.font.Font(None, 14)}

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_fit_text_never_exceeds_width(self):
        font = self.fonts["small"]
        for width in (20, 60, 135, 400):
            fitted = hud.fit_text(font, "LIVE MAP  HEADING UP  Rd 4 Ln -1  X -8 Y 128", width)
            self.assertLessEqual(font.size(fitted)[0], width, fitted)

    def test_short_text_is_left_alone(self):
        self.assertEqual(hud.fit_text(self.fonts["small"], "LIVE MAP", 400), "LIVE MAP")

    def test_instruments_draw_in_every_gear_state(self):
        zones = hud.compute_layout(960, 540, "triple")
        config = ManualTransmissionConfig()
        control = SimpleNamespace(throttle=0.8, brake=0.2)
        for automatic in (True, False):
            for requested, parked in ((1, False), (-1, False), (0, False), (0, True), (6, False)):
                self.display.fill((0, 0, 0))
                hud.draw_instruments(pygame, self.display, self.fonts, zones["instrument"], config,
                                     135.0, 6800.0, 3, requested, 0.0, parked, parked, control,
                                     automatic=automatic, gear_in_sync=False)

    def test_automatic_mode_never_shows_manual_gear_sync_warning(self):
        zones = hud.compute_layout(960, 540, "triple")
        x, y, w, h = zones["instrument"]
        config = ManualTransmissionConfig()
        control = SimpleNamespace(throttle=0.0, brake=0.0)
        hint_area = pygame.Rect(x + 4, y + h - 30, w - 8, 12)
        self.display.fill((0, 0, 0))
        hud.draw_instruments(pygame, self.display, self.fonts, zones["instrument"], config,
                             0.0, 850.0, 1, 1, 0.0, False, False, control,
                             automatic=True, gear_in_sync=False)
        red_pixels = sum(1 for px in range(hint_area.left, hint_area.right)
                         for py in range(hint_area.top, hint_area.bottom)
                         if self.display.get_at((px, py))[:3] == (255, 102, 92))
        self.assertEqual(red_pixels, 0)

    def test_long_status_wraps_instead_of_being_cut_off(self):
        font = self.fonts["hud"]
        message = "MODEL STOP - REALIGN MANUALLY OR BACKSPACE RESET"
        width = 380
        lines = hud.wrap_text(font, message, width, max_lines=2)
        self.assertEqual(len(lines), 2)
        self.assertEqual(" ".join(lines), message)
        for line in lines:
            self.assertLessEqual(font.size(line)[0], width)
        self.assertEqual(hud.wrap_text(font, "READY", width), ["READY"])
        very_long = hud.wrap_text(font, "WORD " * 40, width, max_lines=2)
        self.assertEqual(len(very_long), 2)
        self.assertTrue(very_long[-1].endswith("..."))

    def test_status_panel_draws_long_status_and_hints(self):
        zones = hud.compute_layout(960, 540, "triple")
        self.display.fill((0, 0, 0))
        hud.draw_status_panel(pygame, self.display, self.fonts, zones["rear"], "FRONT / LEFT / RIGHT CAMERAS",
                              "STILL OFF ROUTE - PRESS BACKSPACE TO RESET AND TRY AGAIN NOW", ("A", "B"))

    def test_feed_overlay_reports_waiting_and_stale_feeds(self):
        zones = hud.compute_layout(960, 540, "triple")
        for age in (None, 0.2, 9.0):
            hud.draw_feed_overlay(pygame, self.display, self.fonts, zones["right"], "RIGHT", age)


if __name__ == "__main__":
    unittest.main()
