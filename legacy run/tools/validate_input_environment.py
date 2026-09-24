"""Bounded live test of real CARLA neural inputs; no policy or dataset writes."""


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from runtime.paths import carla_root as get_carla_root
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from runtime.health import check_system_health
from simulation.environment import state_input_world, require_idle_world, paced_tick, cleanup_actions, prepare_state_world
from stack_supervisor import build_components, parse_args as supervisor_args, terminate_tree, tcp_probe
from simulation.observations import (make_observation)
from learning.contract import normalize_features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--carla-root', default=os.environ.get(
        'CARLA_ROOT', str(get_carla_root())))
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--port', type=int, default=2000)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 5:
        parser.error('--seconds must be finite and at least 5')
    verdict = check_system_health()
    if not verdict.safe:
        raise RuntimeError(verdict.reason)
    root = Path(__file__).resolve().parents[1]
    logs = root / 'logs'
    logs.mkdir(exist_ok=True)
    run_id = time.strftime('%Y%m%d-%H%M%S')
    report_path = logs / f'input-environment-{run_id}.json'
    report = {'passed': False, 'requested_seconds': args.seconds,
              'model_weights_changed': False, 'training_data_written': False}
    process = None
    log = None
    try:
        import carla
        sys.path.insert(0, str(Path(args.carla_root) / 'PythonAPI' / 'carla'))
        from agents.navigation.basic_agent import BasicAgent
        # Never replace an existing user's simulator during an unattended check.
        if tcp_probe('127.0.0.1', args.port, 1):
            raise RuntimeError('Close the existing CARLA session before this standalone check.')
        component = build_components(supervisor_args([
            '--carla-root', args.carla_root, '--rpc-port', str(args.port),
            '--render-api', 'dx11']))[0]
        log = (logs / f'input-environment-{run_id}-server.log').open('w')
        process = subprocess.Popen(component.argv, cwd=component.cwd, stdout=log,
            stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 180
        world = None
        print('Starting the camera-free input check...', flush=True)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('CARLA exited during startup')
            try:
                # A client whose initial episode query timed out can retain a
                # failed future; retry with a fresh connection during startup.
                client = carla.Client('127.0.0.1', args.port)
                client.set_timeout(2)
                client.get_server_version()
                client.set_timeout(45)
                world = client.get_world()
                break
            except RuntimeError:
                client.set_timeout(2)
                time.sleep(1)
        if world is None:
            raise RuntimeError('CARLA startup timed out')
        require_idle_world(world)
        report['startup_map'] = world.get_map().name
        client.set_timeout(45)
        world = prepare_state_world(client, carla, 'Town02_Opt')
        report['input_map'] = world.get_map().name
        if report['input_map'].rsplit('/', 1)[-1] != 'Town02_Opt':
            raise RuntimeError('CARLA did not load the requested input map')
        client.set_timeout(10)
        original = world.get_settings()
        with state_input_world(world, carla):
            world.unload_map_layer(carla.MapLayer.All)
            points = world.get_map().get_spawn_points()
            bp = world.get_blueprint_library().find('vehicle.ford.mustang')
            bp.set_attribute('role_name', 'input_validation')
            vehicle = world.try_spawn_actor(bp, points[0])
            if vehicle is None:
                raise RuntimeError('Could not spawn test vehicle')
            sensor = None
            try:
                vehicle.apply_control(carla.VehicleControl(brake=1))
                for _ in range(10):
                    paced_tick(world, 2)
                collided = []
                sensor = world.spawn_actor(world.get_blueprint_library().find(
                    'sensor.other.collision'), carla.Transform(), attach_to=vehicle)
                sensor.listen(lambda event: collided.append(event.frame))
                agent = BasicAgent(vehicle, target_speed=15, opt_dict={'dt': 0.05})
                agent.set_destination(max(points, key=lambda p: p.location.distance(
                    vehicle.get_location())).location)
                client.set_timeout(3)
                start = time.monotonic()
                initial = world.get_snapshot()
                previous_frame = initial.frame
                previous_location = vehicle.get_location()
                count, distance, maximum_speed = 0, 0.0, 0.0
                print('Reading real road, vehicle, obstacle and traffic-light inputs at 20 Hz.', flush=True)
                while time.monotonic() - start < args.seconds:
                    tick_start = time.monotonic()
                    if agent.done():
                        agent.set_destination(max(points, key=lambda p: p.location.distance(
                            vehicle.get_location())).location)
                    plan = list(agent.get_local_planner().get_plan())
                    reference = plan[min(3, len(plan)-1)][0] if plan else None
                    features = make_observation(vehicle, world, carla.TrafficLightState.Red,
                        target_speed_kmh=15, reference_waypoint=reference)
                    normalized = normalize_features(features)
                    if len(normalized) != 8 or not all(math.isfinite(v) for v in normalized):
                        raise RuntimeError('Invalid neural input vector')
                    vehicle.apply_control(agent.run_step())
                    frame = paced_tick(world, 2, tick_start)
                    if frame != previous_frame + 1:
                        raise RuntimeError('Another client advanced the simulation or a frame was lost')
                    previous_frame = frame
                    count += 1
                    location = vehicle.get_location()
                    distance += location.distance(previous_location)
                    previous_location = location
                    maximum_speed = max(maximum_speed, vehicle.get_velocity().length() * 3.6)
                    if collided:
                        raise RuntimeError('Validation vehicle collided')
                    if count % 400 == 0:
                        print(json.dumps({'elapsed_s': round(time.monotonic()-start, 1),
                            'valid_inputs': count, 'distance_m': round(distance, 1)}), flush=True)
                snapshot = world.get_snapshot()
                elapsed = time.monotonic() - start
                simulation_seconds = snapshot.timestamp.elapsed_seconds - initial.timestamp.elapsed_seconds
                cameras = len(world.get_actors().filter('sensor.camera.*'))
                settings = world.get_settings()
                report.update(duration_s=round(elapsed, 2), valid_input_vectors=count,
                    input_hz=round(count/elapsed, 2), distance_m=round(distance, 2),
                    peak_speed_kmh=round(maximum_speed, 2), cameras=cameras,
                    no_rendering_mode=settings.no_rendering_mode,
                    synchronous_mode=settings.synchronous_mode,
                    simulation_seconds=round(simulation_seconds, 2), collisions=len(collided))
                if (distance < 30 or cameras or not settings.no_rendering_mode or
                        abs(simulation_seconds - count * 0.05) > 0.1):
                    raise RuntimeError('Input environment acceptance checks failed')
            finally:
                actions = [('brake', lambda: vehicle.apply_control(carla.VehicleControl(brake=1)))]
                if sensor is not None:
                    actions += [('stop sensor', sensor.stop), ('destroy sensor', sensor.destroy)]
                actions.append(('destroy vehicle', vehicle.destroy))
                cleanup_actions(actions)
        remaining = [a.type_id for a in world.get_actors()
                     if a.type_id.startswith(('vehicle.', 'sensor.'))]
        restored = world.get_settings()
        report['remaining_actors'] = remaining
        report['settings_restored'] = all(getattr(restored, key) == getattr(original, key)
            for key in ('synchronous_mode', 'no_rendering_mode', 'fixed_delta_seconds'))
        if remaining or not report['settings_restored']:
            raise RuntimeError('Environment cleanup failed')
        report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        if process is not None:
            terminate_tree(process.pid)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                report['passed'] = False
                report['shutdown_error'] = 'Owned CARLA process did not exit'
        if log is not None:
            log.close()
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)
        print(f'Report: {report_path}', flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
