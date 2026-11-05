"""Exclusive, camera-free CARLA physics for state-based neural inputs."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sys
import time


STEP_SECONDS = 0.05
# CARLA large maps stream tiles around the hero car and need long load timeouts.
LARGE_MAPS = frozenset({"Town11", "Town12", "Town13"})
LARGE_MAP_LOAD_TIMEOUT_S = 900.0


def require_idle_world(world):
    """Check before loading maps or changing settings, which affect all clients."""
    if world.get_settings().synchronous_mode:
        raise RuntimeError("Another client owns world ticks; stop it before starting this environment.")
    actors = world.get_actors()
    if actors.filter("sensor.camera.*"):
        raise RuntimeError("The state-input environment cannot share a world with camera clients.")
    if any(actors.filter(pattern) for pattern in ("vehicle.*", "walker.*", "sensor.*")):
        raise RuntimeError("Another simulation has active actors; close it before changing the environment.")


def cleanup_actions(actions):
    """Attempt every cleanup even when a disconnected server rejects one."""
    for name, action in actions:
        try:
            action()
        except Exception as exc:
            print(f"[cleanup] {name}: {exc}", file=sys.stderr, flush=True)


def prepare_state_world(client, carla, map_name=None):
    """Disable rendering before map loading; packaged builds can ignore CLI flags."""
    world = client.get_world()
    require_idle_world(world)
    settings = world.get_settings()
    settings.no_rendering_mode = True
    settings.fixed_delta_seconds = STEP_SECONDS
    world.apply_settings(settings)
    if map_name and world.get_map().name.rsplit('/', 1)[-1].lower() != map_name.rsplit('/', 1)[-1].lower():
        world = client.load_world(map_name, reset_settings=False, map_layers=carla.MapLayer.NONE)
    elif map_name and map_name.rsplit('/', 1)[-1].endswith('_Opt'):
        # Starting directly on the target town must also discard optional scenery.
        world.unload_map_layer(carla.MapLayer.All)
    if not world.get_settings().no_rendering_mode:
        raise RuntimeError('CARLA did not retain no-rendering mode while preparing neural inputs')
    return world


@contextmanager
def state_input_world(world, carla):
    """Own fixed ticks, avoid the RGB renderer, and restore settings/weather."""
    require_idle_world(world)
    original = world.get_settings()
    weather = world.get_weather()
    try:
        settings = world.get_settings()
        settings.no_rendering_mode = True
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = STEP_SECONDS
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        world.apply_settings(settings)
        world.set_weather(carla.WeatherParameters(
            cloudiness=0, precipitation=0, precipitation_deposits=0,
            wind_intensity=0, fog_density=0, wetness=0,
            sun_altitude_angle=70, dust_storm=0))
        yield
    finally:
        cleanup_actions([
            ("restore weather", lambda: world.set_weather(weather)),
            ("restore world settings", lambda: world.apply_settings(original)),
        ])


def paced_tick(world, timeout_s, started_at=None):
    """Advance exactly one physics step and cap throughput at 20 Hz."""
    started_at = time.monotonic() if started_at is None else started_at
    frame = world.tick(timeout_s)
    time.sleep(max(0.0, STEP_SECONDS - (time.monotonic() - started_at)))
    return frame


def write_input_heartbeat(path, frame):
    if not path:
        return
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps({"updated_monotonic": time.monotonic(),
                                     "frame": int(frame)}), encoding="utf-8")
    temporary.replace(path)


def input_heartbeat_ready(path, started_at, max_age_s=10.0):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        stamp = float(data["updated_monotonic"])
        age = time.monotonic() - stamp
        return (math.isfinite(stamp) and stamp >= started_at
                and 0 <= age <= max_age_s and int(data["frame"]) > 0)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def map_short_name(name):
    """``/Game/Carla/Maps/Town13/Town13`` and ``Town13`` both become ``Town13``."""
    return str(name).rsplit("/", 1)[-1]


def is_large_map(name):
    return map_short_name(name) in LARGE_MAPS


def load_world_for_driving(client, map_name, carla):
    """Load a fully rendered world for driving, bounding large-map streaming.

    Every map layer stays enabled. For Town11/12/13 the spectator no longer
    streams its own tiles and the streamed region is limited to the area
    around the hero vehicle; this bounds the initial load, not scene quality.
    The caller owns the client timeout; large maps can take minutes to load.
    """
    world = client.get_world()
    require_idle_world(world)
    current = map_short_name(world.get_map().name)
    target = map_short_name(map_name)
    if target in LARGE_MAPS:
        original = world.get_settings()
        settings = world.get_settings()
        settings.spectator_as_ego = False
        settings.tile_stream_distance = 650.0
        settings.actor_active_distance = 350.0
        world.apply_settings(settings)
        if current.lower() != target.lower():
            try:
                world = client.load_world(map_name, reset_settings=False, map_layers=carla.MapLayer.All)
            except Exception:
                client.set_timeout(5)
                cleanup_actions([("restore failed map-load settings", lambda: world.apply_settings(original))])
                raise
    elif current.lower() != target.lower():
        world = client.load_world(map_name, map_layers=carla.MapLayer.All)
    elif target.endswith("_Opt"):
        world.load_map_layer(carla.MapLayer.All)
    return world


def warm_up_large_map_tiles(world, vehicle, client, carla, map_name=None):
    """Hold the brakes and tick until the tiles around a freshly spawned car exist.

    Small maps return immediately. The world must already be synchronous: the
    first tick after spawning on Town13 can take most of a minute.
    """
    name = map_short_name(map_name if map_name is not None else world.get_map().name)
    if name not in LARGE_MAPS:
        return
    print(f"[map] {name}: loading nearby tiles with the vehicle held under braking", flush=True)
    try:
        client.set_timeout(60)
        vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
        transform = vehicle.get_transform()
        world.get_spectator().set_transform(carla.Transform(
            transform.location - transform.get_forward_vector() * 7 + carla.Location(z=3.2),
            carla.Rotation(pitch=-12, yaw=transform.rotation.yaw)))
        world.tick(60)
        client.set_timeout(10)
        for _ in range(3):
            world.tick(10)
    finally:
        client.set_timeout(5)
    print(f"[map] {name}: tile warm-up complete; full rendering remains enabled", flush=True)


def carla_rpc_probe(host, port, timeout_s=3.0):
    """True only when the server answers RPC and its world is still advancing.

    A crashed renderer can leave its TCP listener open indefinitely, and a
    dead synchronous tick owner must also count as unhealthy. The world is
    observed, never ticked, so an owned session is not disturbed.
    """
    try:
        import carla
        client = carla.Client(host, port)
        client.set_timeout(timeout_s)
        client.get_server_version()
        world = client.get_world()
        world.wait_for_tick(seconds=timeout_s)
        return True
    except (RuntimeError, OSError, ImportError):
        return False
