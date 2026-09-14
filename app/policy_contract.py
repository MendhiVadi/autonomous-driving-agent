"""Single source of truth for the state-policy input contract."""

import math

POLICY_CONTRACT_VERSION = 2
POLICY_SIZES = [8, 24, 16, 3]
INPUT_NAMES = (
    "lane_error_m",
    "heading_error_deg",
    "speed_kmh",
    "target_speed_kmh",
    "front_obstacle_distance_m",
    "red_light",
    "curvature",
    "stopped",
)
OUTPUT_NAMES = ("steering", "accelerator", "brake")


def clamp(value, low, high):
    return max(low, min(high, float(value)))


def normalize_features(features):
    """Normalize the eight live and training inputs identically."""
    if len(features) != len(INPUT_NAMES):
        raise ValueError(f"Expected {len(INPUT_NAMES)} policy inputs, got {len(features)}")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in features):
        raise ValueError("Policy features must be finite numbers")
    lane, heading, speed, target, obstacle, red, curvature, stopped = features
    return [
        clamp(lane / 4.0, -1.0, 1.0),
        clamp(heading / 35.0, -1.0, 1.0),
        clamp(speed / 160.0, 0.0, 1.0),
        clamp(target / 160.0, 0.0, 1.0),
        clamp((obstacle - 40.0) / 40.0, -1.0, 1.0),
        clamp(red, 0.0, 1.0),
        clamp(curvature, -1.0, 1.0),
        clamp(stopped, 0.0, 1.0),
    ]
