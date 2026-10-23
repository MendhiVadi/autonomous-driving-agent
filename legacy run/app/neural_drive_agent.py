"""Dependency-light inference-only driving baseline for CARLA 0.9.16.

Training lives in the reviewed Colab pipeline; this process only loads a saved
policy and never changes its weights. Inputs are lane error, heading, speed,
target speed, front-obstacle distance, traffic-light state, curvature, and
stopped. This is a state-based baseline, not yet an end-to-end camera model.
"""
from runtime.paths import carla_root as get_carla_root

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from simulation.environment import (state_input_world,
                                    paced_tick, cleanup_actions, write_input_heartbeat,
                                    prepare_state_world)
from runtime.gesture import GestureBiasReceiver
from learning.contract import normalize_features


from learning.assistance import (clamp, apply_stall_recovery, is_stall_candidate,
                                 limit_neural_speed, apply_lane_assistance)
from learning.model import load_deployable_policy
from learning.checkpoints import evaluate_non_visual_checkpoints
from simulation.observations import make_observation


def run(args):
    if args.bootstrap_train:
        raise RuntimeError(
            "Training is disabled for this project. Remove --bootstrap-train and use the saved inference policy."
        )
    import carla
    import os
    os.environ["CARLA_ROOT"] = str(args.carla_root)
    from vehicle.control import ControlConfig, VehicleCommand
    from vehicle.transmission import (
        ManualTransmissionConfig,
        automatic_gear_for_speed,
        configure_vehicle_six_speed_physics,
        estimate_engine_rpm,
    )
    from vehicle.safety import SafetyLimits, SafetySupervisor
    from runtime.watchdog import CommandWatchdog
    from telemetry.recorder import EpisodeRecorder
    red_state = carla.TrafficLightState.Red
    policy_path = Path(args.policy)
    if not policy_path.is_file():
        raise FileNotFoundError(
            f"Deployable route-conditioned policy not found: {policy_path}. "
            "Export nn_policy_colab.json from the real-episode training pipeline "
            "and copy it to the driver folder."
        )
    # The live driver consumes route-relative observations.  Reject an
    # otherwise deployable artifact unless it was trained with the matching
    # route-conditioned contract.
    model = load_deployable_policy(policy_path, require_route_conditioned=True)
    client = carla.Client(args.host, args.port)
    client.set_timeout(45.0)
    world = prepare_state_world(client, carla, args.map)
    carla_map = world.get_map()
    with state_input_world(world, carla):
        blueprint = world.get_blueprint_library().find("vehicle.ford.mustang")
        blueprint.set_attribute("role_name", "hero")
        points = carla_map.get_spawn_points()
        random.shuffle(points)
        vehicle = None
        for point in points:
            vehicle = world.try_spawn_actor(blueprint, point)
            if vehicle is not None:
                break
        if vehicle is None:
            raise RuntimeError("Could not spawn the hero car; clear old actors or restart CARLA.")
        collision_sensor = None
        recorder = None
        command_watchdog = None
        gesture_receiver = None
        try:
            transmission_config = ManualTransmissionConfig()
            configure_vehicle_six_speed_physics(vehicle, carla, transmission_config)
            gesture_receiver = GestureBiasReceiver(
                args.gesture_host, args.gesture_port, args.gesture_stale_after,
            ) if args.gesture_port > 0 else None
            vehicle.apply_control(carla.VehicleControl(brake=1.0))
            # CARLA reports the origin until a newly spawned actor has ticked.
            for _ in range(10):
                paced_tick(world, args.tick_timeout)
            client.set_timeout(args.tick_timeout)
            collision_bp = world.get_blueprint_library().find("sensor.other.collision")
            collision_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=vehicle)
            collided = {"value": False}
            collision_sensor.listen(lambda _: collided.__setitem__("value", True))
            supervisor = SafetySupervisor(SafetyLimits(
                stale_command_after_s=args.command_timeout,
            ))
            command_watchdog = CommandWatchdog(timeout_s=args.command_timeout)

            def emergency_brake_on_stale_command():
                vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
                print(json.dumps({"safety_override": "stale_command",
                                  "command_age_s": command_watchdog.status()["command_age_s"]}),
                      flush=True)

            command_watchdog.start(emergency_brake_on_stale_command)
            if gesture_receiver is not None:
                gesture_receiver.start()
            recorder = EpisodeRecorder(args.record_dir) if args.record_dir else None
            print(json.dumps({"ready": True, "vehicle_id": vehicle.id, "policy": str(policy_path),
                              "policy_mode": "loaded",
                              "manual_model_contract": "manual_model_contract.json",
                              "environment": "state inputs, no rendering, fixed 20 Hz physics"}), flush=True)
            previous_steering_deg = 0.0
            previous_location = vehicle.get_location()
            total_distance_m = 0.0
            started_at = time.monotonic()
            stalled_since = None
            stall_recovery_active = False
            cached_nearby_vehicles = list(world.get_actors().filter("vehicle.*"))
            actor_refresh_every_ticks = 5  # traffic doesn't need a full RPC re-fetch every tick
            for tick in range(args.max_ticks):
                tick_started_at = time.monotonic()
                if tick % actor_refresh_every_ticks == 0:
                    cached_nearby_vehicles = list(world.get_actors().filter("vehicle.*"))
                features = make_observation(
                    vehicle, world, red_state, cached_nearby_vehicles,
                    target_speed_kmh=args.target_speed_kmh,
                    carla_map=carla_map,
                )
                prediction = model.predict(normalize_features(features))
                gesture_bias = gesture_receiver.snapshot() if gesture_receiver else None
                steering_bias = gesture_bias.steering if gesture_bias else 0.0
                accelerator_bias = gesture_bias.accelerator if gesture_bias else 0.0
                brake_bias = gesture_bias.brake if gesture_bias else 0.0
                accelerator = clamp(prediction[1] + accelerator_bias, 0.0, 1.0)
                brake = clamp(prediction[2] + brake_bias, 0.0, 1.0)
                recovery_candidate = is_stall_candidate(features[2], accelerator, brake)
                now = time.monotonic()
                if recovery_candidate:
                    stalled_since = stalled_since if stalled_since is not None else now
                elif not stall_recovery_active:
                    stalled_since = None
                stalled_for_s = 0.0 if stalled_since is None else now - stalled_since
                if args.disable_stall_recovery:
                    stall_recovery_active = False
                else:
                    accelerator, brake, stall_recovery_active = apply_stall_recovery(
                        features, accelerator, brake, stalled_for_s,
                        active=stall_recovery_active,
                        activation_delay_s=args.stall_recovery_after,
                        brake_override_delay_s=args.stall_recovery_brake_override_after,
                        max_accelerator=args.stall_recovery_max_accelerator,
                    )
                if not stall_recovery_active and not recovery_candidate:
                    stalled_since = None
                # VehicleControl must never receive meaningful accelerator and
                # brake together. Preserve braking only for a genuine stop request.
                lane_departure = abs(features[0]) > 2.0
                emergency_stop = features[5] > 0.7 or features[4] < 7.0 or lane_departure
                if not emergency_stop and brake < 0.45:
                    brake = 0.0
                else:
                    accelerator = 0.0
                command = VehicleCommand(
                    accelerator=accelerator,
                    brake=brake,
                    steering_angle_deg=clamp((prediction[0] + steering_bias) * 70.0, -70.0, 70.0),
                    gear=automatic_gear_for_speed(features[2], transmission_config),
                )
                safe_command, safety_reasons = supervisor.apply(command, {
                    "speed_kmh": features[2],
                    "obstacle_distance_m": features[4],
                    "lane_error_m": abs(features[0]),
                    "red_light": features[5] > 0.7,
                    "collision": collided["value"],
                    "command_age_s": command_watchdog.status()["command_age_s"],
                })
                vehicle.apply_control(safe_command.to_carla(ControlConfig()))
                command_watchdog.command_received()
                # Rendering and traffic can make a CARLA frame exceed 50 ms.
                try:
                    frame = paced_tick(world, args.tick_timeout, tick_started_at)
                    if tick % 20 == 0:
                        write_input_heartbeat(getattr(args, 'heartbeat_path', None), frame)
                except RuntimeError as exc:
                    cleanup_actions([("emergency brake", lambda: vehicle.apply_control(
                        carla.VehicleControl(brake=1.0, hand_brake=True)))])
                    print(json.dumps({"ready": False, "error": "CARLA tick timeout", "detail": str(exc)}),
                          flush=True)
                    raise RuntimeError("CARLA input stream stopped") from exc
                checkpoints, reinforcement = evaluate_non_visual_checkpoints(
                    features, command, collided["value"], previous_steering_deg
                )
                current_location = vehicle.get_location()
                progress_m = current_location.distance(previous_location)
                total_distance_m += progress_m
                previous_location = current_location
                previous_steering_deg = command.steering_angle_deg
                if tick % 10 == 0:
                    engine_rpm = estimate_engine_rpm(
                        features[2], command.gear, command.accelerator, command.clutch
                    )
                    print(json.dumps({"tick": tick, "speed_kmh": features[2],
                                      "engine_rpm_estimated": engine_rpm,
                                      "manual_gear": command.gear,
                                      "clutch": command.clutch,
                                      "obstacle_m": features[4],
                                      "raw_prediction": prediction,
                                      "control_mode": ("stall_recovery"
                                                       if stall_recovery_active
                                                       else "policy"),
                                      "gesture_output_bias": gesture_bias.as_dict() if gesture_bias else {},
                                      "action": {"accelerator": command.accelerator,
                                                 "brake": command.brake,
                                                 "steering_angle_deg": command.steering_angle_deg},
                                      "lane_error_m": features[0],
                                      "heading_error_deg": features[1],
                                      "collision": collided["value"],
                                      "non_visual_checkpoints": checkpoints,
                                      "checkpoints_passed": sum(checkpoints.values()),
                                      "checkpoint_count": len(checkpoints),
                                      "reinforcement": reinforcement,
                                      "progress_m": progress_m}), flush=True)
                if recorder:
                    lane_departure = abs(features[0]) > supervisor.limits.maximum_lane_error_m
                    recorder.record(features, safe_command.__dict__, {
                        "speed_kmh": features[2],
                        "obstacle_distance_m": features[4],
                        "lane_error_m": features[0],
                        "lane_departure": lane_departure,
                        "collision": collided["value"],
                        "distance_m": total_distance_m,
                        "elapsed_s": time.monotonic() - started_at,
                    }, event=safety_reasons or None)
                if collided["value"]:
                    vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
                    break
        finally:
            actions = []
            if gesture_receiver is not None:
                actions.append(("stop gesture input", gesture_receiver.stop))
            if command_watchdog is not None:
                actions.append(("stop command watchdog", command_watchdog.stop))
            if collision_sensor is not None:
                actions.extend([("stop collision sensor", collision_sensor.stop),
                                ("destroy collision sensor", collision_sensor.destroy)])
            actions.append(("destroy hero vehicle", vehicle.destroy))
            if recorder is not None:
                actions.append(("close recording", recorder.close))
            cleanup_actions(actions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--carla-root", default=str(get_carla_root()))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map", default=None,
                        help="Optional map switch; omitted for the stable already-loaded world")
    parser.add_argument("--policy", default="nn_policy_colab.json")
    parser.add_argument("--bootstrap-train", action="store_true",
                        help="Disabled safety guard; training requests exit without changing weights")
    parser.add_argument("--tick-timeout", type=float, default=2.0,
                        help="Maximum seconds to wait for each CARLA frame")
    parser.add_argument("--command-timeout", type=float, default=0.5,
                        help="Emergency-brake when command publication stalls")
    parser.add_argument("--target-speed-kmh", type=float, default=35.0)
    parser.add_argument("--stall-recovery-after", type=float, default=2.0,
                        help="Seconds stopped before safe rule-based progress assistance")
    parser.add_argument("--stall-recovery-max-accelerator", type=float, default=0.35,
                        help="Maximum accelerator allowed for stall recovery (max 0.5)")
    parser.add_argument("--stall-recovery-brake-override-after", type=float, default=5.0,
                        help="Seconds of clear standstill before releasing a stuck model brake")
    parser.add_argument("--disable-stall-recovery", action="store_true",
                        help="Use only the saved policy, even if it remains stopped")
    parser.add_argument("--max-ticks", type=int, default=3600)
    parser.add_argument("--record-dir", default=None,
                        help="Optional JSONL episode directory; does not train")
    parser.add_argument("--heartbeat-path", default=None,
                        help="Supervisor health file, updated only after an input/control tick")
    parser.add_argument("--gesture-host", default="127.0.0.1",
                        help="Loopback address for gesture bias UDP input")
    parser.add_argument("--gesture-port", type=int, default=8765,
                        help="Gesture bias UDP port; use 0 to disable")
    parser.add_argument("--gesture-stale-after", type=float, default=0.75,
                        help="Ignore gesture input older than this many seconds")
    run(parser.parse_args())
