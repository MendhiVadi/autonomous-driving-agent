# Maintenance tools

| Workflow | Tools |
| --- | --- |
| Offline regression suite | verify.py |
| Existing imitation-learning notebook and data | build_colab_notebook.py, prepare_colab_bundle.py, run_preliminary_training.py |
| Architecture illustrations | make_network_figures.py |
| Explicit live diagnostics | validate_input_environment.py, validate_cockpit_runtime.py, validate_neural_visual_live.py |

Live diagnostic tools may start or connect to CARLA. They are separate from
the offline regression suite. The notebook trains the retained imitation
baseline; none of these commands starts the new RL training effort.
