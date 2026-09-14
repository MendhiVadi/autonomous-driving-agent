"""Read-only acceptance check against a running practice visualizer and car."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import json
import math
import time
from pathlib import Path
from urllib.request import urlopen

import carla

root = Path(__file__).resolve().parents[1]
deadline = time.monotonic() + 420
samples = []
url = None
client = carla.Client('127.0.0.1', 2000)
client.set_timeout(2)
while time.monotonic() < deadline:
    try:
        current = json.loads((root / 'logs/neural-visual.json').read_text(encoding="utf-8"))['url']
        with urlopen(current + 'state', timeout=2) as response:
            state = json.load(response)
        url = current
    except (OSError, ValueError):
        if samples:
            break
        time.sleep(1)
        continue
    sample = state.get('sample')
    if sample:
        layers = sample['layers']
        assert [len(layer) for layer in layers] == [8, 24, 16, 3]
        assert all(math.isfinite(value) for layer in layers for value in layer)
        if samples:
            assert sample['sequence'] >= samples[-1]['sequence']
        record = dict(sequence=sample['sequence'], age=state['now']-sample['time'],
                      runtime=state['runtime'], layers=layers)
        if len(samples) % 10 == 0:
            world = client.get_world()
            vehicle = next(iter(world.get_actors().filter('vehicle.*')), None)
            if vehicle:
                loc = vehicle.get_location()
                record['location'] = [loc.x, loc.y, loc.z]
                light = vehicle.get_traffic_light()
                record['traffic_light'] = None if light is None else {
                    'id': light.id, 'state': str(light.get_state()),
                    'elapsed': light.get_elapsed_time(), 'frozen': light.is_frozen(),
                    'green_seconds': light.get_green_time(),
                    'red_seconds': light.get_red_time(),
                }
            print(json.dumps({k: v for k, v in record.items() if k != 'layers'}), flush=True)
        samples.append(record)
    time.sleep(1)
report = root / 'logs' / ('neural-visual-validation-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
report.write_text(json.dumps({'url': url, 'samples': samples}, indent=2), encoding='utf-8')
print(f'Validated {len(samples)} samples; report: {report}', flush=True)
if not samples:
    raise SystemExit('No live inference received')
