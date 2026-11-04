"""Bounded assistance for the retained imitation-learning baseline."""
import math

def clamp(value, low, high):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Policy controls must be finite")
    return max(low, min(high, value))


def apply_stall_recovery(features, accelerator, brake, stalled_for_s,
                         active=False, activation_delay_s=2.0,
                         brake_override_delay_s=5.0, max_accelerator=0.35,
                         maximum_lane_error_m=1.2):
    """Add bounded forward progress only when the road state is clearly safe.

    The saved model remains the primary policy. Recovery activates only after a
    real standstill with no useful accelerator request, and immediately drops
    out for a red light, nearby obstacle, lane/heading error, model brake
    request, invalid state, or when the car reaches cruising speed.
    """
    try:
        values = [*features, accelerator, brake, stalled_for_s,
                  activation_delay_s, brake_override_delay_s, max_accelerator,
                  maximum_lane_error_m]
        if (len(features) != 8 or not isinstance(active, bool) or
                any(isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) for value in values)):
            return 0.0, 1.0, False
        if min(stalled_for_s, activation_delay_s, brake_override_delay_s,
               max_accelerator, maximum_lane_error_m) < 0:
            return 0.0, 1.0, False
        lane, heading, speed, target, obstacle, red, _curvature, _stopped = (
            float(value) for value in features
        )
        accelerator = clamp(accelerator, 0.0, 1.0)
        brake = clamp(brake, 0.0, 1.0)
        stalled_for_s = max(0.0, float(stalled_for_s))
        max_accelerator = clamp(max_accelerator, 0.0, 0.5)
        finite = all(math.isfinite(value) for value in (
            lane, heading, speed, target, obstacle, red,
            accelerator, brake, stalled_for_s, max_accelerator,
        ))
    except (TypeError, ValueError, OverflowError):
        return 0.0, 1.0, False
    safe_gap_m = max(12.0, max(0.0, speed) / 3.6 * 2.0)
    clear_to_assist = (
        finite and target >= 5.0 and red < 0.5 and obstacle >= safe_gap_m
        and abs(lane) <= min(1.6, maximum_lane_error_m) and abs(heading) <= 15.0
    )
    if not clear_to_assist:
        return accelerator, brake, False
    release_speed = max(5.0, target * 0.85)
    if active and speed >= release_speed:
        return accelerator, brake, False
    # A brake request while moving is meaningful and must be respected. At a
    # prolonged, verified-clear standstill it is the known legacy-policy
    # failure mode, so recovery may release it after a longer delay.
    if brake >= 0.45 and speed >= 1.0:
        return accelerator, brake, False
    required_delay = (
        max(float(activation_delay_s), float(brake_override_delay_s))
        if brake >= 0.45 else max(0.0, float(activation_delay_s))
    )
    should_activate = (
        active or (
            is_stall_candidate(speed, accelerator, brake)
            and stalled_for_s >= required_delay
        )
    )
    if not should_activate:
        return accelerator, brake, False
    requested = clamp(
        (target - speed) / max(target, 1.0) * max_accelerator,
        0.12, max_accelerator,
    )
    return min(max_accelerator, max(accelerator, requested)), 0.0, True


def is_stall_candidate(speed, accelerator, brake):
    """Braking cancels accelerator, including contradictory model outputs."""
    return speed < 1.0 and (accelerator < 0.05 or brake >= 0.45)


def limit_neural_speed(accelerator, brake, speed, target):
    """Ease off at the target before reaching the emergency speed cutoff."""
    margin = target - speed
    accelerator *= clamp(margin / 3.0, 0.0, 1.0)
    if margin < -1.0:
        brake = max(brake, clamp((-margin - 1.0) * 0.12, 0.0, 0.5))
    if brake > 0.0:
        accelerator = 0.0
    return accelerator, brake


def apply_lane_assistance(features, steering):
    """Bounded geometry correction; outputs remain explicitly assisted inference.

    Positive lane/heading error needs negative steering in CARLA. Blend toward
    a centering command, never adding more than 0.16 normalized steering. Reduce
    speed while displaced or approaching a turn; the supervisor still follows.
    """
    lane, heading, speed, target, obstacle, red, curvature, stopped = features
    if not all(math.isfinite(x) for x in (*features, steering)):
        raise ValueError('Non-finite lane-assistance input')
    target = max(0.0, target)
    if abs(lane) > 2.0 or red >= .5 or obstacle < 7.0:
        return steering, 0.0, target
    desired = -0.12 * lane - 0.012 * heading
    correction = clamp((desired - steering) * .45, -.16, .16)
    corrected = clamp(steering + correction, -1.0, 1.0)
    curve_limit = max(12.0, target - .6 * max(0.0, abs(heading)-10.0))
    lane_limit = max(12.0, target - 20.0 * max(0.0, abs(lane)-.6))
    return corrected, corrected-steering, min(target, curve_limit, lane_limit)
