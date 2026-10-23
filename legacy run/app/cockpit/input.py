"""Keyboard state, manual controls and transmission decisions."""
import time
from vehicle.control import ControlConfig, VehicleCommand
from vehicle.transmission import automatic_gear_for_speed

class HeldKeyState:
    """Event-driven keyboard state with a short latch for very quick taps."""

    def __init__(self, tap_latch_seconds=0.035):
        self._pressed = set()
        self._released_until = {}
        self._tap_latch_seconds = tap_latch_seconds

    def press(self, key):
        self._pressed.add(key)
        self._released_until.pop(key, None)

    def release(self, key):
        self._pressed.discard(key)
        self._released_until[key] = time.monotonic() + self._tap_latch_seconds

    def clear(self):
        self._pressed.clear()
        self._released_until.clear()

    def __getitem__(self, key):
        if key in self._pressed:
            return True
        expires_at = self._released_until.get(key, 0.0)
        if expires_at > time.monotonic():
            return True
        self._released_until.pop(key, None)
        return False


def build_vehicle_control(keys, pygame, steer, steering_step=0.035,
                          selected_gear=1, parked=False, handbrake=False):
    """Translate keyboard state into an unambiguous CARLA vehicle control.

    R/N/1-6 choose the actual gear. P is a visual selector backed by neutral
    plus the parking brake. W/Up accelerates, S/Down brakes, A/D and arrows
    steer, Left Shift/Control is the clutch, and Space is the handbrake.
    """
    forward = bool(keys[pygame.K_w] or keys[pygame.K_UP])
    braking = bool(keys[pygame.K_s] or keys[pygame.K_DOWN])
    left = bool(keys[pygame.K_a] or keys[pygame.K_LEFT])
    right = bool(keys[pygame.K_d] or keys[pygame.K_RIGHT])
    clutch = 1.0 if (keys[pygame.K_LSHIFT] or keys[pygame.K_LCTRL]) else 0.0
    service_handbrake = bool(keys[pygame.K_SPACE])
    accelerator = 0.0 if parked or selected_gear == 0 or braking else (0.65 if forward else 0.0)
    brake = 1.0 if braking else 0.0
    gear = selected_gear

    if left:
        steer -= steering_step
    if right:
        steer += steering_step
    # Full steering lock is both unrealistic at road speed and produces the
    # largest scenery/rendering spike on this integrated-GPU machine.  Keep
    # keyboard steering progressive and leave a useful safety margin.
    steer = max(-0.72, min(0.72, steer))
    if not (left or right):
        steer *= 0.82

    # Steering-wheel direction does not invert in reverse. The vehicle's path
    # changes because velocity is reversed, not because the road wheels flip.
    # VehicleCommand is the same interface an ML policy will emit.
    command = VehicleCommand(
        accelerator=accelerator,
        brake=brake,
        clutch=clutch,
        hand_brake=parked or handbrake or service_handbrake,
        steering_angle_deg=steer * 70.0,
        gear=gear,
    )
    return command.to_carla(ControlConfig()), steer


def can_change_gear(speed_kmh, clutch_position):
    """Allow easy standstill selection but require the clutch while moving."""
    return abs(float(speed_kmh)) < 1.0 or float(clutch_position) >= 0.95


def automatic_route_gear(speed_kmh, config=None):
    """Choose a route-driving gear from the requested speed bands."""
    return automatic_gear_for_speed(speed_kmh, config)


def gearbox_state_matches(requested_gear, applied_gear):
    """Account for CARLA's first-gear, zero-torque neutral representation."""
    requested_gear = int(requested_gear)
    applied_gear = int(applied_gear)
    if requested_gear == 0:
        return applied_gear in (0, 1)
    return requested_gear == applied_gear
