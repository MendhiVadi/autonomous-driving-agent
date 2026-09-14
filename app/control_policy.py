"""Explicit vehicle controls and ML-friendly objectives for CARLA.

CARLA's VehicleControl.steer is normalized [-1, 1], not an angle.  This module
keeps the policy interface in physical-ish units and converts only at the
simulator boundary.
"""
from dataclasses import dataclass
from math import atan, degrees, isfinite

import carla


def clamp(value, low, high):
    value = float(value)
    if not isfinite(value):
        raise ValueError("Control values must be finite")
    return max(low, min(high, value))


@dataclass
class ControlConfig:
    max_steering_angle_deg: float = 70.0
    max_reverse_speed_kmh: float = 12.0
    steering_rate_deg_per_s: float = 120.0
    throttle_rate_per_s: float = 2.0
    brake_rate_per_s: float = 4.0
    max_forward_gear: int = 6


@dataclass
class VehicleCommand:
    """The action emitted by a keyboard controller or ML policy.

    ``steering_angle_deg`` is the requested road-wheel angle.  Positive is
    right, negative is left.  Accelerator, brake, and handbrake are explicit.
    Gear is -1 reverse, 0 neutral, or manual forward gear 1 through 6.
    """
    accelerator: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0
    hand_brake: bool = False
    wipers: bool = False
    steering_angle_deg: float = 0.0
    gear: int = 1

    def sanitized(self, config=ControlConfig()):
        if isinstance(self.gear, bool) or not isinstance(self.gear, (int, float)) or not isfinite(self.gear) or int(self.gear) != self.gear:
            raise ValueError("Gear must be a finite integer")
        requested_gear = int(self.gear)
        gear = max(-1, min(config.max_forward_gear, requested_gear))
        return VehicleCommand(
            accelerator=clamp(self.accelerator, 0.0, 1.0),
            brake=clamp(self.brake, 0.0, 1.0),
            clutch=clamp(self.clutch, 0.0, 1.0),
            hand_brake=bool(self.hand_brake),
            wipers=bool(self.wipers),
            steering_angle_deg=clamp(
                self.steering_angle_deg,
                -config.max_steering_angle_deg,
                config.max_steering_angle_deg,
            ),
            gear=gear,
        )

    def to_carla(self, config=ControlConfig()):
        command = self.sanitized(config)
        # CARLA's stock Mustang transmission normalizes manual gear 0 back to
        # first gear. Represent neutral deterministically as first gear with
        # zero delivered torque; the cockpit keeps N as the driver-facing state.
        simulator_gear = 1 if command.gear == 0 else command.gear
        return carla.VehicleControl(
            # CARLA has no clutch pedal field. Disengaging the clutch removes
            # wheel torque while preserving accelerator telemetry for training.
            throttle=(0.0 if command.gear == 0 else
                      command.accelerator * (1.0 - command.clutch)),
            brake=command.brake,
            hand_brake=command.hand_brake,
            steer=command.steering_angle_deg / config.max_steering_angle_deg,
            reverse=command.gear < 0,
            manual_gear_shift=True,
            gear=simulator_gear,
        )


def steering_angle_from_lane_error(lateral_error_m, heading_error_deg,
                                   wheelbase_m=2.8, lookahead_m=8.0,
                                   max_angle_deg=70.0):
    """Simple interpretable baseline for turn angle before ML is added."""
    # The public contract is degrees. Converting small degree values as though
    # they were radians caused a discontinuity around +/-1 degree.
    target = float(heading_error_deg) + degrees(
        atan(2.0 * lateral_error_m / max(lookahead_m, 0.1))
    )
    return clamp(target, -max_angle_deg, max_angle_deg)


def action_vector(command):
    """Stable ML action contract including the simulator wiper state."""
    command = command.sanitized()
    return [command.accelerator, command.brake, command.clutch,
            float(command.hand_brake), float(command.wipers),
            command.steering_angle_deg, float(command.gear)]


def objective_reward(progress_m, elapsed_s, speed_kmh, acceleration_mps2,
                     steering_rate_deg_s, collision=False, lane_departure=False,
                     fuel_proxy=0.0):
    """Training score; safety penalties dominate time/mileage incentives.

    CARLA does not provide a universal fuel-consumption model, so ``fuel_proxy``
    must initially be an explicit proxy (throttle squared, acceleration, and
    speed). Replace it later with vehicle-specific powertrain telemetry.
    """
    reward = 1.0 * progress_m - 0.03 * elapsed_s
    reward -= 0.01 * max(speed_kmh - 50.0, 0.0) ** 2
    reward -= 0.03 * abs(acceleration_mps2)
    reward -= 0.002 * abs(steering_rate_deg_s)
    reward -= 0.15 * fuel_proxy
    if lane_departure:
        reward -= 100.0
    if collision:
        reward -= 1000.0
    return reward
