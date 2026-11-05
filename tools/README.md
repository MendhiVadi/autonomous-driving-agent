# Tools

| Tool | Purpose |
| --- | --- |
| `verify.py` | Offline regression suite (`tests/`), no simulator needed |
| `train_bootstrap_policy.py` | Regenerates the bundled fallback policy `nn_policy_bootstrap.json` (numpy only) |
| `build_colab_notebook.py` | Regenerates `colab_train_policy.ipynb` from the live input contract |
| `prepare_colab_bundle.py` | Validates a finished expert collection and zips it for Colab |
| `run_preliminary_training.py` | Runs the notebook's training cells locally (torch, matplotlib, nbformat) |
| `render_probe.py` | Bounded CARLA render/camera diagnostic that owns its own server; the DX11/DX12 evidence in `docs/CRASH_DIAGNOSIS.md` came from it |

See `docs/TRAINING.md` for how the training tools fit together.
