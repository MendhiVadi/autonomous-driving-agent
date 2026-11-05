"""Minimal stand-in for the ``carla`` client package, used only by the tests.

``tools/verify.py`` puts this directory on ``sys.path`` when the real CARLA
package is not importable (for example on a machine without the simulator), so
the offline regression suite still runs. It implements just the value types the
application modules touch at import time or in unit tests: geometry, vehicle
control, weather, enums. Nothing here talks to a server. Tests that need the
real API check ``carla.IS_STUB`` and skip.
"""
import math

IS_STUB = True


class Vector3D:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __add__(self, other):
        return type(self)(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        return type(self)(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar):
        return type(self)(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def length(self):
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    def __repr__(self):
        return f"{type(self).__name__}(x={self.x}, y={self.y}, z={self.z})"


class Location(Vector3D):
    def distance(self, other):
        return (self - other).length()


class Rotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)

    def get_forward_vector(self):
        pitch, yaw = math.radians(self.pitch), math.radians(self.yaw)
        return Vector3D(math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))

    def get_right_vector(self):
        # CARLA uses Unreal's left-handed frame: x forward, y right, z up.
        yaw = math.radians(self.yaw)
        return Vector3D(-math.sin(yaw), math.cos(yaw), 0.0)


class Transform:
    def __init__(self, location=None, rotation=None):
        self.location = location if location is not None else Location()
        self.rotation = rotation if rotation is not None else Rotation()

    def get_forward_vector(self):
        return self.rotation.get_forward_vector()

    def get_right_vector(self):
        return self.rotation.get_right_vector()


class VehicleControl:
    def __init__(self, throttle=0.0, steer=0.0, brake=0.0, hand_brake=False, reverse=False,
                 manual_gear_shift=False, gear=0):
        self.throttle, self.steer, self.brake = float(throttle), float(steer), float(brake)
        self.hand_brake, self.reverse = bool(hand_brake), bool(reverse)
        self.manual_gear_shift, self.gear = bool(manual_gear_shift), int(gear)

    def __repr__(self):
        return (f"VehicleControl(throttle={self.throttle}, steer={self.steer}, brake={self.brake}, "
                f"hand_brake={self.hand_brake}, reverse={self.reverse}, gear={self.gear})")


class WeatherParameters:
    _FIELDS = ("cloudiness", "precipitation", "precipitation_deposits", "wind_intensity",
               "sun_azimuth_angle", "sun_altitude_angle", "fog_density", "fog_distance", "fog_falloff",
               "wetness", "scattering_intensity", "mie_scattering_scale", "rayleigh_scattering_scale",
               "dust_storm")

    def __init__(self, **values):
        unknown = set(values) - set(self._FIELDS)
        if unknown:
            raise TypeError(f"Unknown weather parameters: {sorted(unknown)}")
        for name in self._FIELDS:
            setattr(self, name, float(values.get(name, 0.0)))


WeatherParameters.ClearNoon = WeatherParameters(cloudiness=15, sun_altitude_angle=75, sun_azimuth_angle=0)
WeatherParameters.WetNoon = WeatherParameters(cloudiness=20, precipitation_deposits=50, wetness=50,
                                              sun_altitude_angle=75)
WeatherParameters.HardRainNoon = WeatherParameters(cloudiness=90, precipitation=60, precipitation_deposits=100,
                                                   wind_intensity=100, wetness=100, sun_altitude_angle=75)


class _Flag(int):
    def __new__(cls, value):
        return super().__new__(cls, int(value))

    def __or__(self, other):
        return _Flag(int(self) | int(other))

    __ror__ = __or__

    def __and__(self, other):
        return _Flag(int(self) & int(other))


class MapLayer:
    NONE = _Flag(0)
    Buildings = _Flag(1 << 0)
    Decals = _Flag(1 << 1)
    Foliage = _Flag(1 << 2)
    Ground = _Flag(1 << 3)
    ParkedVehicles = _Flag(1 << 4)
    Particles = _Flag(1 << 5)
    Props = _Flag(1 << 6)
    StreetLights = _Flag(1 << 7)
    Walls = _Flag(1 << 8)
    All = _Flag(0xFFFF)

    def __new__(cls, value):
        return _Flag(value)


class TrafficLightState:
    Red = "Red"
    Yellow = "Yellow"
    Green = "Green"
    Off = "Off"
    Unknown = "Unknown"


class LaneType:
    Driving = "Driving"
    Any = "Any"


class AttachmentType:
    Rigid = "Rigid"
    SpringArm = "SpringArm"


class Client:
    """Never connects; tests patch ``carla.Client`` when they need behaviour."""

    def __init__(self, host="127.0.0.1", port=2000, worker_threads=0):
        self.host, self.port = host, int(port)

    def set_timeout(self, seconds):
        self.timeout = float(seconds)

    def get_client_version(self):
        return "0.9.16-stub"

    def get_server_version(self):
        raise RuntimeError("time-out of 0ms while waiting for the simulator (test stub)")

    def get_world(self):
        raise RuntimeError("time-out of 0ms while waiting for the simulator (test stub)")


class Actor:
    pass


class Vehicle(Actor):
    pass


class World:
    pass
