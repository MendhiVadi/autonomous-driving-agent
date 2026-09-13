"""Safety gate between a neural policy and CARLA VehicleControl."""
from dataclasses import dataclass
import math
import os
import sys
from pathlib import Path

try:
    from control_policy import ControlConfig, VehicleCommand
except ImportError:
    carla_root = Path(os.environ.get("CARLA_ROOT", r"C:\Users\medha\Documents\CARLA\CARLA_0.9.16"))
    sys.path.insert(0, str(carla_root))
    from control_policy import ControlConfig, VehicleCommand


@dataclass
class SafetyLimits:
    max_speed_kmh: float = 50.0
    minimum_obstacle_distance_m: float = 7.0
    stale_command_after_s: float = 0.25
    maximum_lane_error_m: float = 2.0


class SafetySupervisor:
    def __init__(self, limits=None):
        self.limits = limits or SafetyLimits()

    def apply(self, command, state):
        """Return (safe_command, reasons). State values are telemetry fields."""
        reasons = []
        numeric_command = (command.accelerator, command.brake, command.clutch,
                           command.steering_angle_deg, command.gear)
        numeric_state = (state.get("speed_kmh", 0.0),
                         state.get("obstacle_distance_m", 999.0),
                         state.get("lane_error_m", 0.0),
                         state.get("command_age_s", 0.0))
        try:
            finite = all(math.isfinite(float(value)) for value in numeric_command + numeric_state)
        except (TypeError, ValueError):
            finite = False
        if not finite:
            return VehicleCommand(brake=1.0, hand_brake=True, gear=0), ["invalid_telemetry_or_command"]
        command = command.sanitized(ControlConfig())
        if state.get("collision", False):
            reasons.append("collision")
        if state.get("sensor_timeout", False):
            reasons.append("sensor_timeout")
        if state.get("command_age_s", 0.0) > self.limits.stale_command_after_s:
            reasons.append("stale_command")
        if state.get("lane_error_m", 0.0) > self.limits.maximum_lane_error_m:
            reasons.append("lane_departure")
        if state.get("obstacle_distance_m", 999.0) < self.limits.minimum_obstacle_distance_m:
            reasons.append("obstacle")
        if state.get("speed_kmh", 0.0) > self.limits.max_speed_kmh:
            reasons.append("speed_limit")
        if state.get("red_light", False):
            reasons.append("red_light")
        if reasons:
            return VehicleCommand(brake=1.0,
                                  clutch=command.clutch,
                                  hand_brake=bool(state.get("collision", False)),
                                  gear=command.gear), reasons
        if command.brake > 0.0:
            command.accelerator = 0.0
        return command, reasons
