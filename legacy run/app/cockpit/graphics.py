"""Existing camera-cockpit stability controls; native scenic mode is separate."""
import carla
from vehicle.transmission import configure_vehicle_six_speed_physics

def apply_turn_stability(control, speed_kmh, start_steer=0.10,
                         minimum_throttle_fraction=0.38):
    """Reduce drive torque smoothly during a tight turn.

    Steering remains fully under the driver's control.  Only accelerator is
    narrowed, preventing the previous full-throttle/full-lock combination
    that coincided with repeated simulator crashes and vehicle instability.
    """
    steering = abs(float(control.steer))
    if steering <= start_steer or control.throttle <= 0.0:
        return control, False
    severity = min(1.0, (steering - start_steer) / max(0.01, 0.72 - start_steer))
    speed_factor = min(1.0, max(0.25, float(speed_kmh) / 25.0))
    fraction = 1.0 - severity * speed_factor * (1.0 - minimum_throttle_fraction)
    original = float(control.throttle)
    control.throttle = min(original, original * fraction)
    return control, control.throttle < original


def apply_speed_sensitive_steering(control, speed_kmh):
    """Clamp road-wheel demand progressively as speed increases."""
    speed = max(0.0, float(speed_kmh))
    if speed <= 20.0:
        limit = 0.72
    elif speed >= 48.0:
        limit = 0.22
    else:
        limit = 0.72 - ((speed - 20.0) / 28.0) * 0.50
    original = float(control.steer)
    control.steer = max(-limit, min(limit, original))
    return control, abs(control.steer - original) > 1e-6


def apply_scene_streaming_limit(control, speed_kmh, soft_limit_kmh=38.0,
                                hard_limit_kmh=48.0):
    """Keep the visible multi-view cockpit below its verified GPU cliff."""
    speed = max(0.0, float(speed_kmh))
    soft = max(0.0, float(soft_limit_kmh))
    hard = max(soft + 1.0, float(hard_limit_kmh))
    if speed <= soft:
        return control, False
    severity = min(1.0, (speed - soft) / (hard - soft))
    throttle_fraction = max(0.0, 1.0 - severity * 1.7)
    control.throttle = min(float(control.throttle), float(control.throttle) * throttle_fraction)
    # Begin gentle braking before the ceiling so inertia cannot carry the car
    # through it; at/above 48 km/h the bounded brake becomes authoritative.
    if speed >= 42.0:
        brake_fraction = min(0.65, 0.12 + (speed - 42.0) * (0.53 / 6.0))
        control.brake = max(float(control.brake), brake_fraction)
        control.throttle = 0.0
    return control, True


def format_speed_kmh(speed_kmh):
    """Natural-width speed text: 0, 9, 42, 160; never 000 or 042."""
    return f"{max(0.0, float(speed_kmh)):.0f}"


def apply_graphics_throttle_neck(control, speed_kmh, start_kmh=135.0,
                                 cap_kmh=160.0):
    """Progressively reduce acceleration before the cockpit speed ceiling.

    Fast travel makes CARLA stream scenery more aggressively, which can starve
    the four camera feeds on an integrated GPU. This limiter preserves normal
    pedal response below ``start_kmh`` and smoothly narrows the available
    throttle to zero at ``cap_kmh``. It intentionally does not apply the brake,
    so driver braking and the existing fail-safe behavior remain authoritative.
    """
    speed = max(0.0, float(speed_kmh))
    start = max(0.0, float(start_kmh))
    cap = max(start + 1.0, float(cap_kmh))
    if speed <= start:
        return control, False
    throttle_fraction = max(0.0, min(1.0, (cap - speed) / (cap - start)))
    original_throttle = float(control.throttle)
    control.throttle = min(original_throttle, original_throttle * throttle_fraction)
    return control, control.throttle < original_throttle


def configure_six_speed_physics(vehicle, config=None):
    """Install the same six ratios used by the cockpit RPM model in CARLA."""
    return configure_vehicle_six_speed_physics(vehicle, carla, config)


def reduced_motion_weather(weather):
    """Copy weather while removing animated effects that cost render time."""
    return carla.WeatherParameters(
        cloudiness=0.0,
        precipitation=0.0,
        precipitation_deposits=float(weather.precipitation_deposits),
        wind_intensity=0.0,
        sun_azimuth_angle=float(weather.sun_azimuth_angle),
        sun_altitude_angle=float(weather.sun_altitude_angle),
        fog_density=0.0,
        fog_distance=float(weather.fog_distance),
        fog_falloff=float(weather.fog_falloff),
        wetness=float(weather.wetness),
        scattering_intensity=float(weather.scattering_intensity),
        mie_scattering_scale=float(weather.mie_scattering_scale),
        rayleigh_scattering_scale=float(weather.rayleigh_scattering_scale),
        dust_storm=0.0,
    )


def visual_austerity_transition(active, speed_kmh, start_kmh=45.0,
                                resume_kmh=38.0):
    """Return the high-speed reduced-motion state with hysteresis."""
    speed = max(0.0, float(speed_kmh))
    if active:
        return speed > float(resume_kmh)
    return speed >= float(start_kmh)
