"""Receive local gesture intent scores and convert them to safe policy nudges."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import socket
import threading
import time


GESTURE_BIAS_CAP = 0.15


def _bounded(value, low=0.0, high=GESTURE_BIAS_CAP):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return max(low, min(high, float(value)))


@dataclass(frozen=True)
class PolicyOutputBias:
    """Small deltas applied to one neural-policy output decision."""

    steering: float = 0.0
    accelerator: float = 0.0
    brake: float = 0.0
    active: bool = False

    def as_dict(self):
        return {key: round(value, 4) if isinstance(value, float) else value
                for key, value in asdict(self).items()}


def policy_bias_from_payload(payload, cap=GESTURE_BIAS_CAP):
    """Map independent gesture intent biases to three bounded policy outputs.

    Left/right intents can cancel each other. Multiple gestures never stack an
    output beyond ``cap``. The result is advisory and still passes through the
    normal vehicle safety supervisor.
    """
    cap = _bounded(cap, 0.0, GESTURE_BIAS_CAP)
    values = payload.get("bias", {}) if isinstance(payload, dict) else {}
    if not isinstance(values, dict):
        values = {}

    def intent(name):
        return _bounded(values.get(name, 0.0), 0.0, cap)

    left = max(intent("turn_left"), intent("lane_change_left"), intent("uturn_left"))
    right = max(intent("turn_right"), intent("lane_change_right"), intent("uturn_right"))
    stop = intent("stop")
    slow = intent("slow_down")
    overtake = intent("overtake_allowed")

    steering = _bounded(right - left, -cap, cap)
    accelerator = _bounded(overtake - max(slow, stop), -cap, cap)
    brake = _bounded(max(stop, slow * 0.5), 0.0, cap)
    active = bool(payload.get("tracking")) and any(
        abs(value) > 1e-6 for value in (steering, accelerator, brake)
    )
    return PolicyOutputBias(steering, accelerator, brake, active)


class GestureBiasReceiver:
    """Keep the latest loopback-only UDP gesture payload without blocking CARLA."""

    def __init__(self, host="127.0.0.1", port=8765, stale_after_s=0.75):
        self.host = host
        self.port = int(port)
        self.stale_after_s = float(stale_after_s)
        self._lock = threading.Lock()
        self._payload = {}
        self._received_at = 0.0
        self._stop = threading.Event()
        self._socket = None
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.settimeout(0.25)
        self._socket.bind((self.host, self.port))
        self._thread = threading.Thread(target=self._listen, name="gesture-bias", daemon=True)
        self._thread.start()

    def _listen(self):
        while not self._stop.is_set():
            try:
                data, _address = self._socket.recvfrom(65535)
                payload = json.loads(data.decode("utf-8"))
                if isinstance(payload, dict):
                    with self._lock:
                        self._payload = payload
                        self._received_at = time.monotonic()
            except socket.timeout:
                continue
            except (UnicodeDecodeError, json.JSONDecodeError, OSError):
                if not self._stop.is_set():
                    continue

    def snapshot(self):
        with self._lock:
            payload = dict(self._payload)
            age = time.monotonic() - self._received_at
        if not payload or age > self.stale_after_s:
            return PolicyOutputBias()
        return policy_bias_from_payload(payload)

    def stop(self):
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._socket = None
