"""Train the bundled fallback driving policy from a rule-based teacher.

The neural launchers need a deployable, route-conditioned contract-v2 policy.
The policy trained on real CARLA expert demonstrations (``nn_policy_colab.json``)
is private to the machine that recorded it, so a fresh checkout would otherwise
have nothing to drive with. This script distils a small rule-based teacher
(heading/lane steering, speed holding, red-light and obstacle stops) into the
project's 8-24-16-3 network on synthetic states and writes
``nn_policy_bootstrap.json`` at the repository root.

It is a bootstrap, not the real model: ``config/runtime.json`` lists it after
``nn_policy_colab.json`` and the launcher warns when it is in use.

Run with any Python that has numpy:

    python tools/train_bootstrap_policy.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from learning.contract import POLICY_CONTRACT_VERSION, POLICY_SIZES, normalize_features  # noqa: E402

OUTPUT = ROOT / "nn_policy_bootstrap.json"
SEED = 7
SAMPLES = 120_000
EPOCHS = 60
BATCH = 256
LEARNING_RATE = 2e-3

# Teacher gains. Steering follows CARLA's BasicAgent lateral controller
# (about 1.95 per radian of heading error, i.e. 0.034 per degree) softened a
# little, plus gentle lane centring; positive heading/lane error means the car
# points or sits to the right of the route, which needs negative (left) steering.
STEER_PER_DEG = 0.030
STEER_PER_M = 0.10
STOP_DISTANCE_M = 8.0
MAX_ACCELERATOR = 0.75


def clamp(value, low, high):
    return max(low, min(high, float(value)))


def teacher_action(features):
    """Steering, accelerator and brake a careful rule-based driver would request."""
    lane, heading, speed, target, obstacle, red, _curvature, _stopped = features
    steering = clamp(-STEER_PER_DEG * heading - STEER_PER_M * lane, -1.0, 1.0)
    stop_required = red > 0.5 or obstacle < STOP_DISTANCE_M
    desired = min(target, max(0.0, obstacle - STOP_DISTANCE_M) * 1.5)      # ease off behind traffic
    desired = min(desired, max(10.0, target - 0.6 * max(0.0, abs(heading) - 10.0)))  # slow for turns
    if stop_required:
        return [steering, 0.0, 1.0]
    accelerator = clamp((desired - speed) / 12.0, 0.0, MAX_ACCELERATOR)
    brake = clamp((speed - desired - 2.0) / 8.0, 0.0, 1.0)
    if brake > 0.0:
        accelerator = 0.0
    return [steering, accelerator, brake]


def sample_states(rng, count):
    """Synthetic road states weighted toward normal driving, with enough edge cases."""
    mixed = rng.random(count) < 0.7
    lane = np.where(mixed, rng.normal(0.0, 0.5, count), rng.uniform(-3.5, 3.5, count)).clip(-4.0, 4.0)
    heading = np.where(mixed, rng.normal(0.0, 8.0, count), rng.uniform(-60.0, 60.0, count))
    target = np.where(rng.random(count) < 0.7, 30.0, rng.uniform(15.0, 45.0, count))
    speed_mode = rng.random(count)
    # 20 % standing still, 30 % cruising near the target, the rest anywhere up to 50 km/h.
    speed = np.where(speed_mode < 0.2, 0.0,
                     np.where(speed_mode < 0.5, target + rng.normal(0.0, 4.0, count),
                              rng.uniform(0.0, 50.0, count))).clip(0.0, 60.0)
    obstacle = np.where(rng.random(count) < 0.6, 80.0, rng.uniform(3.0, 60.0, count))
    red = (rng.random(count) < 0.15).astype(float)
    curvature = np.where(rng.random(count) < 0.7, rng.normal(0.0, 0.15, count), rng.uniform(-1.0, 1.0, count)).clip(-1.0, 1.0)
    stopped = (speed < 1.0).astype(float)
    return np.column_stack([lane, heading, speed, target, obstacle, red, curvature, stopped])


class Network:
    """The same 8-24-16-3 tanh network the runtime loads, with Adam training."""

    def __init__(self, sizes, rng):
        self.sizes = list(sizes)
        self.weights = [rng.normal(0.0, np.sqrt(1.0 / left), (right, left)) for left, right in zip(sizes, sizes[1:])]
        self.biases = [np.zeros(right) for right in sizes[1:]]
        self.moments = [(np.zeros_like(w), np.zeros_like(w), np.zeros_like(b), np.zeros_like(b))
                        for w, b in zip(self.weights, self.biases)]
        self.step = 0

    def forward(self, x):
        activations = [x]
        for index, (w, b) in enumerate(zip(self.weights, self.biases)):
            z = activations[-1] @ w.T + b
            activations.append(np.tanh(z) if index < len(self.weights) - 1 else z)
        return activations

    def train_batch(self, x, y, lr, beta1=0.9, beta2=0.999, eps=1e-8, weight_decay=1e-5):
        activations = self.forward(x)
        delta = 2.0 * (activations[-1] - y) / len(x)
        self.step += 1
        for index in range(len(self.weights) - 1, -1, -1):
            grad_w = delta.T @ activations[index] + weight_decay * self.weights[index]
            grad_b = delta.sum(axis=0)
            if index > 0:
                delta = (delta @ self.weights[index]) * (1.0 - activations[index] ** 2)
            m_w, v_w, m_b, v_b = self.moments[index]
            m_w[:] = beta1 * m_w + (1 - beta1) * grad_w
            v_w[:] = beta2 * v_w + (1 - beta2) * grad_w ** 2
            m_b[:] = beta1 * m_b + (1 - beta1) * grad_b
            v_b[:] = beta2 * v_b + (1 - beta2) * grad_b ** 2
            correction1, correction2 = 1 - beta1 ** self.step, 1 - beta2 ** self.step
            self.weights[index] -= lr * (m_w / correction1) / (np.sqrt(v_w / correction2) + eps)
            self.biases[index] -= lr * (m_b / correction1) / (np.sqrt(v_b / correction2) + eps)
        return float(np.mean((activations[-1] - y) ** 2))


def main():
    rng = np.random.default_rng(SEED)
    states = sample_states(rng, SAMPLES)
    inputs = np.array([normalize_features(list(map(float, row))) for row in states])
    targets = np.array([teacher_action(list(map(float, row))) for row in states])
    split = int(0.9 * SAMPLES)
    x_train, y_train = inputs[:split], targets[:split]
    x_test, y_test = inputs[split:], targets[split:]

    network = Network(POLICY_SIZES, rng)
    started = time.monotonic()
    for epoch in range(EPOCHS):
        order = rng.permutation(len(x_train))
        lr = LEARNING_RATE * (0.5 * (1 + np.cos(np.pi * epoch / EPOCHS)))  # cosine decay
        losses = [network.train_batch(x_train[batch], y_train[batch], lr)
                  for batch in np.array_split(order, max(1, len(order) // BATCH))]
        if epoch % 10 == 0 or epoch == EPOCHS - 1:
            test_prediction = network.forward(x_test)[-1]
            print(f"epoch {epoch:3d}  train mse {np.mean(losses):.5f}  "
                  f"test mse {np.mean((test_prediction - y_test) ** 2):.5f}", flush=True)
    test_prediction = network.forward(x_test)[-1]
    mae = np.abs(test_prediction - y_test).mean(axis=0)
    metrics = {"test_mse": float(np.mean((test_prediction - y_test) ** 2)),
               "steering_mae": float(mae[0]), "accelerator_mae": float(mae[1]), "brake_mae": float(mae[2])}
    artifact = {
        "sizes": POLICY_SIZES,
        "weights": [w.tolist() for w in network.weights],
        "biases": [b.tolist() for b in network.biases],
        "training_metadata": {
            "deployable": True,
            "route_conditioned": True,
            "policy_contract_version": POLICY_CONTRACT_VERSION,
            "source": "synthetic_bootstrap_teacher",
            "note": ("Fallback policy distilled from a rule-based teacher on synthetic states so the "
                     "neural launchers run on a fresh machine. A policy trained on real CARLA expert "
                     "demonstrations (nn_policy_colab.json) takes precedence when present."),
            "teacher": {"steer_per_deg": STEER_PER_DEG, "steer_per_m": STEER_PER_M,
                        "stop_distance_m": STOP_DISTANCE_M, "max_accelerator": MAX_ACCELERATOR},
            "seed": SEED, "samples": SAMPLES, "epochs": EPOCHS,
            "metrics": metrics,
            "trainer": "tools/train_bootstrap_policy.py",
        },
    }
    assert all(np.isfinite(value) for layer in artifact["weights"] for row in layer for value in row)
    OUTPUT.write_text(json.dumps(artifact, indent=1), encoding="utf-8")
    print(json.dumps({"artifact": str(OUTPUT), "seconds": round(time.monotonic() - started, 1), **metrics}))


if __name__ == "__main__":
    main()
