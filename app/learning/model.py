"""JSON inference model for the retained contract-v2 baseline."""
import json
import math
import random
from pathlib import Path

from learning.contract import POLICY_CONTRACT_VERSION, POLICY_SIZES


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class MLP:
    def __init__(self, sizes, seed=7):
        rng = random.Random(seed)
        self.sizes = sizes
        self.weights = []
        self.biases = []
        self.visualizer = None
        for left, right in zip(sizes, sizes[1:]):
            scale = math.sqrt(2.0 / left)
            self.weights.append([[rng.uniform(-scale, scale) for _ in range(left)] for _ in range(right)])
            self.biases.append([0.0] * right)

    def predict(self, values):
        try:
            layer = list(values)
        except TypeError as exc:
            raise ValueError("Policy inputs must be a sequence of finite numbers") from exc
        trace = [layer] if self.visualizer is not None else None
        if len(layer) != self.sizes[0]:
            raise ValueError(f"Expected {self.sizes[0]} policy inputs, got {len(layer)}")
        if not all(_finite_number(value) for value in layer):
            raise ValueError("Policy inputs must be finite numbers, not booleans")
        for index, (weights, biases) in enumerate(zip(self.weights, self.biases)):
            layer = [sum(w * x for w, x in zip(row, layer)) + bias for row, bias in zip(weights, biases)]
            if not all(_finite_number(value) for value in layer):
                raise ValueError(f"Non-finite policy activation at layer {index}")
            if index != len(self.weights) - 1:
                layer = [math.tanh(x) for x in layer]
            if trace is not None:
                trace.append(layer)
        if trace is not None:
            self.visualizer.publish(trace)
        return layer

    def save(self, path):
        Path(path).write_text(json.dumps({"sizes": self.sizes, "weights": self.weights,
                                          "biases": self.biases}, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path, *, require_deployable=False, require_route_conditioned=False):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Policy must be a JSON object: {path}")
        sizes = payload.get("sizes")
        weights = payload.get("weights")
        biases = payload.get("biases")
        metadata = payload.get("training_metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"Policy training_metadata must be an object: {path}")
        if require_deployable and metadata.get("deployable") is not True:
            raise ValueError(f"Policy is not marked deployable: {path}")
        if require_route_conditioned and metadata.get("route_conditioned") is not True:
            raise ValueError(f"Policy is not route-conditioned: {path}")
        artifact_contract = metadata.get("policy_contract_version")
        if type(artifact_contract) is not int or artifact_contract != POLICY_CONTRACT_VERSION:
            raise ValueError(
                f"Policy contract mismatch in {path}: artifact={artifact_contract}, "
                f"runtime={POLICY_CONTRACT_VERSION}"
            )
        if (not isinstance(sizes, list) or len(sizes) < 2 or
                any(type(size) is not int or size <= 0 for size in sizes) or
                not isinstance(weights, list) or not isinstance(biases, list) or
                len(weights) != len(biases) or len(weights) != len(sizes) - 1):
            raise ValueError(f"Invalid policy structure in {path}")
        if sizes != POLICY_SIZES:
            raise ValueError(f"Unsupported policy sizes in {path}: {sizes}; expected {POLICY_SIZES}")
        for index, (layer, layer_biases) in enumerate(zip(weights, biases)):
            if (not isinstance(layer, list) or len(layer) != sizes[index + 1] or
                    not isinstance(layer_biases, list) or len(layer_biases) != sizes[index + 1] or
                    any(not isinstance(row, list) or len(row) != sizes[index] for row in layer)):
                raise ValueError(f"Invalid policy dimensions in {path} at layer {index}")
            values = [value for row in layer for value in row] + list(layer_biases)
            if not all(_finite_number(value) for value in values):
                raise ValueError(f"Invalid policy values in {path} at layer {index}")
        model = cls(sizes)
        model.weights = weights
        model.biases = biases
        import os
        if os.environ.get("CARLA_NEURAL_VISUAL") == "1":
            try:
                from telemetry.visualizer import NeuralVisualizer
                model.visualizer = NeuralVisualizer(model, path)
            except Exception as exc:
                print(f"[neural visual] unavailable: {exc}", flush=True)
        return model


def load_deployable_policy(path, require_route_conditioned=False):
    """Load only a real, explicitly deployable policy artifact."""
    return MLP.load(path, require_deployable=True,
                    require_route_conditioned=require_route_conditioned)
