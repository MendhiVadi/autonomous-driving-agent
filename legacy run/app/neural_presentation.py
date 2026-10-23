"""Record a real neural drive, capture its four views, and build a presentation."""
from runtime.paths import carla_root as get_carla_root

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import traceback

from runtime.health import check_system_health
from learning.model import (load_deployable_policy)
from simulation.observations import (make_observation)
from learning.assistance import (apply_stall_recovery)
from learning.contract import normalize_features
from simulation.environment import (prepare_state_world, state_input_world, paced_tick,
                                    cleanup_actions, require_idle_world)
from stack_supervisor import tcp_probe, terminate_tree, find_orphans

ROOT = Path(__file__).resolve().parent.parent
from runtime.paths import default_policy_path
DEFAULT_POLICY = default_policy_path()
VIEWS = ('front', 'rear', 'left', 'right')
FPS = 10
FRAME_DIR = 'camera-frames'


def save_json(path, payload):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def pose(transform):
    p, r = transform.location, transform.rotation
    return [p.x, p.y, p.z, r.pitch, r.yaw, r.roll]


def transform(carla, values):
    return carla.Transform(carla.Location(*values[:3]),
                           carla.Rotation(pitch=values[3], yaw=values[4], roll=values[5]))


def light_key(light):
    # Actor IDs change when a server/map restarts; world positions are stable.
    location = light.get_transform().location
    return ','.join(f'{value:.2f}' for value in (location.x, location.y, location.z))


def camera_world_pose(carla, ego_pose, relative_pose):
    import numpy as np
    matrix = np.array(transform(carla, ego_pose).get_matrix()) @ np.array(
        transform(carla, relative_pose).get_matrix())
    pitch = math.degrees(math.atan2(matrix[2, 0], math.hypot(matrix[0, 0], matrix[1, 0])))
    yaw = math.degrees(math.atan2(matrix[1, 0], matrix[0, 0]))
    roll = math.degrees(math.atan2(-matrix[2, 1], matrix[2, 2]))
    return transform(carla, [*matrix[:3, 3], pitch, yaw, roll])


