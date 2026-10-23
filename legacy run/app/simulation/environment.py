"""Exclusive, camera-free CARLA physics for state-based neural inputs."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sys
import time


STEP_SECONDS = 0.05


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
