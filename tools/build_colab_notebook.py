"""Build the Google Colab imitation-learning notebook with nbformat.

The normalization contract embedded in the notebook is generated directly
from ``policy_contract.py`` (owned separately) so the notebook can never
drift from the live policy's input contract. Run this script whenever
``policy_contract.py`` changes to re-embed the current contract.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import inspect
from pathlib import Path

import nbformat as nbf

import learning.contract as policy_contract
CLAMP_SOURCE = inspect.getsource(policy_contract.clamp)
NORMALIZE_SOURCE = inspect.getsource(policy_contract.normalize_features)
POLICY_SIZES = list(policy_contract.POLICY_SIZES)
POLICY_CONTRACT_VERSION = policy_contract.POLICY_CONTRACT_VERSION
INPUT_NAMES = list(policy_contract.INPUT_NAMES)

notebook = nbf.v4.new_notebook()
notebook["metadata"] = {
    "colab": {"name": "CARLA Colab Policy Training", "provenance": []},
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}

cells = []
cells.append(nbf.v4.new_markdown_cell(
    f"# CARLA state-policy training\n\n"
    f"Train the project's **{' → '.join(map(str, POLICY_SIZES))}** driving policy from "
    "route-separated CARLA expert demonstrations. The notebook exports JSON weights that "
    "`neural_drive_agent.py` can load directly.\n\n"
    f"Policy contract version: `{POLICY_CONTRACT_VERSION}` (generated from `policy_contract.py`)."
))
cells.append(nbf.v4.new_markdown_cell(
    "## Goal\n\n"
    "1. Load JSONL episodes recorded by `collect_expert_data.py`.\n"
    "2. Keep complete routes in separate train, validation, and test sets.\n"
    "3. Train steering, accelerator, and brake with supervised imitation learning.\n"
    "4. Export a policy artifact for closed-loop CARLA evaluation.\n\n"
    "> Real CARLA episodes are required by default. A synthetic smoke test only runs when "
    "`CARLA_SMOKE_TEST=1` is set explicitly, and its artifact is never deployable."
))
cells.append(nbf.v4.new_markdown_cell("## Setup"))
cells.append(nbf.v4.new_code_cell(
    "import importlib.util\n"
    "import subprocess\n"
    "import sys as _sys\n\n"
    "REQUIRED_PACKAGES = ['numpy', 'torch', 'matplotlib']\n"
    "missing_packages = [pkg for pkg in REQUIRED_PACKAGES if importlib.util.find_spec(pkg) is None]\n"
    "if missing_packages:\n"
    "    print(f'Installing missing packages: {missing_packages}')\n"
    "    subprocess.check_call([_sys.executable, '-m', 'pip', 'install', '-q', *missing_packages])\n"
    "else:\n"
    "    print('All required packages already available; skipping installation.')"
))
cells.append(nbf.v4.new_code_cell(
    "import os\n"
    "from pathlib import Path\n"
    "import json, math, random, tempfile\n"
    "import numpy as np\n"
    "import torch\n"
    "from torch import nn\n"
    "from torch.utils.data import DataLoader, TensorDataset\n"
    "import matplotlib.pyplot as plt\n\n"
    "SEED = 7\n"
    "# GPU is opt-in: this MLP is tiny enough that host<->device transfer overhead\n"
    "# usually outweighs any GPU speedup. Set ALLOW_GPU=1 to explicitly request CUDA.\n"
    "ALLOW_GPU = os.environ.get('ALLOW_GPU', '0') == '1'\n"
    "DEVICE = torch.device('cuda' if (ALLOW_GPU and torch.cuda.is_available()) else 'cpu')\n"
    "random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED)\n"
    "if DEVICE.type == 'cuda':\n"
    "    torch.cuda.manual_seed_all(SEED)\n"
    "IN_COLAB = 'google.colab' in __import__('sys').modules\n"
    "print({'device': str(DEVICE), 'torch': torch.__version__, 'in_colab': IN_COLAB,\n"
    "       'policy_contract_version': " + repr(POLICY_CONTRACT_VERSION) + "})"
))
cells.append(nbf.v4.new_markdown_cell(
    "### Data location\n\n"
    "In Colab, place the `.jsonl` episode files in `MyDrive/CARLA/episodes`. "
    "The mount prompt is a Google authentication step and must be completed by you."
))
cells.append(nbf.v4.new_code_cell(
    "if IN_COLAB:\n"
    "    from google.colab import drive\n"
    "    drive.mount('/content/drive')\n"
    "    DATA_DIR = Path('/content/drive/MyDrive/CARLA/episodes')\n"
    "    OUTPUT_DIR = Path('/content/drive/MyDrive/CARLA/models')\n"
    "else:\n"
    "    DATA_DIR = Path('episodes/expert')\n"
    "    OUTPUT_DIR = Path('colab_artifacts')\n"
    "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n"
    "print({'data_dir': str(DATA_DIR), 'output_dir': str(OUTPUT_DIR)})"
))
cells.append(nbf.v4.new_markdown_cell("## Steps"))
cells.append(nbf.v4.new_markdown_cell(
    "### 1. Normalize the eight live-policy inputs\n\n"
    "`clamp`/`normalize_features` below are generated verbatim from `policy_contract.py` "
    "(the single source of truth shared with `neural_drive_agent.py`) so this notebook "
    "cannot silently drift from the deployed policy's input contract."
))
cells.append(nbf.v4.new_code_cell(
    "import math\n\n"
    f"POLICY_CONTRACT_VERSION = {POLICY_CONTRACT_VERSION!r}\n"
    f"POLICY_SIZES = {POLICY_SIZES!r}\n"
    f"INPUT_NAMES = {tuple(INPUT_NAMES)!r}\n\n"
    f"{CLAMP_SOURCE}\n"
    f"{NORMALIZE_SOURCE}\n"
    "normalize_observation = normalize_features  # notebook-local alias\n\n"
    "def teacher_action(values):\n"
    "    \"\"\"Rule-based expert used only to label synthetic smoke-test data.\"\"\"\n"
    "    lane, heading, speed, target, obstacle, red, curvature, stopped = values\n"
    "    steering = clamp(-0.18 * lane - 0.035 * heading - 0.55 * curvature, -1, 1)\n"
    "    desired = min(target, max(0.0, obstacle - 8.0) * 2.0)\n"
    "    accelerator = clamp((desired - speed) / 25.0, 0, 1)\n"
    "    brake = 1.0 if red > 0.7 or obstacle < 7.0 else clamp((speed - desired) / 12.0, 0, 1)\n"
    "    return [steering, 0.0 if stopped else accelerator, brake]"
))
cells.append(nbf.v4.new_markdown_cell(
    "### 2. Load and validate complete episodes\n\n"
    "Real CARLA episodes are required by default. Set the environment variable "
    "`CARLA_SMOKE_TEST=1` to explicitly opt into a synthetic, non-deployable smoke test "
    "when no real data is available yet."
))
cells.append(nbf.v4.new_code_cell(
    "MINIMUM_REAL_EPISODES = 10\n"
    "MINIMUM_SPLIT_EPISODES = 6  # smallest episode count that can yield >=2/2/2 train/val/test\n\n"
    "real_episode_files = sorted(DATA_DIR.rglob('*.jsonl')) if DATA_DIR.exists() else []\n"
    "SMOKE_TEST_REQUESTED = os.environ.get('CARLA_SMOKE_TEST') == '1'\n\n"
    "if real_episode_files:\n"
    "    episode_files = real_episode_files\n"
    "    SMOKE_TEST = False\n"
    "    print(f'Using {len(episode_files)} real CARLA expert episode files.')\n"
    "elif SMOKE_TEST_REQUESTED:\n"
    "    SMOKE_TEST = True\n"
    "    smoke_dir = Path(tempfile.gettempdir()) / 'carla_colab_smoke_episodes'\n"
    "    smoke_dir.mkdir(parents=True, exist_ok=True)\n"
    "    for old in smoke_dir.glob('*.jsonl'): old.unlink()\n"
    "    rng = random.Random(SEED)\n"
    "    for episode_index in range(9):\n"
    "        path = smoke_dir / f'smoke-{episode_index:02d}.jsonl'\n"
    "        with path.open('w', encoding='utf-8') as handle:\n"
    "            for _ in range(240):\n"
    "                obs = [rng.uniform(-4,4), rng.uniform(-35,35), rng.uniform(0,70),\n"
    "                       rng.uniform(20,50), rng.uniform(3,80), rng.choice([0,0,0,1]),\n"
    "                       rng.uniform(-0.5,0.5), rng.choice([0,0,1])]\n"
    "                steer, accel, brake = teacher_action(obs)\n"
    "                row = {'observation': obs, 'action': {'steering': steer,\n"
    "                       'accelerator': accel, 'brake': brake},\n"
    "                       'metadata': {'source': 'synthetic_smoke_test'}}\n"
    "                handle.write(json.dumps(row) + '\\n')\n"
    "    episode_files = sorted(smoke_dir.glob('*.jsonl'))\n"
    "    print('WARNING: CARLA_SMOKE_TEST=1 was set; using synthetic smoke-test data. '\n"
    "          'The exported artifact will be explicitly marked non-deployable.')\n"
    "else:\n"
    "    raise RuntimeError(\n"
    "        f'No .jsonl episodes found under {DATA_DIR}. Record real CARLA expert data with '\n"
    "        \"collect_expert_data.py, or set CARLA_SMOKE_TEST=1 to explicitly run a \"\n"
    "        'non-deployable synthetic smoke test instead.'\n"
    "    )\n\n"
    "episodes = {}\n"
    "rejected_rows = 0\n"
    "for path in episode_files:\n"
    "    rows = []\n"
    "    for line in path.read_text(encoding='utf-8').splitlines():\n"
    "        try:\n"
    "            row = json.loads(line)\n"
    "            obs, action = row['observation'], row['action']\n"
    "            metadata = row.get('metadata') or {}\n"
    "            if not SMOKE_TEST and (metadata.get('route_conditioned') is not True or\n"
    "                    metadata.get('policy_contract_version') != POLICY_CONTRACT_VERSION):\n"
    "                raise ValueError\n"
    "            steering = action.get('steering', action.get('steer'))\n"
    "            if steering is None and 'steering_angle_deg' in action:\n"
    "                steering = float(action['steering_angle_deg']) / 70.0\n"
    "            target = [steering, action.get('accelerator', action.get('throttle')), action['brake']]\n"
    "            if len(obs) != POLICY_SIZES[0]: raise ValueError\n"
    "            values = list(map(float, obs)) + list(map(float, target))\n"
    "            if not all(math.isfinite(v) for v in values): raise ValueError\n"
    "            rows.append((normalize_observation(obs), target))\n"
    "        except (KeyError, TypeError, ValueError, json.JSONDecodeError):\n"
    "            rejected_rows += 1\n"
    "    if rows: episodes[path.name] = rows\n\n"
    "if SMOKE_TEST:\n"
    "    assert len(episodes) >= MINIMUM_SPLIT_EPISODES, (\n"
    "        f'Smoke test produced only {len(episodes)} non-empty episodes; '\n"
    "        f'need at least {MINIMUM_SPLIT_EPISODES}.'\n"
    "    )\n"
    "else:\n"
    "    assert len(episodes) >= MINIMUM_REAL_EPISODES, (\n"
    "        f'Only {len(episodes)} non-empty real episodes were found under {DATA_DIR}; '\n"
    "        f'at least {MINIMUM_REAL_EPISODES} are required before training.'\n"
    "    )\n"
    "print({'episodes': len(episodes), 'samples': sum(map(len, episodes.values())),\n"
    "       'rejected_rows': rejected_rows, 'smoke_test': SMOKE_TEST})"
))
cells.append(nbf.v4.new_markdown_cell("### 3. Split by route, never by individual frame"))
cells.append(nbf.v4.new_code_cell(
    "episode_names = sorted(episodes)\n"
    "random.Random(SEED).shuffle(episode_names)\n"
    "MIN_PER_SPLIT = 2\n"
    "test_count = max(MIN_PER_SPLIT, round(len(episode_names) * 0.15))\n"
    "validation_count = max(MIN_PER_SPLIT, round(len(episode_names) * 0.15))\n"
    "test_names = episode_names[:test_count]\n"
    "validation_names = episode_names[test_count:test_count + validation_count]\n"
    "train_names = episode_names[test_count + validation_count:]\n"
    "assert len(train_names) >= MIN_PER_SPLIT, (\n"
    "    f'Only {len(train_names)} training episodes remain after the split; '\n"
    "    f'need at least {MIN_PER_SPLIT}. Record more episodes.'\n"
    ")\n"
    "assert len(validation_names) >= MIN_PER_SPLIT and len(test_names) >= MIN_PER_SPLIT\n"
    "assert set(train_names).isdisjoint(validation_names + test_names)\n"
    "assert set(validation_names).isdisjoint(test_names)\n\n"
    "def stack(names):\n"
    "    pairs = [pair for name in names for pair in episodes[name]]\n"
    "    x = torch.tensor([pair[0] for pair in pairs], dtype=torch.float32)\n"
    "    y = torch.tensor([pair[1] for pair in pairs], dtype=torch.float32)\n"
    "    return x, y\n\n"
    "x_train, y_train = stack(train_names)\n"
    "x_validation, y_validation = stack(validation_names)\n"
    "x_test, y_test = stack(test_names)\n"
    "# Move the static validation/test tensors to DEVICE once; the training loop and\n"
    "# the final evaluation cell reuse these instead of re-transferring every epoch.\n"
    "x_validation_device = x_validation.to(DEVICE)\n"
    "y_validation_device = y_validation.to(DEVICE)\n"
    "x_test_device = x_test.to(DEVICE)\n"
    "y_test_device = y_test.to(DEVICE)\n"
    "print({'train_episodes': train_names, 'validation_episodes': validation_names,\n"
    "       'test_episodes': test_names, 'samples': [len(x_train), len(x_validation), len(x_test)]})"
))
cells.append(nbf.v4.new_markdown_cell("### 4. Train the MLP"))
cells.append(nbf.v4.new_code_cell(
    f"model = nn.Sequential(nn.Linear({POLICY_SIZES[0]}, {POLICY_SIZES[1]}), nn.Tanh(), "
    f"nn.Linear({POLICY_SIZES[1]}, {POLICY_SIZES[2]}), nn.Tanh(), "
    f"nn.Linear({POLICY_SIZES[2]}, {POLICY_SIZES[3]})).to(DEVICE)\n"
    "optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)\n"
    "loss_fn = nn.MSELoss()\n"
    "loader = DataLoader(TensorDataset(x_train, y_train), batch_size=128, shuffle=True,\n"
    "                    generator=torch.Generator().manual_seed(SEED),\n"
    "                    pin_memory=(DEVICE.type == 'cuda'))\n\n"
    "MAX_EPOCHS = 80\n"
    "PATIENCE = 12\n"
    "MIN_IMPROVEMENT = 1e-5\n\n"
    "history = []\n"
    "best_validation = float('inf')\n"
    "# Seed best_state with the model's own (finite, randomly-initialized) starting\n"
    "# weights so a NaN-from-epoch-zero run never leaves best_state as None.\n"
    "best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}\n"
    "epochs_without_improvement = 0\n"
    "for epoch in range(MAX_EPOCHS):\n"
    "    model.train(); train_total = 0.0\n"
    "    for batch_x, batch_y in loader:\n"
    "        batch_x = batch_x.to(DEVICE, non_blocking=(DEVICE.type == 'cuda'))\n"
    "        batch_y = batch_y.to(DEVICE, non_blocking=(DEVICE.type == 'cuda'))\n"
    "        optimizer.zero_grad(); prediction = model(batch_x)\n"
    "        loss = loss_fn(prediction, batch_y); loss.backward(); optimizer.step()\n"
    "        train_total += loss.item() * len(batch_x)\n"
    "    train_loss = train_total / len(x_train)\n"
    "    if not math.isfinite(train_loss):\n"
    "        raise RuntimeError(f'Training loss became non-finite ({train_loss}) at epoch {epoch}.')\n"
    "    model.eval()\n"
    "    with torch.no_grad():\n"
    "        validation_loss = loss_fn(model(x_validation_device), y_validation_device).item()\n"
    "    if not math.isfinite(validation_loss):\n"
    "        raise RuntimeError(f'Validation loss became non-finite ({validation_loss}) at epoch {epoch}.')\n"
    "    history.append((train_loss, validation_loss))\n"
    "    if validation_loss < best_validation - MIN_IMPROVEMENT:\n"
    "        best_validation = validation_loss\n"
    "        best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}\n"
    "        epochs_without_improvement = 0\n"
    "    else:\n"
    "        epochs_without_improvement += 1\n"
    "        if epochs_without_improvement >= PATIENCE:\n"
    "            print(f'Early stopping at epoch {epoch} (no improvement for {PATIENCE} epochs).')\n"
    "            break\n"
    "model.load_state_dict(best_state)\n"
    "print({'best_validation_mse': best_validation, 'final_train_mse': history[-1][0],\n"
    "       'epochs_run': len(history)})"
))
cells.append(nbf.v4.new_markdown_cell("### 5. Inspect learning and held-out errors"))
cells.append(nbf.v4.new_code_cell(
    "plt.figure(figsize=(7, 3))\n"
    "plt.plot([v[0] for v in history], label='train')\n"
    "plt.plot([v[1] for v in history], label='validation')\n"
    "plt.yscale('log'); plt.xlabel('Epoch'); plt.ylabel('MSE'); plt.title('Imitation-learning loss')\n"
    "plt.legend(); plt.grid(alpha=.25); plt.show()\n\n"
    "model.eval()\n"
    "with torch.no_grad():\n"
    "    test_prediction = model(x_test_device).cpu()\n"
    "mae = torch.mean(torch.abs(test_prediction - y_test), dim=0).numpy()\n"
    "test_mse = torch.mean((test_prediction - y_test) ** 2).item()\n"
    "metrics = {'test_mse': float(test_mse), 'steering_mae': float(mae[0]),\n"
    "           'accelerator_mae': float(mae[1]), 'brake_mae': float(mae[2])}\n"
    "print(metrics)"
))
cells.append(nbf.v4.new_markdown_cell("### 6. Export weights compatible with the local driver"))
cells.append(nbf.v4.new_code_cell(
    "linear_layers = [layer for layer in model if isinstance(layer, nn.Linear)]\n"
    "artifact = {\n"
    "    'sizes': POLICY_SIZES,\n"
    "    'weights': [layer.weight.detach().cpu().tolist() for layer in linear_layers],\n"
    "    'biases': [layer.bias.detach().cpu().tolist() for layer in linear_layers],\n"
    "    'training_metadata': {\n"
    "        'deployable': not SMOKE_TEST, 'source': 'carla_expert_jsonl' if not SMOKE_TEST else 'synthetic_smoke_test',\n"
    "        'seed': SEED, 'policy_contract_version': POLICY_CONTRACT_VERSION,\n"
    "        'route_conditioned': True,\n"
    "        'train_episodes': train_names, 'validation_episodes': validation_names,\n"
    "        'test_episodes': test_names, 'samples': int(len(x_train)+len(x_validation)+len(x_test)),\n"
    "        'metrics': metrics,\n"
    "    },\n"
    "}\n"
    "filename = 'nn_policy_smoke_test.json' if SMOKE_TEST else 'nn_policy_colab.json'\n"
    "artifact_path = OUTPUT_DIR / filename\n"
    "assert artifact_path.name != 'nn_policy.json', 'Refusing to overwrite the live nn_policy.json artifact.'\n"
    "artifact_path.write_text(json.dumps(artifact, indent=2), encoding='utf-8')\n"
    "assert all(np.isfinite(value) for layer in artifact['weights'] for row in layer for value in row)\n"
    "print({'artifact': str(artifact_path), 'deployable': not SMOKE_TEST})"
))
cells.append(nbf.v4.new_markdown_cell(
    "## Checks\n\n"
    "- Train, validation, and test routes are disjoint, with at least two routes each.\n"
    "- At least ten real episodes are required unless `CARLA_SMOKE_TEST=1` is set explicitly.\n"
    "- Invalid rows are counted and excluded.\n"
    "- Normalization is generated from `policy_contract.py`, not duplicated by hand.\n"
    "- The JSON layer sizes match the local pure-Python loader.\n"
    "- Synthetic smoke-test artifacts are explicitly marked non-deployable and are never "
    "written to `nn_policy.json`.\n\n"
    "Offline errors are only a training check. A real policy must still pass closed-loop CARLA evaluation "
    "with the independent safety supervisor enabled."
))
cells.append(nbf.v4.new_markdown_cell(
    "## Next steps\n\n"
    "1. Download `nn_policy_colab.json`.\n"
    "2. Keep the existing `nn_policy.json` as a rollback copy.\n"
    "3. Run the candidate on unseen CARLA routes with `--record-dir`.\n"
    "4. Compare collisions, lane departures, completion, and safety interventions.\n"
    "5. Promote the candidate only after closed-loop acceptance."
))

notebook["cells"] = cells
nbf.write(notebook, Path(__file__).resolve().parents[1] / "colab_train_policy.ipynb")
print("Wrote colab_train_policy.ipynb")
