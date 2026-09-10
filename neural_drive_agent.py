"""Dependency-light inference-only driving baseline for CARLA 0.9.16.

Training lives in the reviewed Colab pipeline; this process only loads a saved
policy and never changes its weights. Inputs are lane error, heading, speed,
target speed, front-obstacle distance, traffic-light state, curvature, and
stopped. This is a state-based baseline, not yet an end-to-end camera model.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from gesture_policy_bias import GestureBiasReceiver
from policy_contract import POLICY_CONTRACT_VERSION, POLICY_SIZES, normalize_features


def clamp(value, low, high):
    return max(low, min(high, float(value)))


def wrap_angle(angle):
    while angle > 180.0:
        angle -= 360.0
    while angle < -180.0:
        angle += 360.0
    return angle


def apply_stall_recovery(features, accelerator, brake, stalled_for_s,
                         active=False, activation_delay_s=2.0,
                         brake_override_delay_s=5.0, max_accelerator=0.35):
    """Add bounded forward progress only when the road state is clearly safe.

    The saved model remains the primary policy. Recovery activates only after a
    real standstill with no useful accelerator request, and immediately drops
    out for a red light, nearby obstacle, lane/heading error, model brake
    request, invalid state, or when the car reaches cruising speed.
    """
    try:
        lane, heading, speed, target, obstacle, red, _curvature, _stopped = (
            float(value) for value in features
        )
        accelerator = clamp(accelerator, 0.0, 1.0)
        brake = clamp(brake, 0.0, 1.0)
        stalled_for_s = max(0.0, float(stalled_for_s))
        max_accelerator = clamp(max_accelerator, 0.0, 0.5)
        finite = all(math.isfinite(value) for value in (
            lane, heading, speed, target, obstacle, red,
            accelerator, brake, stalled_for_s, max_accelerator,
        ))
    except (TypeError, ValueError):
        return accelerator, brake, False
    safe_gap_m = max(12.0, max(0.0, speed) / 3.6 * 2.0)
    clear_to_assist = (
        finite and target >= 5.0 and red < 0.5 and obstacle >= safe_gap_m
        and abs(lane) <= 1.0 and abs(heading) <= 15.0
    )
    if not clear_to_assist:
        return accelerator, brake, False
    release_speed = max(5.0, target * 0.85)
    if active and speed >= release_speed:
        return accelerator, brake, False
    # A brake request while moving is meaningful and must be respected. At a
    # prolonged, verified-clear standstill it is the known legacy-policy
    # failure mode, so recovery may release it after a longer delay.
    if brake >= 0.45 and speed >= 1.0:
        return accelerator, brake, False
    required_delay = (
        max(float(activation_delay_s), float(brake_override_delay_s))
        if brake >= 0.45 else max(0.0, float(activation_delay_s))
    )
    should_activate = (
        active or (
            speed < 1.0 and accelerator < 0.05
            and stalled_for_s >= required_delay
        )
    )
    if not should_activate:
        return accelerator, brake, False
    requested = clamp(
        (target - speed) / max(target, 1.0) * max_accelerator,
        0.12, max_accelerator,
    )
    return max(accelerator, requested), 0.0, True


class MLP:
    def __init__(self, sizes, seed=7):
        rng = random.Random(seed)
        self.sizes = sizes
        self.weights = []
        self.biases = []
        for left, right in zip(sizes, sizes[1:]):
            scale = math.sqrt(2.0 / left)
            self.weights.append([[rng.uniform(-scale, scale) for _ in range(left)] for _ in range(right)])
            self.biases.append([0.0] * right)

    def predict(self, values):
        layer = list(values)
        if len(layer) != self.sizes[0]:
            raise ValueError(f"Expected {self.sizes[0]} policy inputs, got {len(layer)}")
        for index, (weights, biases) in enumerate(zip(self.weights, self.biases)):
            layer = [sum(w * x for w, x in zip(row, layer)) + bias for row, bias in zip(weights, biases)]
            if index != len(self.weights) - 1:
                layer = [math.tanh(x) for x in layer]
        return layer

    def save(self, path):
        Path(path).write_text(json.dumps({"sizes": self.sizes, "weights": self.weights,
                                          "biases": self.biases}, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        sizes = payload.get("sizes")
        weights = payload.get("weights")
        biases = payload.get("biases")
        metadata = payload.get("training_metadata") or {}
        artifact_contract = metadata.get("policy_contract_version")
        if artifact_contract != POLICY_CONTRACT_VERSION:
            raise ValueError(
                f"Policy contract mismatch in {path}: artifact={artifact_contract}, "
                f"runtime={POLICY_CONTRACT_VERSION}"
            )
        if (not isinstance(sizes, list) or len(sizes) < 2 or
                any(not isinstance(size, int) or size <= 0 for size in sizes) or
                not isinstance(weights, list) or not isinstance(biases, list) or
                len(weights) != len(biases) or len(weights) != len(sizes) - 1):
            raise ValueError(f"Invalid policy structure in {path}")
        if sizes != POLICY_SIZES:
            raise ValueError(f"Unsupported policy sizes in {path}: {sizes}; expected {POLICY_SIZES}")
        for index, (layer, layer_biases) in enumerate(zip(weights, biases)):
            if (not isinstance(layer, list) or len(layer) != sizes[index + 1] or
                    not isinstance(layer_biases, list) or len(layer_biases) != sizes[index + 1] or
                    any(not isinstance(row, list) or len(row) != sizes[index] for row in layer)):
                raise ValueError(f"Invalid policy dimensions in {path} at layer {index}")
            values = [value for row in layer for value in row] + list(layer_biases)
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
                raise ValueError(f"Invalid policy values in {path} at layer {index}")
        model = cls(sizes)
        model.weights = weights
        model.biases = biases
        return model


def dot(a, b):
    return a.x * b.x + a.y * b.y + a.z * b.z


def make_observation(vehicle, world, red_state, nearby_vehicles=None,
                     target_speed_kmh=35.0, reference_waypoint=None):
    transform = vehicle.get_transform()
    location = transform.location
    waypoint = world.get_map().get_waypoint(location, project_to_road=True)
    if waypoint is None:
        raise RuntimeError("Vehicle is outside the drivable map; reset it to a road spawn point.")
    delta = location - waypoint.transform.location
    lateral = dot(delta, waypoint.transform.get_right_vector())
    if reference_waypoint is None:
        desired_heading = waypoint.transform.rotation.yaw
    else:
        reference_location = reference_waypoint.transform.location
        desired_heading = math.degrees(math.atan2(
            reference_location.y - location.y,
            reference_location.x - location.x,
        ))
    heading = wrap_angle(transform.rotation.yaw - desired_heading)
    velocity = vehicle.get_velocity()
    speed = math.sqrt(dot(velocity, velocity)) * 3.6
    if reference_waypoint is not None:
        curvature = wrap_angle(
            desired_heading - waypoint.transform.rotation.yaw,
        ) / 45.0
    else:
        next_points = waypoint.next(8.0)
        curvature = 0.0
        if next_points:
            curvature = wrap_angle(
                next_points[0].transform.rotation.yaw - waypoint.transform.rotation.yaw,
            ) / 45.0
    obstacle = 80.0
    forward = transform.get_forward_vector()
    if nearby_vehicles is None:
        nearby_vehicles = world.get_actors().filter("vehicle.*")
    for actor in nearby_vehicles:
        if actor.id != vehicle.id:
            relative = actor.get_location() - location
            if dot(relative, forward) <= 0:
                continue
            distance_squared = dot(relative, relative)
            if distance_squared < obstacle * obstacle:
                obstacle = math.sqrt(distance_squared)
    red = 1.0 if vehicle.get_traffic_light_state() == red_state else 0.0
    return [lateral, heading, speed, float(target_speed_kmh), obstacle, red,
            curvature, 1.0 if speed < 1.0 else 0.0]


def load_deployable_policy(path, require_route_conditioned=False):
    """Load only a real, explicitly deployable policy artifact."""
    policy_path = Path(path)
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    metadata = payload.get("training_metadata") or {}
    if metadata.get("deployable") is not True:
        raise ValueError(f"Policy is not marked deployable: {policy_path}")
    if require_route_conditioned and metadata.get("route_conditioned") is not True:
        raise ValueError(f"Policy is not route-conditioned: {policy_path}")
    return MLP.load(policy_path)


def evaluate_non_visual_checkpoints(features, command, collided, previous_steering_deg):
    """Score checks that can be evaluated without camera pixels.

    These checks are deliberately named and serialized so a future RL trainer
    can use them as shaped rewards instead of treating the score as a black
    box. A passing check gives positive reinforcement; safety failures carry
    larger penalties.
    """
    lane_error, heading, speed, target, obstacle, red, _curvature, _stopped = features
    speed_mps = speed / 3.6
    safe_gap = max(7.0, speed_mps * 1.2)
    checks = {
        "state_finite": all(math.isfinite(float(value)) for value in features),
        "lane_centered": abs(lane_error) <= 1.2,
        "heading_aligned": abs(heading) <= 12.0,
        "speed_suitable": speed <= target + 5.0 and (speed >= 1.0 or target <= 1.0),
        "safe_following_distance": obstacle >= safe_gap,
        "traffic_light_compliance": red < 0.5 or speed <= 1.5,
        "smooth_steering": abs(command.steering_angle_deg - previous_steering_deg) <= 22.0,
        "no_conflicting_controls": not (command.accelerator > 0.05 and command.brake > 0.05),
        "no_collision": not collided,
        "lane_safety": abs(lane_error) <= 2.0,
    }
    weights = {
        "state_finite": 0.25,
        "lane_centered": 0.35,
        "heading_aligned": 0.25,
        "speed_suitable": 0.25,
        "safe_following_distance": 0.50,
        "traffic_light_compliance": 0.75,
        "smooth_steering": 0.20,
        "no_conflicting_controls": 0.50,
        "no_collision": 2.00,
        "lane_safety": 1.00,
    }
    reward = sum(weights[name] if passed else -weights[name] for name, passed in checks.items())
    if all(checks.values()):
        reward += 1.0  # completion bonus when every non-visual point matches
    return checks, reward


def run(args):
    if args.bootstrap_train:
        raise RuntimeError(
            "Training is disabled for this project. Remove --bootstrap-train and use the saved inference policy."
        )
    import carla
    sys.path.insert(0, args.carla_root)
    from control_policy import ControlConfig, VehicleCommand
    from manual_transmission import (
        ManualTransmissionConfig,
        automatic_gear_for_speed,
        configure_vehicle_six_speed_physics,
        estimate_engine_rpm,
    )
    from safety_supervisor import SafetyLimits, SafetySupervisor
    from device_watchdog import CommandWatchdog
    from episode_recorder import EpisodeRecorder
    client = carla.Client(args.host, args.port)
    client.set_timeout(45.0)
    world = client.get_world()
    if args.map:
        current_map = world.get_map().name.rsplit("/", 1)[-1]
        requested_map = args.map.rsplit("/", 1)[-1]
        if current_map.lower() != requested_map.lower():
            world = client.load_world(args.map)
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
    blueprint = world.get_blueprint_library().find("vehicle.ford.mustang")
    blueprint.set_attribute("role_name", "hero")
    points = world.get_map().get_spawn_points()
    random.shuffle(points)
    vehicle = None
    for point in points:
        vehicle = world.try_spawn_actor(blueprint, point)
        if vehicle is not None:
            break
    if vehicle is None:
        raise RuntimeError("Could not spawn the hero car; clear old actors or restart CARLA.")
    transmission_config = ManualTransmissionConfig()
    configure_vehicle_six_speed_physics(vehicle, carla, transmission_config)
    collision_sensor = None
    recorder = None
    command_watchdog = None
    gesture_receiver = GestureBiasReceiver(
        args.gesture_host, args.gesture_port, args.gesture_stale_after,
    ) if args.gesture_port > 0 else None
    try:
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
                          "note": "legacy state baseline loaded; manual-gear training is not started"}), flush=True)
        previous_steering_deg = 0.0
        previous_location = vehicle.get_location()
        total_distance_m = 0.0
        started_at = time.monotonic()
        stalled_since = None
        stall_recovery_active = False
        cached_nearby_vehicles = list(world.get_actors().filter("vehicle.*"))
        actor_refresh_every_ticks = 5  # traffic doesn't need a full RPC re-fetch every tick
        for tick in range(args.max_ticks):
            if tick % actor_refresh_every_ticks == 0:
                cached_nearby_vehicles = list(world.get_actors().filter("vehicle.*"))
            features = make_observation(
                vehicle, world, red_state, cached_nearby_vehicles,
                target_speed_kmh=args.target_speed_kmh,
            )
            prediction = model.predict(normalize_features(features))
            gesture_bias = gesture_receiver.snapshot() if gesture_receiver else None
            steering_bias = gesture_bias.steering if gesture_bias else 0.0
            accelerator_bias = gesture_bias.accelerator if gesture_bias else 0.0
            brake_bias = gesture_bias.brake if gesture_bias else 0.0
            accelerator = clamp(prediction[1] + accelerator_bias, 0.0, 1.0)
            brake = clamp(prediction[2] + brake_bias, 0.0, 1.0)
            recovery_candidate = features[2] < 1.0 and accelerator < 0.05
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
                world.wait_for_tick(seconds=args.tick_timeout)
            except RuntimeError as exc:
                vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True))
                print(json.dumps({"ready": False, "error": "CARLA tick timeout", "detail": str(exc)}),
                      flush=True)
                break
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
        if gesture_receiver is not None:
            gesture_receiver.stop()
        if command_watchdog is not None:
            command_watchdog.stop()
        if collision_sensor is not None:
            collision_sensor.stop()
            collision_sensor.destroy()
        vehicle.destroy()
        if recorder:
            recorder.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--carla-root", default=r"C:\Users\medha\Documents\CARLA\CARLA_0.9.16")
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
    parser.add_argument("--gesture-host", default="127.0.0.1",
                        help="Loopback address for gesture bias UDP input")
    parser.add_argument("--gesture-port", type=int, default=8765,
                        help="Gesture bias UDP port; use 0 to disable")
    parser.add_argument("--gesture-stale-after", type=float, default=0.75,
                        help="Ignore gesture input older than this many seconds")
    run(parser.parse_args())
