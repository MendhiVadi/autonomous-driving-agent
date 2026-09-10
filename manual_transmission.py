"""Manual-transmission telemetry shared by the cockpit and ML interfaces.

CARLA 0.9.16 exposes wheel speed and selected gear, but not engine-shaft RPM
or a clutch pedal.  RPM is therefore estimated from road speed, configured
gear ratios, final drive, and tyre circumference.  The clutch is simulated by
scaling engine torque before the VehicleControl command reaches CARLA.
"""
from dataclasses import dataclass, field


def clamp(value, low, high):
    return max(low, min(high, float(value)))


@dataclass
class ManualTransmissionConfig:
    gear_ratios: dict = field(default_factory=lambda: {
        -1: 3.64,
        0: 0.0,
        # Redline road speeds: 12, 20, 28, 36, 42, and 48 km/h.  This keeps
        # every forward gear useful inside the cockpit's stability envelope.
        1: 12.9275,
        2: 7.7565,
        3: 5.5404,
        4: 4.3092,
        5: 3.6936,
        6: 3.2319,
    })
    gear_speed_ranges_kmh: dict = field(default_factory=lambda: {
        1: (0.0, 12.0),
        2: (9.0, 20.0),
        3: (17.0, 28.0),
        4: (25.0, 36.0),
        5: (33.0, 42.0),
        6: (39.0, 48.0),
    })
    final_drive_ratio: float = 4.27
    tyre_circumference_m: float = 1.84
    idle_rpm: float = 800.0
    redline_rpm: float = 6000.0
    max_forward_gear: int = 6


def gear_redline_speed_kmh(gear, config=None):
    """Theoretical road speed at redline for a configured forward gear."""
    config = config or ManualTransmissionConfig()
    ratio = abs(float(config.gear_ratios.get(int(gear), 0.0)))
    if ratio <= 0.0:
        return 0.0
    wheel_rpm = config.redline_rpm / (ratio * config.final_drive_ratio)
    return wheel_rpm * config.tyre_circumference_m / 60.0 * 3.6


def automatic_gear_for_speed(speed_kmh, config=None):
    """Choose the forward gear at the requested upper edge of each band."""
    config = config or ManualTransmissionConfig()
    speed = max(0.0, float(speed_kmh))
    for gear in range(1, config.max_forward_gear):
        if speed < config.gear_speed_ranges_kmh[gear][1]:
            return gear
    return config.max_forward_gear


def configure_vehicle_six_speed_physics(vehicle, carla_module, config=None):
    """Apply the shared six-speed ratios to a spawned CARLA vehicle."""
    config = config or ManualTransmissionConfig()
    physics = vehicle.get_physics_control()
    physics.max_rpm = float(config.redline_rpm)
    physics.final_ratio = float(config.final_drive_ratio)
    physics.use_gear_autobox = False
    torque_curve = list(physics.torque_curve)
    if torque_curve and max(point.x for point in torque_curve) < config.redline_rpm:
        torque_curve.extend([
            carla_module.Vector2D(x=5500.0, y=520.0),
            carla_module.Vector2D(x=float(config.redline_rpm), y=420.0),
        ])
        physics.torque_curve = torque_curve
    physics.forward_gears = [
        carla_module.GearPhysicsControl(
            ratio=float(config.gear_ratios[gear]),
            down_ratio=0.18,
            up_ratio=0.92,
        )
        for gear in range(1, config.max_forward_gear + 1)
    ]
    vehicle.apply_physics_control(physics)
    return physics


