"""Regression checks for recording integrity and distinct camera output."""
import json
from pathlib import Path
import tempfile
import unittest

from neural_presentation import (read_recording, assemble, save_json, check_capture_manifest,
                                 VIEWS, FRAME_DIR)


class PresentationTests(unittest.TestCase):
    def test_resume_rejects_changed_trajectory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'trajectory.jsonl').write_text('{"tick":0}\n', encoding="utf-8")
            check_capture_manifest(root)
            check_capture_manifest(root)
            (root / 'trajectory.jsonl').write_text('{"tick":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, 'cached frames'):
                check_capture_manifest(root)

    def test_incomplete_recording_is_not_rendered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_json(root / 'recording.json', {'completed': False})
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                read_recording(root)

    def test_frame_count_and_exact_decimation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_json(root / 'recording.json', {'completed': True, 'ticks': 4})
            (root / 'trajectory.jsonl').write_text('\n'.join(
                json.dumps({'tick': i}) for i in range(4)), encoding="utf-8")
            _, rows = read_recording(root)
            self.assertEqual([r['tick'] for r in rows], [1, 3])
            (root / 'trajectory.jsonl').write_text('{}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, 'frame count'):
                read_recording(root)

    def test_video_has_four_distinct_views_and_rejects_missing_frames(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            colors = [(0, 0, 220), (0, 220, 0), (220, 0, 0), (0, 220, 220)]
            for view, color in zip(VIEWS, colors):
                folder = root / FRAME_DIR / view
                folder.mkdir(parents=True)
                cv2.imwrite(str(folder / '000000.png'), np.full((180, 320, 3), color, np.uint8))
            metadata = {'distance_m': 10, 'stop_reason': 'duration_reached'}
            rows = [{'seconds': 0.1, 'speed_kmh': 15, 'distance_m': 10, 'safety': []}]
            video = assemble(root, metadata, rows)
            reader = cv2.VideoCapture(str(video))
            ok, frame = reader.read()
            reader.release()
            self.assertTrue(ok)
            for j, color in enumerate(colors):
                sample = frame[200+(j//2)*340, 320+(j%2)*640].astype(float)
                self.assertLess(np.max(np.abs(sample-np.array(color))), 15)
            (root / FRAME_DIR / 'right' / '000000.png').unlink()
            with self.assertRaisesRegex(RuntimeError, 'Missing or invalid right'):
                assemble(root, metadata, rows)
            self.assertTrue(video.is_file())  # A failed rebuild preserves the prior video.


if __name__ == '__main__':
    unittest.main()
