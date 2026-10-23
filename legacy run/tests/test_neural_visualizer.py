import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from learning.model import (MLP)  # noqa: E402
from telemetry.visualizer import NeuralVisualizer, sanitize_wait  # noqa: E402

PAGE = Path(__file__).resolve().parents[1] / "app" / "telemetry" / "neural_visualizer.html"


def strict_json(raw):
    """Parse like a strict client: NaN and Infinity are not valid JSON."""
    def reject(token):
        raise ValueError("non-finite JSON constant " + token)
    return json.loads(raw, parse_constant=reject)


class NeuralVisualizerTests(unittest.TestCase):
    def test_actual_forward_pass_and_read_only_http(self):
        path = Path('test-policy.json')
        model = MLP([8, 24, 16, 3], seed=7)
        model.visualizer = None
        values = [.1, -.2, .03, .2, 1, 0, -.1, 1]
        expected = model.predict(values)
        visual = NeuralVisualizer(model, path, open_browser=False, save_session=False)
        try:
            model.visualizer = visual
            with urlopen(visual.url + 'state') as response:
                self.assertIsNone(json.load(response)['sample'])
            self.assertEqual(model.predict(values), expected)
            with urlopen(visual.url + 'state') as response:
                state = json.load(response)
            layers = state['sample']['layers']
            self.assertEqual([len(x) for x in layers], [8, 24, 16, 3])
            self.assertEqual(layers[0], values)
            self.assertEqual(layers[-1], expected)
            for i, (weights, biases) in enumerate(zip(model.weights, model.biases)):
                calculated = [sum(w*x for w, x in zip(row, layers[i]))+b
                              for row, b in zip(weights, biases)]
                if i < 2:
                    calculated = [math.tanh(x) for x in calculated]
                self.assertEqual(layers[i+1], calculated)
            self.assertEqual(state['sample']['sequence'], 1)
            visual.publish_runtime({'status': 'SAFETY: red_light', 'route_active': True})
            visual.publish_runtime({'applied': {'brake': 1}})
            with urlopen(visual.url + 'state') as response:
                state = json.load(response)
            self.assertEqual(state['runtime']['status'], 'SAFETY: red_light')
            self.assertEqual(state['runtime']['applied']['brake'], 1)
            with urlopen(visual.url) as response:
                self.assertIn(b'Inside the driving network', response.read())
        finally:
            visual.close()


class SanitizeWaitTests(unittest.TestCase):
    def test_valid_wait_passes_through(self):
        wait = {'kind': 'realign', 'label': 'Re-aligning to route',
                'elapsed_s': 0.7, 'total_s': 2.5}
        self.assertEqual(sanitize_wait(wait), wait)
        self.assertEqual(wait['elapsed_s'], 0.7, 'input must not be mutated')
        for kind in ('start', 'realign', 'exhausted'):
            self.assertEqual(sanitize_wait(dict(wait, kind=kind))['kind'], kind)

    def test_elapsed_is_clamped_into_zero_to_total(self):
        base = {'kind': 'start', 'label': 'Waiting for safe start', 'total_s': 3}
        self.assertEqual(sanitize_wait(dict(base, elapsed_s=9))['elapsed_s'], 3.0)
        self.assertEqual(sanitize_wait(dict(base, elapsed_s=-4))['elapsed_s'], 0.0)
        self.assertEqual(sanitize_wait(dict(base, elapsed_s=1))['elapsed_s'], 1.0)

    def test_label_is_truncated_and_tidied(self):
        base = {'kind': 'start', 'elapsed_s': 1, 'total_s': 3}
        self.assertEqual(sanitize_wait(dict(base, label='a' * 90))['label'], 'a' * 40)
        self.assertEqual(sanitize_wait(dict(base, label='  Re-align\n\tnow  '))['label'],
                         'Re-align now')
        for label in (None, 7, ['x'], {'x': 1}):
            self.assertEqual(sanitize_wait(dict(base, label=label))['label'], '')
        self.assertEqual(sanitize_wait(base)['label'], '')

    def test_unknown_kind_or_shape_clears_the_wait(self):
        good = {'label': 'x', 'elapsed_s': 1, 'total_s': 3}
        for kind in ('bogus', '', 'START', None, 3, ['start']):
            self.assertIsNone(sanitize_wait(dict(good, kind=kind)), kind)
        self.assertIsNone(sanitize_wait(good))
        for value in (None, 'start', 3, [], ('start',), True):
            self.assertIsNone(sanitize_wait(value), value)

    def test_unusable_numbers_are_dropped_but_label_is_kept(self):
        base = {'kind': 'realign', 'label': 'Re-aligning to route'}
        label_only = {'kind': 'realign', 'label': 'Re-aligning to route'}
        bad = [{'elapsed_s': 1, 'total_s': float('inf')},
               {'elapsed_s': 1, 'total_s': float('nan')},
               {'elapsed_s': float('nan'), 'total_s': 3},
               {'elapsed_s': float('-inf'), 'total_s': 3},
               {'elapsed_s': 1, 'total_s': 0},
               {'elapsed_s': 1, 'total_s': -2},
               {'elapsed_s': 1, 'total_s': 0.0004},
               {'elapsed_s': '1', 'total_s': '3'},
               {'elapsed_s': 1, 'total_s': True},
               {'elapsed_s': False, 'total_s': 3},
               {'elapsed_s': None, 'total_s': 3},
               {'total_s': 3},
               {'elapsed_s': 1}]
        for numbers in bad:
            self.assertEqual(sanitize_wait(dict(base, **numbers)), label_only, numbers)

    def test_output_is_strict_json(self):
        wait = sanitize_wait({'kind': 'start', 'label': 'x', 'elapsed_s': 1e308,
                              'total_s': 1e308})
        self.assertEqual(strict_json(json.dumps(wait, allow_nan=False)), wait)


