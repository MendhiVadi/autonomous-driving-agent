"""Terminal-controlled single CARLA vehicle.

Send one JSON action per line on stdin. One telemetry JSON object is printed
after every action. This makes the client usable by a neural-network process
without keyboard automation or GUI scraping.

Example action:
{"accelerator":0.35,"brake":0,"clutch":0,"hand_brake":false,"wipers":true,"steering_angle_deg":-8,"gear":1}
"""
import argparse
import json
import random
import sys

import carla

from vehicle.control import ControlConfig, VehicleCommand, action_vector
from vehicle.transmission import estimate_engine_rpm
from runtime.watchdog import CommandWatchdog
from vehicle.safety import SafetySupervisor, SafetyLimits
from simulation.observations import (make_observation)
from simulation.environment import require_idle_world, cleanup_actions


def command_from_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("A control action must be a JSON object")
    allowed = set(VehicleCommand.__dataclass_fields__)
    if set(payload) - allowed:
        raise ValueError("Unknown control fields")
    for name, value in payload.items():
        if name in ("hand_brake", "wipers"):
            if not isinstance(value, bool):
                raise ValueError("Control flags must be booleans")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Controls must be numeric")
    return VehicleCommand(**payload).sanitized()



def telemetry(vehicle, world, tick, command=None):
    velocity = vehicle.get_velocity()
    speed_mps = (velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) ** 0.5
    transform = vehicle.get_transform()
    command = command or VehicleCommand(gear=vehicle.get_control().gear)
    return {
        "tick": tick,
        "vehicle_id": vehicle.id,
        "map": world.get_map().name,
        "x": transform.location.x,
        "y": transform.location.y,
        "z": transform.location.z,
        "yaw_deg": transform.rotation.yaw,
        "speed_kmh": speed_mps * 3.6,
        "engine_rpm_estimated": estimate_engine_rpm(
            speed_mps * 3.6, command.gear, command.accelerator, command.clutch
        ),
        "manual_gear": command.gear,
        "clutch": command.clutch,
        "acceleration_mps2": vehicle.get_acceleration().length(),
        "action_space": "[accelerator, brake, clutch, handbrake, wipers, steering_angle_deg, gear]",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map", default=None)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    import math
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
    require_idle_world(world)
    if args.map:
        current_map = world.get_map().name.rsplit("/", 1)[-1]
        requested_map = args.map.rsplit("/", 1)[-1]
        if current_map.lower() != requested_map.lower():
            world = client.load_world(args.map)
    blueprints = world.get_blueprint_library()
    vehicle_bp = blueprints.find("vehicle.ford.mustang")
    vehicle_bp.set_attribute("role_name", "hero")
    points = world.get_map().get_spawn_points()
    random.shuffle(points)
    vehicle = None
    for point in points:
        vehicle = world.try_spawn_actor(vehicle_bp, point)
        if vehicle is not None:
            break
    if vehicle is None:
        raise RuntimeError("Could not spawn the hero vehicle; clear old actors or restart CARLA.")

    config = ControlConfig()
    collision = {"value": False}
    sensor = None
    watchdog = CommandWatchdog(timeout_s=0.25)
    safety = SafetySupervisor(SafetyLimits(stale_command_after_s=0.25))
    try:
        client.set_timeout(min(args.timeout, 2.0))
        vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
        sensor = world.spawn_actor(blueprints.find("sensor.other.collision"), carla.Transform(), attach_to=vehicle)
        sensor.listen(lambda _event: collision.update(value=True))
        watchdog.start(lambda: vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True)))
        watchdog.command_received()
        print(json.dumps({"ready": True, "vehicle_id": vehicle.id, "map": world.get_map().name}), flush=True)
        tick = 0
        while True:
            line = sys.stdin.readline(16385)
            if not line:
                break
            if len(line) > 16384:
                raise ValueError("Control action exceeds 16 KiB")
            if not line.strip():
                continue
            command = command_from_payload(json.loads(line))
            features = make_observation(vehicle, world, carla.TrafficLightState.Red)
            command, reasons = safety.apply(command, {
                "speed_kmh": features[2], "obstacle_distance_m": features[4],
                "lane_error_m": features[0], "command_age_s": 0.0,
                "red_light": bool(features[5]), "collision": collision["value"],
            })
            vehicle.apply_control(command.to_carla(config))
            watchdog.command_received()
            world.wait_for_tick(seconds=min(args.timeout, 2.0))
            tick += 1
            result = telemetry(vehicle, world, tick, command)
            result["action"] = action_vector(command)
            result["safety_reasons"] = reasons
            print(json.dumps(result, allow_nan=False), flush=True)
    finally:
        actions = [("stop watchdog", watchdog.stop),
                   ("emergency brake", lambda: vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True)))]
        if sensor is not None:
            actions.extend([("stop collision sensor", sensor.stop), ("destroy collision sensor", sensor.destroy)])
        actions.append(("destroy terminal vehicle", vehicle.destroy))
        cleanup_actions(actions)



if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}), file=sys.stderr, flush=True)
        raise SystemExit(1)
