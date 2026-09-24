import json
import math
import unittest
from pathlib import Path
from urllib.request import urlopen

from learning.model import (MLP)
from telemetry.visualizer import NeuralVisualizer


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


if __name__ == '__main__':
    unittest.main()
