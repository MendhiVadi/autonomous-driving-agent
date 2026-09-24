"""Safety gate between a neural policy and CARLA VehicleControl."""
from dataclasses import dataclass
import math
from vehicle.control import ControlConfig, VehicleCommand


@dataclass
class SafetyLimits:
    max_speed_kmh: float = 50.0
    minimum_obstacle_distance_m: float = 7.0
    stale_command_after_s: float = 0.25
    maximum_lane_error_m: float = 2.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


class SafetySupervisor:
    def __init__(self, limits=None):
        self.limits = limits or SafetyLimits()

    def apply(self, command, state):
        """Return (safe_command, reasons). State values are telemetry fields."""
        reasons = []
        numeric_fields = ("speed_kmh", "obstacle_distance_m", "lane_error_m", "command_age_s")
        try:
            values = [state[key] for key in numeric_fields]
            values += [command.accelerator, command.brake, command.clutch,
                       command.steering_angle_deg, command.gear]
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                raise ValueError("Telemetry and controls must contain finite numbers")
            if any(state[key] < 0 for key in ("speed_kmh", "obstacle_distance_m", "command_age_s")):
                raise ValueError("Negative distance, speed or command age")
            for key in ("red_light", "collision"):
                if not isinstance(state[key], bool):
                    raise ValueError("Safety flags must be booleans")
            if "sensor_timeout" in state and not isinstance(state["sensor_timeout"], bool):
                raise ValueError("Sensor timeout must be boolean")
            command = command.sanitized(ControlConfig())
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            return VehicleCommand(brake=1.0, hand_brake=True, gear=0), ["invalid_telemetry_or_command"]
        if state.get("collision", False):
            reasons.append("collision")
        if state.get("sensor_timeout", False):
            reasons.append("sensor_timeout")
        if state.get("command_age_s", 0.0) > self.limits.stale_command_after_s:
            reasons.append("stale_command")
        if abs(state["lane_error_m"]) > self.limits.maximum_lane_error_m:
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