class EngineRpmEstimator:
    """Stateful tachometer model with believable rise and fall rates."""

    def __init__(self, config=None):
        self.config = config or ManualTransmissionConfig()
        self.rpm = self.config.idle_rpm

    def reset(self):
        self.rpm = self.config.idle_rpm

    def update(self, speed_kmh, gear, accelerator=0.0, clutch=0.0, dt=0.1):
        target = estimate_engine_rpm(
            speed_kmh, gear, accelerator, clutch, self.config,
        )
        dt = clamp(dt, 0.0, 0.5)
        # Engines gain revs faster than they shed them. Rate limiting prevents
        # the visually distracting jumps produced by raw wheel-speed updates.
        rate = 5200.0 if target >= self.rpm else 3200.0
        maximum_change = rate * dt
        self.rpm += clamp(target - self.rpm, -maximum_change, maximum_change)
        self.rpm = clamp(self.rpm, self.config.idle_rpm, self.config.redline_rpm)
        return self.rpm


def estimate_engine_rpm(speed_kmh, gear, accelerator=0.0, clutch=0.0,
                        config=None):
    """Estimate a plausible target RPM from wheel speed and driver demand."""
    config = config or ManualTransmissionConfig()
    gear = int(gear)
    accelerator = clamp(accelerator, 0.0, 1.0)
    clutch = clamp(clutch, 0.0, 1.0)
    free_rpm = config.idle_rpm + accelerator ** 0.72 * (
        config.redline_rpm - config.idle_rpm
    ) * 0.82
    ratio = abs(config.gear_ratios.get(gear, 0.0))
    if ratio == 0.0 or clutch >= 0.95:
        return clamp(free_rpm, config.idle_rpm, config.redline_rpm)
    wheel_rpm = (abs(float(speed_kmh)) / 3.6) / config.tyre_circumference_m * 60.0
    coupled_rpm = wheel_rpm * ratio * config.final_drive_ratio
    # CARLA does not expose clutch slip or engine-shaft speed. At launch, model
    # a modest amount of slip/load so pressing the accelerator produces useful
    # tachometer movement instead of pinning the display at idle.
    launch_factor = 1.0 - clamp(abs(float(speed_kmh)) / 18.0, 0.0, 1.0)
    launch_rpm = config.idle_rpm + accelerator * 1550.0 * launch_factor
    coupled_rpm = max(coupled_rpm, launch_rpm)
    # Partial clutch blends the coupled engine with a free-revving engine.
    rpm = coupled_rpm * (1.0 - clutch) + free_rpm * clutch
    return clamp(max(config.idle_rpm, rpm), config.idle_rpm, config.redline_rpm)


def recommended_shift(gear, rpm, accelerator=0.0, config=None, speed_kmh=None):
    """Return a compact driver-facing shift suggestion, if one is useful."""
    config = config or ManualTransmissionConfig()
    gear = int(gear)
    rpm = float(rpm)
    accelerator = clamp(accelerator, 0.0, 1.0)
    if gear <= 0:
        return ""
    if speed_kmh is not None and gear in config.gear_speed_ranges_kmh:
        low_speed, high_speed = config.gear_speed_ranges_kmh[gear]
        speed = max(0.0, float(speed_kmh))
        if gear < config.max_forward_gear and speed >= high_speed:
            return "SHIFT NOW"
        if gear > 1 and speed < low_speed:
            return "SHIFT DOWN"
        return ""
    if rpm >= config.redline_rpm * 0.91:
        return "SHIFT NOW" if gear < 6 else "REDLINE"
    if rpm >= config.redline_rpm * 0.77 and accelerator >= 0.35 and gear < 6:
        return "SHIFT UP"
    if rpm < 1250.0 and accelerator >= 0.25 and gear > 1:
        return "SHIFT DOWN"
    return ""


def selector_name(gear, parked=False):
    """P/R/N/D is display state; forward motion retains the actual M1-M6 gear."""
    if parked:
        return "P"
    if int(gear) < 0:
        return "R"
    if int(gear) == 0:
        return "N"
    return "D"


def manual_gear_name(gear, parked=False):
    if parked:
        return "P"
    if int(gear) < 0:
        return "R"
    if int(gear) == 0:
        return "N"
    return f"M{int(gear)}"