@contextmanager
def server(args, output, stage):
    """Own only the server started here; leave existing sessions alone."""
    import carla
    verdict = check_system_health()
    if not verdict.safe:
        raise RuntimeError(verdict.reason)
    if find_orphans() or tcp_probe('127.0.0.1', args.port, 1):
        raise RuntimeError('Close the existing CARLA/driver session before this presentation.')
    argv = [str(Path(args.carla_root) / 'CarlaUE4.exe'), '-RenderOffScreen', '-dx11',
            '-quality-level=Low', '-nosound', '-NoVSync', '-NoBloom', '-NoMotionBlur',
            '-ResX=160', '-ResY=90', '-fps=20', '-unattended',
            f'-carla-rpc-port={args.port}',
            '-ExecCmds=t.MaxFPS 20,r.ViewDistanceScale 0.5,r.ShadowQuality 0,'
            'r.SSR.Quality 0,r.BloomQuality 0,r.MotionBlurQuality 0,'
            'r.VolumetricFog 0,foliage.DensityScale 0,grass.DensityScale 0']
    with (output / f'{stage}-server.log').open('w') as log:
        process = subprocess.Popen(argv, cwd=args.carla_root, stdout=log,
            stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 180
            while True:
                if process.poll() is not None:
                    raise RuntimeError('CARLA exited during startup; see the server log.')
                try:
                    client = carla.Client('127.0.0.1', args.port)
                    client.set_timeout(2)
                    client.get_server_version()
                    client.set_timeout(45)
                    world = client.get_world()
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('CARLA startup exceeded three minutes.')
                    time.sleep(1)
            yield client, world
        finally:
            terminate_tree(process.pid)
            process.wait(timeout=15)


def advance_route(route, location, index):
    end = min(index + 30, len(route))
    return min(range(index, end), key=lambda i: route[i][0].transform.location.distance(location))


def record_drive(args, output):
    import carla
    from vehicle.control import VehicleCommand, ControlConfig
    from vehicle.safety import SafetySupervisor, SafetyLimits
    from runtime.watchdog import CommandWatchdog
    from simulation.routes import plan_route

    model = load_deployable_policy(args.policy, require_route_conditioned=True)
    metadata = {'schema': 1, 'map': 'Town02_Opt', 'policy': str(args.policy),
        'policy_sha256': hashlib.sha256(Path(args.policy).read_bytes()).hexdigest(),
        'controller': 'neural policy with independent safety supervisor',
        'stall_recovery': not args.policy_only, 'traffic_vehicles': 0, 'physics_hz': 20,
        'capture_fps': FPS, 'vehicle': 'vehicle.ford.mustang', 'completed': False,
        'transmission': 'stock automatic, matching expert collection'}
    save_json(output / 'recording.json', metadata)
    print('Stage 1/3: recording the neural driver with cameras disabled.', flush=True)
    with server(args, output, 'drive') as (client, _):
        world = prepare_state_world(client, carla, metadata['map'])
        with state_input_world(world, carla):
            bp = world.get_blueprint_library().find(metadata['vehicle'])
            bp.set_attribute('role_name', 'neural_presentation')
            points = world.get_map().get_spawn_points()
            if not 0 <= args.spawn_index < len(points):
                raise ValueError(f'Spawn index must be between 0 and {len(points)-1}')
            car = world.try_spawn_actor(bp, points[args.spawn_index])
            if car is None:
                raise RuntimeError('Presentation spawn point is occupied.')
            sensor, watchdog = None, None
            try:
                car.apply_control(carla.VehicleControl(brake=1))
                for _ in range(10):
                    paced_tick(world, 3)
                destination = max(points, key=lambda p: p.location.distance(car.get_location()))
                route = plan_route(world, car.get_location(), destination.location)
                if len(route) < 6:
                    raise RuntimeError('No usable presentation route was found.')
                metadata['route'] = [pose(wp.transform)[:3] for wp, _ in route]
                metadata['spawn_index'] = args.spawn_index
                collided = []
                sensor = world.spawn_actor(world.get_blueprint_library().find(
                    'sensor.other.collision'), carla.Transform(), attach_to=car)
                sensor.listen(lambda event: collided.append(event.frame))
                safety = SafetySupervisor(SafetyLimits(max_speed_kmh=30, stale_command_after_s=0.5))
                watchdog = CommandWatchdog(0.5)
                watchdog.start(lambda: car.apply_control(carla.VehicleControl(brake=1, hand_brake=True)))
                client.set_timeout(3)
                distance, index, count = 0.0, 0, 0
                previous = car.get_location()
                reason = 'duration_reached'
                overrides = {}
                stalled_since, recovery_active, recovery_ticks = None, False, 0
                traffic_lights = [(light_key(light), light)
                    for light in world.get_actors().filter('traffic.traffic_light*')]
                with (output / 'trajectory.jsonl').open('w', encoding='utf-8') as stream:
                    for tick in range(round(args.seconds * 20)):
                        started = time.monotonic()
                        index = advance_route(route, car.get_location(), index)
                        features = make_observation(car, world, carla.TrafficLightState.Red,
                            [car], args.speed, route[min(index + 4, len(route)-1)][0])
                        if not all(math.isfinite(x) for x in features):
                            raise RuntimeError('Non-finite neural observation.')
                        prediction = model.predict(normalize_features(features))
                        if not all(math.isfinite(x) for x in prediction):
                            raise RuntimeError('Non-finite neural prediction.')
                        throttle = max(0., min(1., prediction[1]))
                        brake = max(0., min(1., prediction[2]))
                        now = time.monotonic()
                        if features[2] < 1 and throttle < 0.05:
                            stalled_since = now if stalled_since is None else stalled_since
                        elif not recovery_active:
                            stalled_since = None
                        if not args.policy_only:
                            throttle, brake, recovery_active = apply_stall_recovery(
                                features, throttle, brake,
                                0 if stalled_since is None else now-stalled_since,
                                active=recovery_active)
                        recovery_ticks += int(recovery_active)
                        # Use the existing headless driver's small-brake deadband.
                        emergency = features[5] > 0.7 or features[4] < 7 or abs(features[0]) > 2
                        if not emergency and brake < 0.45:
                            brake = 0.
                        else:
                            throttle = 0.
                        command = VehicleCommand(accelerator=throttle, brake=brake,
                            steering_angle_deg=max(-70., min(70., prediction[0]*70)), gear=1)
                        safe, reasons = safety.apply(command, {'speed_kmh': features[2],
                            'obstacle_distance_m': features[4], 'lane_error_m': abs(features[0]),
                            'red_light': bool(features[5]), 'collision': bool(collided),
                            'command_age_s': watchdog.status()['command_age_s']})
                        for item in reasons:
                            overrides[item] = overrides.get(item, 0) + 1
                        control = safe.to_carla(ControlConfig())
                        control.manual_gear_shift = False
                        car.apply_control(control)
                        watchdog.command_received()
                        frame = paced_tick(world, 3, started)
                        location = car.get_location()
                        distance += location.distance(previous)
                        previous = location
                        row = {'tick': tick, 'frame': frame, 'seconds': (tick+1)*0.05,
                            'pose': pose(car.get_transform()),
                            'speed_kmh': car.get_velocity().length()*3.6, 'distance_m': distance,
                            'observation': features, 'prediction': prediction,
                            'control_mode': 'stall_recovery' if recovery_active else 'policy',
                            'applied': safe.__dict__, 'safety': reasons,
                            'lights': [[key, int(light.get_state())] for key, light in traffic_lights]}
                        stream.write(json.dumps(row, allow_nan=False)+'\n')
                        stream.flush()
                        count += 1
                        if count % 100 == 0:
                            print(f'Neural drive: {count/20:.0f}s, {distance:.1f} m, '
                                  f'{row["speed_kmh"]:.1f} km/h', flush=True)
                        if collided or 'lane_departure' in reasons:
                            reason = 'collision' if collided else 'lane_departure'
                            break
                        if car.get_location().distance(destination.location) < 4:
                            reason = 'destination_reached'
                            break
                metadata.update(completed=True, ticks=count, seconds=count/20,
                    distance_m=distance, collisions=len(collided), stop_reason=reason,
                    safety_overrides=overrides, stall_recovery_ticks=recovery_ticks)
                save_json(output / 'recording.json', metadata)
                print(f'Recording saved: {distance:.1f} m; {reason}.', flush=True)
            finally:
                cleanup_actions(([('watchdog', watchdog.stop)] if watchdog else []) +
                    [('brake', lambda: car.apply_control(carla.VehicleControl(brake=1)))] +
                    ([('sensor stop', sensor.stop), ('sensor destroy', sensor.destroy)] if sensor else []) +
                    [('car', car.destroy)])
    return metadata


def read_recording(output):
    metadata = json.loads((output / 'recording.json').read_text(encoding='utf-8'))
    if not metadata.get('completed'):
        raise ValueError('Recording is incomplete; create a new neural drive first.')
    rows = [json.loads(line) for line in (output / 'trajectory.jsonl').read_text(encoding="utf-8").splitlines()]
    if len(rows) != metadata['ticks'] or not rows:
        raise ValueError('Recording frame count does not match its manifest.')
    return metadata, rows[1::2]  # Exact 10 Hz samples from the 20 Hz physics run.


def check_capture_manifest(output):
    payload = {'schema': 1, 'trajectory_sha256': hashlib.sha256(
        (output / 'trajectory.jsonl').read_bytes()).hexdigest(),
        'camera_size': [320, 180], 'fps': FPS, 'views': list(VIEWS), 'ego_body_rendered': False}
    path = output / 'capture-viewpoints.json'
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != payload:
        raise ValueError('Recording or capture settings changed; cached frames cannot be reused.')
    save_json(path, payload)


@contextmanager
def rendered_world(client, carla, map_name):
    """Render continuously; every captured scene is static and pose-verified."""
    require_idle_world(client.get_world())
    print('Loading the reduced visual map...', flush=True)
    world = client.load_world(map_name, reset_settings=True, map_layers=carla.MapLayer(
        carla.MapLayer.Buildings | carla.MapLayer.Ground | carla.MapLayer.Walls))
    original = world.get_settings()
    weather = world.get_weather()
    try:
        settings = world.get_settings()
        settings.no_rendering_mode = False
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = 0.05
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        world.apply_settings(settings)
        world.set_weather(carla.WeatherParameters(cloudiness=0, precipitation=0,
            precipitation_deposits=0, wind_intensity=0, fog_density=0, wetness=0,
            sun_altitude_angle=70, dust_storm=0))
        print('Visual map ready; creating the capture camera.', flush=True)
        yield world
    finally:
        cleanup_actions([('restore weather', lambda: world.set_weather(weather)),
                         ('restore settings', lambda: world.apply_settings(original))])


def capture_view(args, output, metadata, rows, view):
    """Render one camera per pass; poses are the recorded neural decisions."""
    import carla
    import cv2
    import numpy as np
    folder = output / FRAME_DIR / view
    folder.mkdir(parents=True, exist_ok=True)
    missing = [i for i in range(len(rows)) if not (folder / f'{i:06d}.png').is_file()]
    if not missing:
        print(f'{view}: using completed capture.', flush=True)
        return
    print(f'Stage 2/3: {view} camera ({len(missing)} frames remaining).', flush=True)
    with server(args, output, f'capture-{view}') as (client, _):
        with rendered_world(client, carla, metadata['map']) as world:
            camera = None
            try:
                poses = {'front': [0.65, 0, 1.62, -3, 0, 0],
                         'rear': [-2.4, 0, 1.25, -8, 180, 0],
                         'left': [0.5, -1.05, 1.3, -12, -100, 0],
                         'right': [0.5, 1.05, 1.3, -12, 100, 0]}
                camera_bp = world.get_blueprint_library().find('sensor.camera.rgb')
                for key, value in {'image_size_x': '320', 'image_size_y': '180',
                    'fov': '95', 'sensor_tick': '0.0', 'enable_postprocess_effects': 'false'}.items():
                    camera_bp.set_attribute(key, value)
                camera = world.spawn_actor(camera_bp, camera_world_pose(
                    carla, rows[missing[0]]['pose'], poses[view]))
                frames = queue.Queue(maxsize=8)
                def receive(image):
                    try:
                        frames.put_nowait(image)
                    except queue.Full:
                        pass
                camera.listen(receive)
                lights = {light_key(light): light
                    for light in world.get_actors().filter('traffic.traffic_light*')}
                for light in lights.values():
                    light.freeze(True)
                client.set_timeout(45)

                def render(row, startup=False):
                    for key, state in row['lights']:
                        if key not in lights:
                            raise RuntimeError('Recorded traffic lights do not match this map.')
                        lights[key].set_state(carla.TrafficLightState(state))
                    target = camera_world_pose(carla, row['pose'], poses[view])
                    camera.set_transform(target)
                    expected = world.get_snapshot().frame + 2
                    deadline = time.monotonic() + args.capture_timeout
                    # Continuous rendering avoids the local synchronous RGB
                    # stall. Require a fresh frame at the exact requested pose;
                    # no physics/traffic runs during this visual reconstruction.
                    while time.monotonic() < deadline:
                        try:
                            frame = frames.get(timeout=0.25)
                        except queue.Empty:
                            continue
                        actual = frame.transform
                        same_pose = actual.location.distance(target.location) < 0.02 and all(
                            abs((getattr(actual.rotation, axis)-getattr(target.rotation, axis)+180)%360-180) < 0.05
                            for axis in ('pitch', 'yaw', 'roll'))
                        if frame.frame >= expected and same_pose:
                            return np.frombuffer(frame.raw_data, dtype=np.uint8).reshape(
                                frame.height, frame.width, 4)[:, :, :3].copy()
                    raise RuntimeError(f'{view} camera stopped producing images; recording preserved.')

                # Warm the actual route's assets before capture, with bounded memory.
                print(f'{view}: warming route assets.', flush=True)
                first_image = render(rows[missing[0]], startup=True)
                cv2.imwrite(str(folder / f'{missing[0]:06d}.png'), first_image)
                print(f'{view}: first camera frame received.', flush=True)
                client.set_timeout(args.capture_timeout)
                for i in sorted(set([missing[0], *missing[::max(1, len(missing)//8)]])):
                    render(rows[i])
                for i in missing:
                    image = render(rows[i])
                    temporary = folder / f'{i:06d}.tmp.png'
                    if not cv2.imwrite(str(temporary), image):
                        raise RuntimeError('Could not save camera frame.')
                    temporary.replace(folder / f'{i:06d}.png')
                    if i % 50 == 0:
                        print(f'{view}: frame {i+1}/{len(rows)}', flush=True)
            finally:
                client.set_timeout(3)
                cleanup_actions(([('camera stop', camera.stop), ('camera destroy', camera.destroy)]
                    if camera else []))


def assemble(output, metadata, rows):
    import cv2
    import numpy as np
    destination = output / 'neural-presentation.mp4'
    temporary = output / 'neural-presentation.partial.mp4'
    writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (1280, 840))
    if not writer.isOpened():
        raise RuntimeError('MP4 encoder could not start.')
    try:
        for i, row in enumerate(rows):
            canvas = np.full((840, 1280, 3), (22, 18, 14), dtype=np.uint8)
            cv2.putText(canvas, 'NEURAL DRIVE | RECORDED PRESENTATION', (28, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (230, 240, 245), 2, cv2.LINE_AA)
            for j, view in enumerate(VIEWS):
                image = cv2.imread(str(output / FRAME_DIR / view / f'{i:06d}.png'))
                if image is None or image.shape != (180, 320, 3):
                    raise RuntimeError(f'Missing or invalid {view} frame {i}; resume capture.')
                x, y = (j % 2)*640, 50+(j//2)*360
                canvas[y:y+360, x:x+640] = cv2.resize(image, (640, 360))
                cv2.rectangle(canvas, (x, y), (x+150, y+30), (22, 18, 14), -1)
                cv2.putText(canvas, view.upper(), (x+12, y+22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (100, 230, 230), 1, cv2.LINE_AA)
            caption = f'{row["seconds"]:.1f}s   {row["speed_kmh"]:.1f} km/h   {row["distance_m"]:.1f} m'
            cv2.putText(canvas, caption, (28, 805), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (230, 240, 245), 1, cv2.LINE_AA)
            status = ', '.join(row['safety']) or ('Start assistance' if
                row.get('control_mode') == 'stall_recovery' else 'Neural policy + safety supervisor')
            cv2.putText(canvas, status, (650, 805), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (100, 230, 230), 1, cv2.LINE_AA)
            cv2.putText(canvas, 'Town02 | Preliminary model | No moving traffic | Actual recorded trajectory',
                (28, 833), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 170, 180), 1, cv2.LINE_AA)
            writer.write(canvas)
            if i == len(rows)//2:
                cv2.imwrite(str(output / 'preview.png'), canvas)
    finally:
        writer.release()
    video = cv2.VideoCapture(str(temporary))
    count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, _ = video.read()
    video.release()
    if not ok or count != len(rows):
        raise RuntimeError('Encoded video failed verification.')
    temporary.replace(destination)
    save_json(output / 'presentation.json', {'completed': True, 'video': str(destination),
        'frames': count, 'fps': FPS, 'seconds': count/FPS, 'views': list(VIEWS),
        'neural_distance_m': metadata['distance_m'], 'stop_reason': metadata['stop_reason']})
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carla-root', default=os.environ.get('CARLA_ROOT',
        str(get_carla_root())))
    parser.add_argument('--policy', type=Path, default=DEFAULT_POLICY)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--speed', type=float, default=15)
    parser.add_argument('--spawn-index', type=int, default=0)
    parser.add_argument('--port', type=int, default=2000)
    parser.add_argument('--capture-timeout', type=float, default=30,
        help='Maximum seconds to allow a slow offline rendering tick (5-45).')
    parser.add_argument('--resume', type=Path, help='Reuse a saved recording and completed camera frames.')
    parser.add_argument('--record-only', action='store_true')
    parser.add_argument('--policy-only', action='store_true',
        help='Disable the existing bounded stall recovery for model evaluation.')
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not 5 <= args.seconds <= 180:
        parser.error('--seconds must be between 5 and 180')
    if not math.isfinite(args.speed) or not 5 <= args.speed <= 25:
        parser.error('--speed must be between 5 and 25 km/h')
    if not math.isfinite(args.capture_timeout) or not 5 <= args.capture_timeout <= 45:
        parser.error('--capture-timeout must be between 5 and 45 seconds')
    os.environ["CARLA_ROOT"] = str(args.carla_root)
    output = args.resume.resolve() if args.resume else ROOT / 'exports' / (
        'neural-presentation-' + time.strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True, exist_ok=bool(args.resume))
    print(f'Presentation folder: {output}', flush=True)
    try:
        if not args.resume:
            record_drive(args, output)
        metadata, rows = read_recording(output)
        if args.record_only:
            return 0
        check_capture_manifest(output)
        for view in VIEWS:
            capture_view(args, output, metadata, rows, view)
        print('Stage 3/3: assembling and verifying the four-camera video.', flush=True)
        video = assemble(output, metadata, rows)
        print(f'Presentation ready: {video}', flush=True)
        if not args.no_open:
            os.startfile(str(video))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        save_json(output / 'failure.json', {'error': str(exc) or 'Interrupted',
            'traceback': traceback.format_exc(),
            'recording_preserved': (output / 'trajectory.jsonl').is_file()})
        print(f'Presentation stopped: {exc}', file=sys.stderr, flush=True)
        print(f'To resume: run_neural_presentation.cmd --resume "{output}"', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
