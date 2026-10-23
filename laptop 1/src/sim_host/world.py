"""Exclusive world ownership and best-effort cleanup for the simulation host."""
import sys
from pathlib import Path

LARGE_MAPS = {"Town11", "Town12", "Town13"}


def create_client(carla):
    client = carla.Client("127.0.0.1", 2000)
    cache = Path(__file__).resolve().parents[2] / "cache/carla-api"
    cache.mkdir(parents=True, exist_ok=True)
    client.set_files_base_folder(str(cache))
    return client


def load_map(client, map_name, carla):
    """Load an idle world without streaming a wide area around an unused spectator.

    Keep rendering enabled and every map layer. Large-map tiles follow the
    hero vehicle; this bounds the initially loaded area, not scene quality.
    """
    world = client.get_world()
    require_idle_world(world)
    current = world.get_map().name.rsplit("/", 1)[-1]
    target = map_name.rsplit("/", 1)[-1]
    if target in LARGE_MAPS:
        original = world.get_settings()
        settings = world.get_settings()
        settings.spectator_as_ego = False
        settings.tile_stream_distance = 650.0
        settings.actor_active_distance = 350.0
        world.apply_settings(settings)
        if current != target:
            try:
                world = client.load_world(map_name, reset_settings=False, map_layers=carla.MapLayer.All)
            except Exception:
                client.set_timeout(5)
                cleanup_actions([("restore failed map-load settings", lambda: world.apply_settings(original))])
                raise
    elif current != target:
        world = client.load_world(map_name, map_layers=carla.MapLayer.All)
    elif target.endswith("_Opt"):
        world.load_map_layer(carla.MapLayer.All)
    return world


def warm_up_tiles(world, vehicle, client, carla, map_name=None):
    """Only initial hero spawning may need a long tile-load tick; never drive here."""
    name = (map_name if map_name is not None else world.get_map().name).rsplit("/", 1)[-1]
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
