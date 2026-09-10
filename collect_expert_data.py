"""Collect CARLA BasicAgent demonstrations for Colab imitation learning.

Each route is written to a separate JSONL episode. The observation layout is
identical to neural_drive_agent.py and the action is the rule-based expert's
steering, accelerator, and brake command. This script collects labels only; it
does not train or overwrite a policy.
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

from policy_contract import POLICY_CONTRACT_VERSION


def choose_route(spawn_points, rng, minimum_distance_m):
    """Choose a start/destination pair far enough apart to be useful."""
    candidates = list(spawn_points)
    rng.shuffle(candidates)
    for start in candidates:
        destinations = list(candidates)
        rng.shuffle(destinations)
        for destination in destinations:
            if start.location.distance(destination.location) >= minimum_distance_m:
                return start, destination
    raise RuntimeError("Map has no spawn-point pair meeting the minimum route distance.")


def episode_rng(seed, episode_number):
    """Return a route RNG independent of earlier or interrupted episodes."""
    return random.Random(f"carla-route:{int(seed)}:{int(episode_number)}")


def run(args):
    carla_root = Path(args.carla_root).resolve()
    agents_root = carla_root / "PythonAPI" / "carla"
    if not agents_root.is_dir():
        raise FileNotFoundError(f"CARLA Python agents were not found at {agents_root}")
    sys.path.insert(0, str(agents_root))

    import carla
    from agents.navigation.basic_agent import BasicAgent

    from episode_recorder import EpisodeRecorder
    from neural_drive_agent import make_observation

    client = carla.Client(args.host, args.port)
    client.set_timeout(45.0)
    world = client.get_world()
    if args.map:
        current_map = world.get_map().name.rsplit("/", 1)[-1]
        requested_map = args.map.rsplit("/", 1)[-1]
        if current_map.lower() != requested_map.lower():
            world = client.load_world(args.map)

    map_name = world.get_map().name.rsplit("/", 1)[-1]
    spawn_points = world.get_map().get_spawn_points()
    if len(spawn_points) < 2:
        raise RuntimeError(f"{map_name} does not provide enough spawn points.")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    red_state = carla.TrafficLightState.Red
    completed = []

    for episode_number in range(args.start_episode, args.start_episode + args.episodes):
        start, destination = choose_route(
            spawn_points, episode_rng(args.seed, episode_number), args.minimum_route_m,
        )
        blueprint = world.get_blueprint_library().find(args.vehicle)
        blueprint.set_attribute("role_name", "expert")
        vehicle = world.try_spawn_actor(blueprint, start)
        if vehicle is None:
            print(json.dumps({"episode": episode_number, "status": "spawn_skipped"}), flush=True)
            continue

        collision_sensor = None
        recorder = None
        try:
            collision_bp = world.get_blueprint_library().find("sensor.other.collision")
            collision_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=vehicle)
            collided = {"value": False}
            collision_sensor.listen(lambda _: collided.__setitem__("value", True))

            agent = BasicAgent(vehicle, target_speed=args.target_speed_kmh,
                               opt_dict={"max_brake": 1.0})
            agent.set_destination(destination.location)
            route_id = f"expert-{map_name.lower()}-{args.seed}-{episode_number:03d}"
            recorder = EpisodeRecorder(output_dir, route_id)
            previous_location = vehicle.get_location()
            total_distance_m = 0.0
            started_at = time.monotonic()
            nearby = []

            for tick in range(args.max_ticks):
                if tick % 10 == 0:
                    nearby = list(world.get_actors().filter("vehicle.*"))
                local_plan = list(agent.get_local_planner().get_plan())
                reference_waypoint = (
                    local_plan[min(3, len(local_plan) - 1)][0]
                    if local_plan else None
                )
                observation = make_observation(
                    vehicle, world, red_state, nearby, target_speed_kmh=args.target_speed_kmh,
                    reference_waypoint=reference_waypoint,
                )
                expert_control = agent.run_step()
                action = {
                    "steering": float(expert_control.steer),
                    "accelerator": float(expert_control.throttle),
                    "brake": float(expert_control.brake),
                }
                vehicle.apply_control(expert_control)
                try:
                    world.wait_for_tick(seconds=args.tick_timeout)
                except RuntimeError as exc:
                    vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
                    raise RuntimeError(f"CARLA tick timeout: {exc}") from exc

                current_location = vehicle.get_location()
                total_distance_m += current_location.distance(previous_location)
                previous_location = current_location
                lane_departure = abs(observation[0]) > 2.0
                recorder.record(
                    observation,
                    action,
                    telemetry={
                        "speed_kmh": observation[2],
                        "obstacle_distance_m": observation[4],
                        "lane_error_m": observation[0],
                        "lane_departure": lane_departure,
                        "collision": collided["value"],
                        "distance_m": total_distance_m,
                        "elapsed_s": time.monotonic() - started_at,
                    },
                    event=["collision"] if collided["value"] else None,
                    metadata={
                        "source": "carla_basic_agent",
                        "map": map_name,
                        "route_id": route_id,
                        "target_speed_kmh": args.target_speed_kmh,
                        "route_conditioned": True,
                        "policy_contract_version": POLICY_CONTRACT_VERSION,
                        "weather": str(world.get_weather()),
                    },
                )

                if collided["value"] or agent.done():
                    break

            status = "collision" if collided["value"] else "complete" if agent.done() else "max_ticks"
            result = {"episode": episode_number, "status": status,
                      "path": str(recorder.path), "distance_m": round(total_distance_m, 1)}
            completed.append(result)
            print(json.dumps(result), flush=True)
        finally:
            if recorder is not None:
                recorder.close()
            if collision_sensor is not None:
                collision_sensor.stop()
                collision_sensor.destroy()
            vehicle.destroy()

    print(json.dumps({"finished": True, "episodes_written": len(completed),
                      "output_dir": str(output_dir)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record CARLA expert demonstrations for Colab.")
    parser.add_argument("--carla-root", default=r"C:\Users\medha\Documents\CARLA\CARLA_0.9.16")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map", default=None)
    parser.add_argument("--output-dir", default="episodes/expert")
    parser.add_argument("--episodes", type=int, default=12)
    parser.add_argument("--start-episode", type=int, default=1,
                        help="One-based episode number for deterministic resume")
    parser.add_argument("--max-ticks", type=int, default=2400)
    parser.add_argument("--target-speed-kmh", type=float, default=30.0)
    parser.add_argument("--minimum-route-m", type=float, default=150.0)
    parser.add_argument("--tick-timeout", type=float, default=2.0)
    parser.add_argument("--vehicle", default="vehicle.ford.mustang")
    parser.add_argument("--seed", type=int, default=7)
    run(parser.parse_args())
