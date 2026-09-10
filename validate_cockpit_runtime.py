"""Bounded simulator/camera regression; rule-based test driver, no model writes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(os.environ.get('CARLA_ROOT', r'C:\Users\medha\Documents\CARLA\CARLA_0.9.16'))))
import carla
from manual_transmission import automatic_gear_for_speed
from route_planner import _load_agents


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--map', default='Town05')
    parser.add_argument('--label', default='crash-validation')
    parser.add_argument('--camera-profile', choices=['parking', 'map'], default='parking')
    parser.add_argument('--driver', choices=['route', 'shakedown'], default='shakedown')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    carla_root = Path(os.environ.get('CARLA_ROOT', r'C:\Users\medha\Documents\CARLA\CARLA_0.9.16'))
    client = carla.Client('127.0.0.1', 2000)
    client.set_timeout(45)
    world = client.get_world()
    if any(a.type_id.startswith(('vehicle.', 'sensor.')) for a in world.get_actors()):
        raise RuntimeError('Validation needs an empty server; existing actors were preserved.')
    if world.get_map().name.rsplit('/', 1)[-1] != args.map:
        world = client.load_world(args.map)
    road_map = world.get_map()
    points = road_map.get_spawn_points()
    def straight_length(point):
        waypoint = road_map.get_waypoint(point.location)
        yaw = waypoint.transform.rotation.yaw
        length = 0
        for _ in range(40):
            options = waypoint.next(5)
            if not options:
                break
            waypoint = options[0]
            turn = abs((waypoint.transform.rotation.yaw - yaw + 180) % 360 - 180)
            if waypoint.is_junction or turn > 3:
                break
            length += 5
        return length
    spawn_index = max(range(len(points)), key=lambda i: straight_length(points[i]))
    log_path = root / 'logs' / (args.label + '.log')
    # Render the same UI into an off-screen SDL surface so manual key presses
    # cannot reset the car or close an unattended regression halfway through.
    env = dict(os.environ, PYTHONPATH=str(root) + os.pathsep + str(carla_root),
               SDL_VIDEODRIVER='dummy')
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([
            sys.executable, '-u', str(carla_root / 'spawn_car.py'),
            '--map', args.map, '--camera-profile', args.camera_profile, '--target-fps', '20',
            '--spawn-index', str(spawn_index),
            '--camera-fps', '4', '--mirror-camera-fps', '2', '--agent-stdin',
            '--agent-timeout', '0.5', '--max-runtime-seconds', str(args.seconds),
            '--screenshot-path', str(root / 'logs' / (args.label + '.png')),
        ], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            text=True, env=env, cwd=root)
        try:
            deadline = time.monotonic() + 100
            vehicle = None
            while time.monotonic() < deadline and process.poll() is None:
                world = client.get_world()
                heroes = [v for v in world.get_actors().filter('vehicle.*')
                          if v.attributes.get('role_name') == 'hero']
                expected_cameras = 0 if args.camera_profile == 'map' else 4
                if (heroes and len(world.get_actors().filter('sensor.camera.rgb')) == expected_cameras
                        and world.get_actors().filter('sensor.other.collision')):
                    vehicle = heroes[0]
                    break
                time.sleep(0.5)
            if vehicle is None:
                raise RuntimeError('Cockpit never finished creating its actors; inspect ' + str(log_path))
            client.set_timeout(3)
            if args.driver == 'route':
                _load_agents()
                from agents.navigation.basic_agent import BasicAgent
                agent = BasicAgent(vehicle, target_speed=40)
                destination = max(points, key=lambda p: p.location.distance(vehicle.get_location()))
                agent.set_destination(destination.location)
            started = time.monotonic()
            start_sim_time = world.get_snapshot().timestamp.elapsed_seconds
            start_world_frame = world.get_snapshot().frame
            previous = vehicle.get_location()
            distance = 0.0
            max_speed = 0.0
            ticks = 0
            frames = set()
            while process.poll() is None:
                if time.monotonic() - started > args.seconds + 20:
                    raise RuntimeError('Cockpit exceeded its runtime deadline')
                try:
                    location = vehicle.get_location()
                    speed = vehicle.get_velocity().length() * 3.6
                    displacement = location.distance(previous)
                    if displacement < 10.0:  # Exclude reset/destruction jumps.
                        distance += displacement
                    previous = location
                    max_speed = max(max_speed, speed)
                    if args.driver == 'route' and agent.done():
                        destination = max(points, key=lambda p: p.location.distance(location))
                        agent.set_destination(destination.location)
                    if args.driver == 'route':
                        control = agent.run_step()
                        command = dict(accelerator=control.throttle, brake=control.brake,
                                       steering_angle_deg=control.steer * 70,
                                       gear=automatic_gear_for_speed(speed), clutch=0,
                                       hand_brake=False)
                    else:
                        # Exercise accelerator, brakes and both travel directions
                        # on one straight stretch, without testing a route policy.
                        phase = (time.monotonic() - started) % 26
                        moving = phase < 10 or 13 <= phase < 23
                        command = dict(accelerator=min(0.3, max(0.0, (8-speed)*0.1)) if moving else 0,
                                       brake=(0.15 if speed > 8.5 else 0) if moving else 1,
                                       steering_angle_deg=0, gear=1 if phase < 13 else -1,
                                       clutch=0, hand_brake=False)
                    process.stdin.write(json.dumps(command) + '\n')
                    process.stdin.flush()
                    frames.add(world.get_snapshot().frame)
                    ticks += 1
                    if ticks % 200 == 0:
                        print(json.dumps(dict(elapsed=round(time.monotonic()-started),
                                              distance_m=round(distance), max_speed_kmh=round(max_speed,1))), flush=True)
                    time.sleep(0.05)
                except (BrokenPipeError, RuntimeError):
                    # Normal cleanup may destroy the hero just before the child exits.
                    if process.wait(timeout=8) != 0:
                        raise
                    break
            code = process.wait(timeout=8)
            remaining = [a.type_id for a in world.get_actors()
                         if a.type_id.startswith(('vehicle.', 'sensor.'))]
            report = dict(exit_code=code, duration_s=round(time.monotonic()-started,1),
                          distance_m=round(distance,1), max_speed_kmh=round(max_speed,1),
                          unique_world_frames=len(frames), remaining_actors=remaining,
                          driver=args.driver, spawn_index=spawn_index,
                          simulation_seconds=round(world.get_snapshot().timestamp.elapsed_seconds-start_sim_time,1),
                          world_frame_advance=world.get_snapshot().frame-start_world_frame,
                          log=str(log_path))
            (root / 'logs' / (args.label + '.json')).write_text(json.dumps(report, indent=2))
            print(json.dumps(report), flush=True)
            if code or distance < 30 or remaining or report['duration_s'] < args.seconds - 15:
                raise RuntimeError('Runtime validation failed: ' + json.dumps(report))
        finally:
            if process.poll() is None:
                # Kill the Python redirector and its child together on Windows.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)


if __name__ == '__main__':
    main()
