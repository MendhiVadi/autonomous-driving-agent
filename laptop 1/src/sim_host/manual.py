"""One manual car in the native CARLA viewport; no camera sensors or model."""
import argparse
import ctypes
from ctypes import wintypes
import json
import math
import time

from sim_host.watchdog import CommandWatchdog
from sim_host.profiles import PRESENTATION
from sim_host.world import load_map, cleanup_actions, warm_up_tiles, create_client


class ViewportKeyboard:
    """Read controls only while a window owned by this simulator has focus."""
    def __init__(self, server_pids):
        self.server_pids = set(server_pids)
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short

    def focused(self):
        process = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(self.user32.GetForegroundWindow(), ctypes.byref(process))
        return process.value in self.server_pids

    def down(self, *keys):
        return any(self.user32.GetAsyncKeyState(key) & 0x8000 for key in keys)


def steering_step(previous, direction, dt):
    try:
        valid = all(not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) for value in (previous, direction, dt))
    except OverflowError:
        valid = False
    if not valid or direction not in (-1, 0, 1) or dt < 0:
        raise ValueError("Steering needs finite values, direction -1/0/1 and non-negative dt")
    previous = max(-0.7, min(0.7, previous))
    step = min(dt, 0.1) * 1.5
    if direction:
        return max(-0.7, min(0.7, previous + direction * step))
    return math.copysign(max(0.0, abs(previous) - step * 2.0), previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', default='Town02_Opt')
    parser.add_argument('--server-pids', type=int, nargs='+', required=True)
    parser.add_argument('--max-runtime-seconds', type=float, default=0)
    parser.add_argument('--spawn-index', type=int, default=0)
    parser.add_argument('--no-input', action='store_true', help='Hold brakes for a bounded diagnostic')
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_runtime_seconds) or args.max_runtime_seconds < 0:
        parser.error('Runtime must be finite and non-negative')
    import carla
    client = create_client(carla)
    client.set_timeout(120)
    world = load_map(client, args.map, carla)
    map_data = world.get_map()
    print(f'[map] Loaded {map_data.name}; native client {client.get_client_version()}', flush=True)
    original_settings, original_weather = world.get_settings(), world.get_weather()
    vehicle = None
    watchdog = CommandWatchdog(timeout_s=0.75)
    try:
        settings = world.get_settings()
        settings.no_rendering_mode = False
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 1.0 / PRESENTATION.fps
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        world.apply_settings(settings)
        world.set_weather(carla.WeatherParameters(
            cloudiness=20, precipitation=0, precipitation_deposits=0,
            wind_intensity=PRESENTATION.wind, sun_altitude_angle=45, fog_density=0, wetness=0))
        blueprint = world.get_blueprint_library().find('vehicle.ford.mustang')
        blueprint.set_attribute('role_name', 'hero')
        spawn_points = map_data.get_spawn_points()
        if not 0 <= args.spawn_index < len(spawn_points):
            raise ValueError('Spawn index is outside this map')
        for spawn in spawn_points[args.spawn_index:] + spawn_points[:args.spawn_index]:
            vehicle = world.try_spawn_actor(blueprint, spawn)
            if vehicle is not None:
                break
        if vehicle is None:
            raise RuntimeError('No free vehicle spawn point')
        warm_up_tiles(world, vehicle, client, carla, map_data.name)
        brake = lambda: vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
        watchdog.start(brake)
        keyboard = ViewportKeyboard(args.server_pids)
        spectator = world.get_spectator()
        client.set_timeout(3)
        reverse, bonnet, steer = False, False, 0.0
        previous_r, previous_c = False, False
        started = previous_time = last_report = time.monotonic()
        frames = 0
        print('[scenic] one car; native viewport; Epic scenery; wind=65; no sensors or neural model', flush=True)
        print('[scenic] Click CARLA. WASD/arrows drive; Space handbrake; R reverse; C view; Esc exit.', flush=True)
        while not args.max_runtime_seconds or time.monotonic() - started < args.max_runtime_seconds:
            tick_started = time.monotonic()
            dt, previous_time = tick_started - previous_time, tick_started
            focused = not args.no_input and keyboard.focused()
            velocity = vehicle.get_velocity()
            speed = math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) * 3.6
            r, c = focused and keyboard.down(0x52), focused and keyboard.down(0x43)
            if r and not previous_r and speed < 1:
                reverse = not reverse
            if c and not previous_c:
                bonnet = not bonnet
            previous_r, previous_c = r, c
            if focused and keyboard.down(0x1B):
                break
            direction = (int(keyboard.down(0x44, 0x27)) - int(keyboard.down(0x41, 0x25))) if focused else 0
            steer = steering_step(steer, direction, dt)
            braking = not focused or keyboard.down(0x53, 0x28)
            throttle = 0.65 if focused and not braking and keyboard.down(0x57, 0x26) else 0.0
            control = carla.VehicleControl(throttle=throttle, brake=float(braking), steer=steer,
                                          reverse=reverse, hand_brake=focused and keyboard.down(0x20))
            vehicle.apply_control(control)
            watchdog.command_received()
            world.tick(3)
            transform = vehicle.get_transform()
            forward = transform.get_forward_vector()
            offset, height, pitch = (1.0, 1.35, -3) if bonnet else (-7.0, 3.2, -12)
            spectator.set_transform(carla.Transform(
                transform.location + carla.Location(x=forward.x * offset, y=forward.y * offset, z=height),
                carla.Rotation(pitch=pitch, yaw=transform.rotation.yaw)))
            frames += 1
            if tick_started - last_report >= 5:
                print('[scenic] ' + json.dumps({'fps': round(frames / (tick_started - last_report), 1),
                    'speed_kmh': round(speed, 1), 'focused': focused,
                    'view': 'bonnet' if bonnet else 'chase', 'gear': 'R' if reverse else 'D'}), flush=True)
                last_report, frames = tick_started, 0
            time.sleep(max(0, 1.0 / PRESENTATION.fps - (time.monotonic() - tick_started)))
    finally:
        actions = [('stop watchdog', watchdog.stop)]
        if vehicle is not None:
            actions.extend([('brake', lambda: vehicle.apply_control(carla.VehicleControl(brake=1))),
                            ('destroy vehicle', vehicle.destroy)])
        actions.extend([('restore weather', lambda: world.set_weather(original_weather)),
                        ('restore settings', lambda: world.apply_settings(original_settings))])
        cleanup_actions(actions)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
