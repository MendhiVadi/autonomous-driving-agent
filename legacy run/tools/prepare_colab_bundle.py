"""Validate a completed collection and package its real episodes for Colab."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import argparse
import json
import math
from pathlib import Path
import zipfile

from learning.contract import POLICY_CONTRACT_VERSION, INPUT_NAMES


def prepare(manifest_path, output):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    episodes = manifest.get("episodes", [])
    if not manifest.get("finished") or len(episodes) != 12:
        raise ValueError("The bundle requires a finished collection of 12 successful routes.")
    summaries = []
    paths = []
    route_ids = set()
    for episode in episodes:
        path = Path(episode["path"])
        if episode["status"] != "complete" or path.parent.resolve() != manifest_path.parent.resolve():
            raise ValueError(f"Not an accepted episode: {path}")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) < 100:
            raise ValueError(f"Too few samples: {path}")
        route_id = rows[0]["metadata"]["route_id"]
        if route_id in route_ids:
            raise ValueError("Duplicate route ID")
        route_ids.add(route_id)
        previous_distance = 0.0
        red_samples = 0
        lane_departures = 0
        for row in rows:
            features, action, meta = row["observation"], row["action"], row["metadata"]
            values = features + [action[k] for k in ("steering", "accelerator", "brake")]
            if len(features) != len(INPUT_NAMES) or not all(math.isfinite(float(v)) for v in values):
                raise ValueError(f"Invalid numerical sample: {path}")
            if not (-1 <= action["steering"] <= 1 and 0 <= action["accelerator"] <= 1 and 0 <= action["brake"] <= 1):
                raise ValueError(f"Out-of-range action: {path}")
            if (meta.get("source") != "carla_basic_agent" or
                    meta.get("policy_contract_version") != POLICY_CONTRACT_VERSION or
                    meta.get("route_conditioned") is not True or meta.get("route_id") != route_id or
                    meta.get("rendering_enabled") is not False):
                raise ValueError(f"Incompatible or unverified sample: {path}")
            telemetry = row["telemetry"]
            if telemetry.get("collision") or row.get("event"):
                raise ValueError(f"Collision/event in accepted route: {path}")
            distance = telemetry["distance_m"]
            if not math.isfinite(distance) or not 0 <= distance - previous_distance < 5:
                raise ValueError(f"Discontinuous distance (possible spawn snapshot): {path}")
            previous_distance = distance
            red_samples += features[5] > 0
            lane_departures += bool(telemetry.get("lane_departure"))
        summaries.append({"file": path.name, "samples": len(rows),
                          "distance_m": round(previous_distance, 1),
                          "red_light_samples": red_samples, "lane_departure_samples": lane_departures,
                          "map": rows[0]["metadata"]["map"]})
        paths.append(path)
    report = {"validated": True, "contract_version": POLICY_CONTRACT_VERSION,
              "episodes": summaries, "total_samples": sum(s["samples"] for s in summaries),
              "total_distance_m": round(sum(s["distance_m"] for s in summaries), 1),
              "scope": "BasicAgent demonstrations on one small map; no trained-model or unseen-map success claim."}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path = output.with_suffix(".validation.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    instructions = (
        "Extract this archive into My Drive/CARLA so the JSONL files are in CARLA/episodes.\n"
        "Open colab_train_policy.ipynb in Google Colab and run its cells.\n"
        "Use the real-data path, not synthetic smoke-test mode.\n"
        "The notebook separates complete episodes into train, validation and test sets.\n"
        "Model optimization happens in Colab; these files are demonstrations, not trained weights.\n"
        "Evaluate the exported policy on Town04 before using it for a live presentation.\n"
    )
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, f"episodes/{path.name}")
        archive.write(Path(__file__).resolve().parents[1] / "colab_train_policy.ipynb", "colab_train_policy.ipynb")
        archive.writestr("validation.json", json.dumps(report, indent=2))
        archive.writestr("READ_ME.txt", instructions)
    print(json.dumps({"bundle": str(output), "episodes": len(paths), "samples": report["total_samples"],
                      "distance_m": report["total_distance_m"], "validation": str(report_path)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--output", default="exports/CARLA_colab_training.zip")
    args = parser.parse_args()
    prepare(args.manifest, args.output)
