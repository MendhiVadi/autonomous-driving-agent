"""Draw the trained network and its actual held-out regression results."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import numpy as np

from learning.model import (MLP)
from learning.contract import normalize_features

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'exports/preliminary-network-20260910-150651'
payload = json.loads((OUT / 'nn_policy_preliminary.json').read_text(encoding="utf-8"))
result = json.loads((OUT / 'training_result.json').read_text(encoding="utf-8"))
model = MLP.load(OUT / 'nn_policy_preliminary.json')
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
                     'axes.spines.top': False, 'axes.spines.right': False})

fig, ax = plt.subplots(figsize=(15, 8), facecolor='#f7f9fc')
ax.set_facecolor('#f7f9fc')
xs = [0, 1.7, 3.4, 5.1]
ys = [np.linspace(.84, .16, n) for n in payload['sizes']]
for layer, weights in enumerate(payload['weights']):
    values = np.asarray(weights)
    segments, colors, widths = [], [], []
    for dest, row in enumerate(values):
        for src, weight in enumerate(row):
            segments.append([(xs[layer], ys[layer][src]), (xs[layer+1], ys[layer+1][dest])])
            colors.append('#2563eb' if weight >= 0 else '#db6b34')
            widths.append(.12 + .85 * abs(weight) / np.max(np.abs(values)))
    ax.add_collection(LineCollection(segments, colors=colors, linewidths=widths, alpha=.23))
for x, y in zip(xs, ys):
    ax.scatter([x]*len(y), y, s=100 if len(y) < 10 else 48,
               color='#2563eb', edgecolor='white', linewidth=1.1, zorder=3)
labels = ['Lane offset', 'Heading error', 'Speed', 'Target speed', 'Obstacle distance',
          'Red light', 'Road curvature', 'Stopped state']
for y, label in zip(ys[0], labels):
    ax.text(-.16, y, label, ha='right', va='center', fontsize=11)
for y, label in zip(ys[-1], ['Steering', 'Accelerator', 'Brake']):
    ax.text(5.27, y, label, ha='left', va='center', fontsize=12, weight='bold')
for x, title, detail in zip(xs, ['8 inputs', '24 neurons', '16 neurons', '3 outputs'],
                           ['Normalized road / vehicle state', 'Hidden layer · tanh', 'Hidden layer · tanh', 'Continuous predictions']):
    ax.text(x, .99, title, ha='center', fontsize=16, weight='bold', color='#14243a')
    ax.text(x, .935, detail, ha='center', fontsize=9, color='#526176')
ax.text(2.55, .035, 'Blue connections: positive weights     Orange connections: negative weights\nLine thickness represents the magnitude of each learned weight.',
        ha='center', va='center', fontsize=11, color='#526176')
ax.set_xlim(-1.6, 6.4)
ax.set_ylim(-.04, 1.06)
ax.axis('off')
fig.suptitle('Your trained driving neural network', fontsize=25, weight='bold', x=.5, y=.98, color='#14243a')
fig.text(.5, .91, '667 learned parameters  |  12 real CARLA demonstration routes  |  33 training epochs',
         ha='center', fontsize=12, color='#526176')
fig.text(.5, .025, 'Supervised imitation learning: predicts driving controls from state values. Live driving has not yet been evaluated.',
         ha='center', fontsize=10, color='#526176')
fig.subplots_adjust(top=.83, bottom=.10, left=.04, right=.96)
fig.savefig(OUT / 'neural_network_diagram.png', dpi=170, facecolor=fig.get_facecolor())
fig.savefig(OUT / 'neural_network_diagram.pdf', facecolor=fig.get_facecolor())
plt.close(fig)

actual, predicted = [], []
for name in payload['training_metadata']['test_episodes']:
    for line in (ROOT / 'episodes/expert' / name).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        action = row['action']
        actual.append([action['steering'], action['accelerator'], action['brake']])
        predicted.append(model.predict(normalize_features(row['observation'])))
actual, predicted = np.asarray(actual), np.asarray(predicted)
mae = np.mean(np.abs(predicted-actual), axis=0)
assert len(actual) == 3725
assert abs(np.mean((predicted-actual)**2) - result['metrics']['test_mse']) < 1e-6
fig = plt.figure(figsize=(15, 10), facecolor='white')
grid = fig.add_gridspec(2, 3, height_ratios=[1, 1], hspace=.5, wspace=.33)
for i, name in enumerate(['Steering', 'Accelerator', 'Brake']):
    ax = fig.add_subplot(grid[0, i])
    ax.scatter(actual[:, i], predicted[:, i], s=9, alpha=.18, c='#2563eb', linewidths=0, rasterized=True)
    low = min(actual[:, i].min(), predicted[:, i].min())
    high = max(actual[:, i].max(), predicted[:, i].max())
    pad = (high-low)*.06
    ax.plot([low-pad, high+pad], [low-pad, high+pad], '--', color='#d06b30', lw=1.5, label='Perfect prediction')
    ax.set(xlim=(low-pad, high+pad), ylim=(low-pad, high+pad),
           xlabel='Expert control value', ylabel='Network prediction', title=f'{name} · MAE {mae[i]:.3f}')
    ax.grid(alpha=.15)
    if i == 0:
        ax.legend(fontsize=9, loc='upper left')
ax = fig.add_subplot(grid[1, :2])
history = np.asarray(result['history'])
epochs = np.arange(1, len(history)+1)
ax.plot(epochs, history[:, 0], color='#2563eb', lw=2, label='Training routes')
ax.plot(epochs, history[:, 1], color='#d06b30', lw=2, label='Validation routes')
ax.set(xlabel='Training epoch', ylabel='Mean squared error (lower is better)', title='Learning curve: error falls as the network learns')
ax.grid(alpha=.15)
ax.legend()
ax = fig.add_subplot(grid[1, 2])
ax.axis('off')
ax.text(0, .98, 'What this shows', fontsize=17, weight='bold', va='top', color='#14243a')
ax.text(0, .83, 'Each dot is a real test sample.\nCloser to the dashed line means\na closer match to the expert.\n\n3,725 held-out test samples\n2 routes unseen during training\n\nTest MSE: 0.015713\n\nOutputs are continuous controls.\nThis is nonlinear regression\nusing a neural network.', va='top', fontsize=12, linespacing=1.6, color='#35465c')
fig.suptitle('Actual results from your trained network', fontsize=25, weight='bold', y=.97, color='#14243a')
fig.text(.5, .925, '8 training routes  /  2 validation routes  /  2 test routes · Raw predictions shown without clipping', ha='center', fontsize=12, color='#526176')
fig.subplots_adjust(top=.84, bottom=.09, left=.075, right=.97)
fig.text(.5, .025, 'Recorded-data evaluation, not a live CARLA driving demonstration.', ha='center', fontsize=11, color='#526176')
fig.savefig(OUT / 'regression_results.png', dpi=160)
fig.savefig(OUT / 'regression_results.pdf')
plt.close(fig)
print(json.dumps({'samples': len(actual), 'test_mse_verified': float(np.mean((predicted-actual)**2)), 'figures': str(OUT)}))
