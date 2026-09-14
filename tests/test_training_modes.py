"""World ownership and failure cleanup for camera-free data collection."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from collect_expert_data import collection_world


class TrainingWorldTests(unittest.TestCase):
    def make_world(self):
        current = SimpleNamespace(synchronous_mode=False, no_rendering_mode=False,
                                  fixed_delta_seconds=None, substepping=False,
                                  max_substep_delta_time=0.01, max_substeps=10)
        world = Mock()
        world.get_settings.side_effect = lambda: copy.deepcopy(current)
        world.get_actors.return_value.filter.return_value = []
        world.apply_settings.side_effect = lambda s: current.__dict__.update(vars(s))
        return world, current

    def test_headless_settings_restore_after_failure(self):
        world, current = self.make_world()
        original = copy.deepcopy(vars(current))
        with self.assertRaisesRegex(RuntimeError, "collection failed"):
            with collection_world(world, Mock(), True):
                self.assertTrue(current.no_rendering_mode)
                self.assertTrue(current.synchronous_mode)
                self.assertEqual(current.fixed_delta_seconds, 0.05)
                raise RuntimeError("collection failed")
        self.assertEqual(vars(current), original)

    def test_refuses_another_tick_owner(self):
        world, current = self.make_world()
        current.synchronous_mode = True
        with self.assertRaisesRegex(RuntimeError, "Another client"):
            with collection_world(world, Mock(), True):
                self.fail("must not enter")
        world.apply_settings.assert_not_called()

    def test_refuses_existing_camera_client(self):
        world, _ = self.make_world()
        world.get_actors.return_value.filter.return_value = [object()]
        with self.assertRaisesRegex(RuntimeError, "camera clients"):
            with collection_world(world, Mock(), True):
                self.fail("must not enter")
        world.apply_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
