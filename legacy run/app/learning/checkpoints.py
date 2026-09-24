"""Diagnostic scores for the existing baseline, not an RL reward contract."""
import math

def evaluate_non_visual_checkpoints(features, command, collided, previous_steering_deg):
    """Score checks that can be evaluated without camera pixels.

    These checks are deliberately named and serialized so a future RL trainer
    can use them as shaped rewards instead of treating the score as a black
    box. A passing check gives positive reinforcement; safety failures carry
    larger penalties.
    """
    lane_error, heading, speed, target, obstacle, red, _curvature, _stopped = features
    speed_mps = speed / 3.6
    safe_gap = max(7.0, speed_mps * 1.2)
    checks = {
        "state_finite": all(math.isfinite(float(value)) for value in features),
        "lane_centered": abs(lane_error) <= 1.2,
        "heading_aligned": abs(heading) <= 12.0,
        "speed_suitable": speed <= target + 5.0 and (speed >= 1.0 or target <= 1.0),
        "safe_following_distance": obstacle >= safe_gap,
        "traffic_light_compliance": red < 0.5 or speed <= 1.5,
        "smooth_steering": abs(command.steering_angle_deg - previous_steering_deg) <= 22.0,
        "no_conflicting_controls": not (command.accelerator > 0.05 and command.brake > 0.05),
        "no_collision": not collided,
        "lane_safety": abs(lane_error) <= 2.0,
    }
    weights = {
        "state_finite": 0.25,
        "lane_centered": 0.35,
        "heading_aligned": 0.25,
        "speed_suitable": 0.25,
        "safe_following_distance": 0.50,
        "traffic_light_compliance": 0.75,
        "smooth_steering": 0.20,
        "no_conflicting_controls": 0.50,
        "no_collision": 2.00,
        "lane_safety": 1.00,
    }
    reward = sum(weights[name] if passed else -weights[name] for name, passed in checks.items())
    if all(checks.values()):
        reward += 1.0  # completion bonus when every non-visual point matches
    return checks, reward
