import unittest
from learning.assistance import (apply_stall_recovery, is_stall_candidate, limit_neural_speed, apply_lane_assistance)


class PracticeRecoveryTests(unittest.TestCase):
    def test_lane_assistance_direction_bounds_and_speed(self):
        for lane, heading, sign in [(1.37, 9, -1), (-1.37, -9, 1)]:
            features = [lane, heading, 0, 30, 80, 0, 0, 1]
            corrected, correction, target = apply_lane_assistance(features, 0)
            self.assertGreater(corrected*sign, 0)
            self.assertLessEqual(abs(correction), .16)
            self.assertLess(target, 30)
            self.assertGreaterEqual(target, 12)
            accelerator, brake, active = apply_stall_recovery(
                features, .1, .9, 6, maximum_lane_error_m=1.6, max_accelerator=.2)
            self.assertTrue(active)
            self.assertLessEqual(accelerator, .2)
            self.assertEqual(brake, 0)

    def test_lane_assistance_defers_to_hazards(self):
        for index, value in [(0, 2.1), (4, 4), (5, 1)]:
            features = [1, 10, 12, 30, 80, 0, 0, 0]
            features[index] = value
            self.assertEqual(apply_lane_assistance(features, .2), (.2, 0, 30))
        with self.assertRaises(ValueError):
            apply_lane_assistance([0, float('nan'), 0, 30, 80, 0, 0, 1], 0)

    def test_lane_correction_bound_even_for_opposing_model(self):
        steering, correction, _target = apply_lane_assistance([1.5, 15, 10, 30, 80, 0, 0, 0], 1)
        self.assertAlmostEqual(correction, -.16)
        self.assertAlmostEqual(steering, .84)

    def test_conflicting_predictions_can_recover_at_clear_standstill(self):
        # Actual failing log: accelerator .148, brake .929, speed zero.
        features = [0.1, 1., 0., 30., 80., 0., 0., 1.]
        self.assertTrue(is_stall_candidate(0, .148, .929))
        self.assertFalse(apply_stall_recovery(features, .148, .929, 4.9)[2])
        accelerator, brake, active = apply_stall_recovery(features, .148, .929, 5.1)
        self.assertTrue(active)
        self.assertGreater(accelerator, 0)
        self.assertLessEqual(accelerator, .35)
        self.assertEqual(brake, 0)

    def test_conflicting_large_accelerator_stays_bounded(self):
        result = apply_stall_recovery([0, 0, 0, 30, 80, 0, 0, 1], .9, .9, 6)
        self.assertEqual(result, (.35, 0., True))

    def test_measured_green_light_offset_can_restart(self):
        features = [1.025, 4.525, 0, 30, 80, 0, -.126, 1]
        self.assertTrue(apply_stall_recovery(features, .01, .992, 6)[2])
        features[5] = 1
        self.assertFalse(apply_stall_recovery(features, .01, .992, 6)[2])
        features[5], features[0] = 0, 1.21
        self.assertFalse(apply_stall_recovery(features, .01, .992, 6)[2])

    def test_conflicting_outputs_do_not_override_hazards(self):
        for index, value in [(0, 1.5), (1, 20), (2, 5), (4, 5), (5, 1)]:
            features = [0, 0, 0, 30, 80, 0, 0, 1]
            features[index] = value
            with self.subTest(index=index):
                self.assertFalse(apply_stall_recovery(features, .148, .929, 20)[2])

    def test_speed_regulation_before_emergency_cutoff(self):
        self.assertEqual(limit_neural_speed(.8, 0, 20, 30), (.8, 0))
        self.assertLess(limit_neural_speed(.8, 0, 29, 30)[0], .8)
        self.assertEqual(limit_neural_speed(.8, 0, 30, 30), (0, 0))
        accelerator, brake = limit_neural_speed(.8, 0, 33, 30)
        self.assertEqual(accelerator, 0)
        self.assertGreater(brake, 0)
        self.assertEqual(limit_neural_speed(.8, 1, 20, 30), (0, 1))


if __name__ == '__main__':
    unittest.main()