class NeuralVisualizerWaitTests(unittest.TestCase):
    def setUp(self):
        model = MLP([8, 24, 16, 3], seed=7)
        model.visualizer = None
        self.visual = NeuralVisualizer(model, Path('test-policy.json'),
                                       open_browser=False, save_session=False)
        self.addCleanup(self.visual.close)

    def fetch_state(self):
        with urlopen(self.visual.url + 'state') as response:
            raw = response.read()
        for token in (b'NaN', b'Infinity'):
            self.assertNotIn(token, raw)
        return strict_json(raw)

    def test_published_wait_appears_in_state(self):
        self.assertNotIn('wait', self.fetch_state()['runtime'])
        self.visual.publish_runtime({
            'status': 'MODEL REQUESTS STOP · WAITING FOR SAFE START', 'route_active': True,
            'wait': {'kind': 'start', 'label': 'Waiting for safe start',
                     'elapsed_s': 1.25, 'total_s': 4.0}})
        runtime = self.fetch_state()['runtime']
        self.assertEqual(runtime['wait'], {'kind': 'start', 'label': 'Waiting for safe start',
                                           'elapsed_s': 1.25, 'total_s': 4.0})
        self.assertTrue(runtime['route_active'])
        self.assertEqual(runtime['status'], 'MODEL REQUESTS STOP · WAITING FOR SAFE START')

    def test_wait_persists_across_other_updates_and_clears_with_none(self):
        self.visual.publish_runtime({'wait': {'kind': 'realign', 'label': 'Re-aligning to route',
                                              'elapsed_s': 0.5, 'total_s': 2.0}})
        self.visual.publish_runtime({'applied': {'steering': 0.1, 'accelerator': 0.0, 'brake': 1.0}})
        self.assertEqual(self.fetch_state()['runtime']['wait']['kind'], 'realign')
        self.visual.publish_runtime({'wait': None})
        runtime = self.fetch_state()['runtime']
        self.assertIsNone(runtime['wait'])
        self.assertEqual(runtime['applied']['brake'], 1.0)

    def test_exhausted_wait_is_reported_as_label(self):
        self.visual.publish_runtime({'wait': {'kind': 'exhausted', 'label': 'Out of retries'}})
        self.assertEqual(self.fetch_state()['runtime']['wait'],
                         {'kind': 'exhausted', 'label': 'Out of retries'})

    def test_bad_wait_values_are_sanitised_in_state(self):
        self.visual.publish_runtime({'wait': {
            'kind': 'realign', 'label': 'x' * 80,
            'elapsed_s': float('inf'), 'total_s': float('nan')}})
        self.assertEqual(self.fetch_state()['runtime']['wait'],
                         {'kind': 'realign', 'label': 'x' * 40})
        self.visual.publish_runtime({'wait': {
            'kind': 'start', 'label': 'Waiting for safe start',
            'elapsed_s': 99.0, 'total_s': 2.0}})
        self.assertEqual(self.fetch_state()['runtime']['wait']['elapsed_s'], 2.0)
        self.visual.publish_runtime({'wait': {
            'kind': 'start', 'label': 'Waiting for safe start',
            'elapsed_s': -3.0, 'total_s': 2.0}})
        self.assertEqual(self.fetch_state()['runtime']['wait']['elapsed_s'], 0.0)

    def test_unknown_kind_clears_the_previous_wait(self):
        self.visual.publish_runtime({'wait': {'kind': 'start', 'label': 'x',
                                              'elapsed_s': 1, 'total_s': 2}})
        self.visual.publish_runtime({'wait': {'kind': 'teleport', 'label': 'x',
                                              'elapsed_s': 1, 'total_s': 2}})
        self.assertIsNone(self.fetch_state()['runtime']['wait'])

    def test_served_page_has_the_countdown_elements(self):
        with urlopen(self.visual.url) as response:
            page = response.read().decode('utf-8')
        for token in ('id="wait"', 'id="wait-text"', 'id="wait-track"', 'id="wait-fill"',
                      'role="progressbar"'):
            self.assertIn(token, page)


class NeuralPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding='utf-8')
        cls.script = re.search(r'<script>(.*?)</script>', cls.page, re.S).group(1)

    def tag(self, element_id):
        match = re.search(r'<[a-z]+\b[^>]*\bid="' + element_id + r'"[^>]*>', self.page)
        self.assertIsNotNone(match, element_id)
        return match.group(0)

    def test_wait_countdown_markup_is_accessible(self):
        wait = self.tag('wait')
        self.assertIn('class="wait"', wait)
        self.assertRegex(wait, r'\bhidden\b')
        track = self.tag('wait-track')
        for attribute in ('role="progressbar"', 'aria-label="Time left on current wait"',
                          'aria-valuemin="0"', 'aria-valuemax="1"', 'aria-valuenow="0"'):
            self.assertIn(attribute, track)
        self.assertRegex(track, r'\bhidden\b')
        self.tag('wait-text')
        self.tag('wait-fill')

    def test_wait_sits_in_the_runtime_status_block(self):
        order = ['class="runtime-text"', 'id="driving"', 'id="assistance"', 'id="wait"',
                 'id="wait-text"', 'id="wait-track"', 'id="wait-fill"',
                 'class="source-switch"']
        positions = [self.page.index(token) for token in order]
        self.assertEqual(positions, sorted(positions))

    def test_wait_uses_page_tokens_and_no_transition(self):
        styles = re.search(r'<style>(.*?)</style>', self.page, re.S).group(1)
        rules = ''.join(re.findall(r'\.wait[^{}]*\{[^{}]*\}', styles))
        self.assertIn('.wait-fill{', rules)
        self.assertIn('color:var(--yellow)', rules)
        self.assertIn('background:var(--yellow)', rules)
        self.assertNotIn('transition', rules)
        self.assertIn('@media(prefers-reduced-motion:reduce)', self.page)
        self.assertIn('transition:none!important', self.page)
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)')", self.script)

    def test_wait_reuses_the_existing_stale_and_disconnect_handling(self):
        # The countdown is shown only while the page's own live test passes.
        self.assertIn('waitLive=isLive;renderWait()', self.script)
        self.assertIn('shown=!!t&&connected&&waitLive', self.script)
        self.assertEqual(self.script.count('trackWait(frame)'), 2)

    def test_existing_layout_is_intact(self):
        for element_id in ('status', 'freeze', 'model', 'architecture', 'network', 'direction',
                           'throttle', 'brake', 'steer', 'driving', 'assistance',
                           'source-applied', 'source-raw', 'history', 'history-empty',
                           'counter', 'detail', 'accessible-values'):
            self.tag(element_id)
        for query in ('(min-width:1450px)', '(max-width:1150px)', '(max-width:820px)',
                      '(max-width:520px)'):
            self.assertIn('@media' + query, self.page)
        self.assertIn('.runtime-strip{', self.page)
        self.assertIn('.runtime-text{', self.page)
        self.assertIn('name="viewport"', self.page)
        self.assertIn('Inside the driving network', self.page)

    def test_page_stays_self_contained(self):
        self.assertNotIn('<link', self.page)
        self.assertNotIn('<script src', self.page)
        self.assertNotIn('@import', self.page)
        self.assertEqual(re.findall(r'(?:src|href)\s*=\s*["\']?(?:https?:)?//', self.page), [])

    @unittest.skipUnless(shutil.which('node'), 'node is not installed')
    def test_script_parses(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'page.js'
            source.write_text(self.script, encoding='utf-8')
            result = subprocess.run([shutil.which('node'), '--check', str(source)],
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
