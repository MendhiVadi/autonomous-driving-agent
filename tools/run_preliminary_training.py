"""Run the Colab training cells locally and preserve a school-demo result."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import base64
import contextlib
from datetime import datetime
import io
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import nbformat
import torch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ.pop("CARLA_SMOKE_TEST", None)
torch.set_num_threads(2)
OUTPUT = ROOT / "exports" / ("preliminary-network-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
OUTPUT.mkdir(parents=True, exist_ok=False)
notebook = nbformat.read(ROOT / "colab_train_policy.ipynb", as_version=4)
namespace = {"__name__": "__main__"}
count = 0
for cell in notebook.cells:
    if cell.cell_type != "code":
        continue
    count += 1
    if "drive.mount(" in cell.source:
        cell.source = (f"DATA_DIR = Path({str(ROOT / 'episodes/expert')!r})\n"
                       f"OUTPUT_DIR = Path({str(OUTPUT)!r})\n"
                       "print({'data_dir': str(DATA_DIR), 'output_dir': str(OUTPUT_DIR)})")
    if "artifact_path = OUTPUT_DIR / filename" in cell.source:
        cell.source = cell.source.replace("artifact_path = OUTPUT_DIR / filename",
                                          "artifact_path = OUTPUT_DIR / 'nn_policy_preliminary.json'")
    stream = io.StringIO()
    print(f"Running training cell {count}/9", flush=True)
    with contextlib.redirect_stdout(stream):
        exec(compile(cell.source, f"notebook-cell-{count}", "exec"), namespace)
    cell.execution_count = count
    cell.outputs = [nbformat.v4.new_output("stream", name="stdout", text=stream.getvalue())]
    print(stream.getvalue(), end="", flush=True)
    if "plt.figure(" in cell.source:
        plot = OUTPUT / "learning_curve.png"
        plt.gcf().savefig(plot, dpi=160, bbox_inches="tight")
        cell.outputs.append(nbformat.v4.new_output("display_data", data={
            "image/png": base64.b64encode(plot.read_bytes()).decode("ascii")}, metadata={}))
        plt.close("all")
    nbformat.write(notebook, OUTPUT / "trained_network.ipynb")
result = {"training_location": "local CPU", "synthetic": namespace["SMOKE_TEST"],
          "architecture": namespace["POLICY_SIZES"], "epochs": len(namespace["history"]),
          "best_validation_mse": namespace["best_validation"],
          "samples": [len(namespace[key]) for key in ("x_train", "x_validation", "x_test")],
          "metrics": namespace["metrics"], "history": namespace["history"],
          "artifact": str(namespace["artifact_path"]), "closed_loop_evaluated": False}
(OUTPUT / "training_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print("TRAINING COMPLETE: " + str(OUTPUT), flush=True)
