# Training the driving network

The network drives from eight state inputs and produces steering, accelerator
and brake (`app/learning/contract.py`, contract version 2). Training is
imitation learning on demonstrations recorded in CARLA by this project. All
commands below run from the repository root with CARLA installed and the
Python environment created (`scripts\setup_environment.ps1`).

## 1. Record expert demonstrations

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 -Mode expert
```

This starts a camera-free CARLA server on Town02_Opt and lets CARLA's
`BasicAgent` drive twelve routes of at least 150 m while the same observations
the live cockpit uses are recorded with the agent's controls. Each accepted
route becomes `episodes\expert\expert-*.jsonl`; a manifest
`episodes\expert\collection-<id>.json` lists them. Routes that collide or time
out stay in `episodes\expert_pending` and are not used.

Options: `-Episodes 20`, `-MaxTicks 3000`, `-Map Town05`, `-OutputDir episodes\town05`.

## 2. Optional: record your own driving

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch.ps1 -Mode human-demo
```

The map cockpit opens. Click a road at least 150 m away and drive the green
route yourself; reaching the destination saves a `human-*.jsonl` episode, a
collision discards it. The notebook accepts these alongside expert episodes.

## 3. Bundle and validate

```powershell
& "$env:CARLA_ROOT\carla_env\Scripts\python.exe" tools\prepare_colab_bundle.py episodes\expert\collection-<id>.json
```

This checks every sample (finite values, contract version, route separation,
no collisions) and writes `exports\CARLA_colab_training.zip` with the episodes,
the notebook and a validation report.

## 4. Train in Google Colab

Extract the ZIP into *My Drive/CARLA* so the episodes are in
`CARLA/episodes`, open `colab_train_policy.ipynb` in Colab and run all cells.
The notebook splits complete routes into train, validation and test sets,
trains the 8-24-16-3 network and writes `CARLA/models/nn_policy_colab.json`
with `deployable: true` and `route_conditioned: true` metadata. Synthetic
smoke-test runs (`CARLA_SMOKE_TEST=1`) are marked non-deployable and the
launcher refuses them.

Local alternative without Colab (needs `pip install -r requirements\colab.txt
-r requirements\notebook.txt`, i.e. torch, matplotlib, nbformat):

```powershell
& "$env:CARLA_ROOT\carla_env\Scripts\python.exe" tools\run_preliminary_training.py
```

It writes `exports\preliminary-network-<stamp>\nn_policy_preliminary.json`.

## 5. Install the model

Copy the exported file to the repository root as `nn_policy_colab.json`. The
launcher validates it before CARLA starts and prints `Neural policy: ...` with
the path it loaded. Commit the file so it survives a reinstall.

## The bootstrap policy

`nn_policy_bootstrap.json` exists so the neural launchers work on a machine
that has no trained model yet. `tools\train_bootstrap_policy.py` distils a
rule-based teacher (heading and lane steering, speed holding, red-light and
obstacle stops) into the same network on synthetic states; it has never seen
CARLA data. `tests\test_bootstrap_policy.py` drives it through the cockpit's
assistance chain on a kinematic car as a sanity check. Regenerate it with:

```powershell
& "$env:CARLA_ROOT\carla_env\Scripts\python.exe" tools\train_bootstrap_policy.py
```

## Judging a model

Offline losses only show that the network imitates its teacher. Judge a
candidate in closed loop: drive several unseen routes with `run_neural.cmd`
and compare completions, collisions, lane departures and how often the status
line reports a safety intervention. The safety supervisor can hide a weak
policy, so count its interventions, not just arrivals.
