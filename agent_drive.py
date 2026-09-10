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

from control_policy import ControlConfig, VehicleCommand, action_vector
from manual_transmission import estimate_engine_rpm


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

    client = carla.Client(args.host, args.port)
    client.set_timeout(args.timeout)
    world = client.get_world()
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
    vehicle = next((world.try_spawn_actor(vehicle_bp, p) for p in points), None)
    if vehicle is None:
        raise RuntimeError("Could not spawn the hero vehicle; clear old actors or restart CARLA.")

    config = ControlConfig()
    print(json.dumps({"ready": True, "vehicle_id": vehicle.id,
                      "map": world.get_map().name,
                      "action_space": "[accelerator, brake, clutch, handbrake, wipers, steering_angle_deg, gear]"}), flush=True)
    try:
        for tick, line in enumerate(sys.stdin, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            command = VehicleCommand(
                accelerator=payload.get("accelerator", 0.0),
                brake=payload.get("brake", 0.0),
                clutch=payload.get("clutch", 0.0),
                hand_brake=payload.get("hand_brake", False),
                wipers=payload.get("wipers", False),
                steering_angle_deg=payload.get("steering_angle_deg", 0.0),
                gear=payload.get("gear", 1),
            ).sanitized(config)
            vehicle.apply_control(command.to_carla(config))
            world.wait_for_tick(seconds=args.timeout)
            result = telemetry(vehicle, world, tick, command)
            result["action"] = action_vector(command)
            print(json.dumps(result), flush=True)
    finally:
        vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
        vehicle.destroy()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}), file=sys.stderr, flush=True)
        raise SystemExit(1)
