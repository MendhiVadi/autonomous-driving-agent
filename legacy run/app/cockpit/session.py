"""Stability-first CARLA parking cockpit with HUD and local minimap."""
import ctypes
import json
import math
import os
import queue
import random
import sys
import threading
import time
from pathlib import Path

import carla
from vehicle.control import ControlConfig, VehicleCommand
from telemetry.recorder import EpisodeRecorder
from simulation.observations import (make_observation)
from learning.assistance import (apply_stall_recovery, is_stall_candidate, limit_neural_speed, apply_lane_assistance)
from learning.contract import POLICY_CONTRACT_VERSION, normalize_features
from vehicle.safety import SafetyLimits, SafetySupervisor
from runtime.watchdog import CommandWatchdog
from simulation.environment import require_idle_world, cleanup_actions
from simulation.roads import build_road_segments, RoadSegmentIndex
from vehicle.transmission import (
    EngineRpmEstimator,
    ManualTransmissionConfig,
    automatic_gear_for_speed,
    gear_redline_speed_kmh,
    manual_gear_name,
    recommended_shift,
    selector_name,
)


from cockpit.options import parse_args
from cockpit.input import (HeldKeyState, build_vehicle_control, can_change_gear,
                           automatic_route_gear, gearbox_state_matches)
from cockpit.graphics import (apply_turn_stability, apply_speed_sensitive_steering,
    apply_scene_streaming_limit, format_speed_kmh, apply_graphics_throttle_neck,
    configure_six_speed_physics, reduced_motion_weather, visual_austerity_transition)
from cockpit.navigation import (segment_intersects_local_radius, map_bounds_from_segments,
    world_to_map_pixel, map_pixel_to_world, make_neural_route_planner, plan_neural_route,
    load_deployable_route_policy, advance_route_index)
from cockpit.world import vehicle_speed_kmh, nearest_distances, try_spawn_vehicle


def main():
    args = parse_args()
    try:
        import pygame
    except ImportError:
        raise SystemExit("pygame is required: python -m pip install pygame")

    client = carla.Client(args.host, args.port)
    # Map loading can exceed ten seconds on the low-power/low-quality setup.
    # Keep the client alive long enough for Town05 to finish switching.
    client.set_timeout(45.0)
    print("[startup] CARLA client connected", flush=True)
    world = client.get_world()
    require_idle_world(world)
    if args.map:
        current_map = world.get_map().name.rsplit("/", 1)[-1]
        requested_map = args.map.rsplit("/", 1)[-1]
        if current_map.lower() != requested_map.lower():
            print(f"[startup] loading map {requested_map}", flush=True)
            if args.low_scenery and requested_map.endswith("_Opt"):
                layers = (carla.MapLayer.Buildings | carla.MapLayer.Ground |
                          carla.MapLayer.ParkedVehicles |
                          carla.MapLayer.Walls)
                world = client.load_world(args.map, map_layers=carla.MapLayer(layers))
            else:
                world = client.load_world(args.map)
    if args.low_scenery:
        if world.get_map().name.endswith("_Opt"):
            world.unload_map_layer(carla.MapLayer(
                carla.MapLayer.Foliage | carla.MapLayer.Particles | carla.MapLayer.Props |
                carla.MapLayer.StreetLights | carla.MapLayer.Decals))
        world.set_weather(carla.WeatherParameters(
            cloudiness=0.0, precipitation=0.0, precipitation_deposits=0.0,
            wind_intensity=0.0, fog_density=0.0, wetness=0.0,
            sun_altitude_angle=70.0, dust_storm=0.0))
        print("[startup] low scenery: no foliage; clear dry daylight; no weather animation or optional effects", flush=True)
    print(f"[startup] world ready: {world.get_map().name}", flush=True)
    if args.presentation:
        if world.get_map().name.endswith("_Opt"):
            world.load_map_layer(carla.MapLayer.All)
        world.set_weather(carla.WeatherParameters(
            cloudiness=0, precipitation=0, precipitation_deposits=0,
            wind_intensity=0, fog_density=0, wetness=0,
            sun_altitude_angle=70, dust_storm=0))
    carla_map = world.get_map()
    blueprints = world.get_blueprint_library()
    # Use a combustion car so a manual gearbox and tachometer are coherent.
    vehicle_bp = blueprints.find("vehicle.ford.mustang")
    vehicle_bp.set_attribute("role_name", "hero")
    spawn_points = carla_map.get_spawn_points()
    if not spawn_points:
        raise RuntimeError("The loaded map has no vehicle spawn points.")
    if args.spawn_index is None:
        random.shuffle(spawn_points)
    elif 0 <= args.spawn_index < len(spawn_points):
        spawn_points = [spawn_points[args.spawn_index]]
    else:
        raise ValueError("--spawn-index is outside this map's spawn points")
    original_settings = world.get_settings()
    command_watchdog = CommandWatchdog(timeout_s=0.5)
    vehicle = try_spawn_vehicle(world, vehicle_bp, spawn_points)
    if vehicle is None:
        raise RuntimeError("All spawn points are occupied. Stop old actors or restart CARLA.")
    sensors = []
    safety_sensors = []
    collision_state = {"value": False}
    human_recorder = None
    try:
        transmission_config = ManualTransmissionConfig()
        simple_neural_mode = args.camera_profile == "map" and args.preload_route_policy
        configured_physics = (vehicle.get_physics_control() if simple_neural_mode else
                              configure_six_speed_physics(vehicle, transmission_config))
        print(f"[startup] vehicle ready: {vehicle.id}", flush=True)
        print(("[startup] stock transmission for neural driving: " if simple_neural_mode else
               "[startup] six-speed transmission ready: ") + json.dumps({
            "ratios": [round(gear.ratio, 2) for gear in configured_physics.forward_gears],
            "redline_kmh": [
                round(gear_redline_speed_kmh(gear, transmission_config), 1)
                for gear in range(1, transmission_config.max_forward_gear + 1)
            ],
            "max_rpm": round(configured_physics.max_rpm),
            "torque_curve_end_rpm": round(configured_physics.torque_curve[-1].x),
        }), flush=True)

        command_watchdog.start(lambda: vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True)))

        if original_settings.synchronous_mode:
            raise RuntimeError("Cockpit requires an asynchronous server; stop the other tick owner first.")
        settings = world.get_settings()
        settings.fixed_delta_seconds = 0.05
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
        settings.no_rendering_mode = args.camera_profile == "map"
        # Own fixed physics ticks in both lightweight modes. An asynchronous
        # world can outrun wall time, multiplying the real camera capture rate.
        settings.synchronous_mode = args.camera_profile == "map" or args.low_scenery or args.presentation
        world.apply_settings(settings)
        print("[startup] physics: fixed 0.05s step, 0.01s substeps", flush=True)
        client.set_timeout(10.0)
        pygame.init()
        display = pygame.display.set_mode(
            (args.window_width, args.window_height), pygame.HWSURFACE | pygame.DOUBLEBUF
        )
        pygame.display.set_caption("CARLA Map Driving" if args.camera_profile == "map" else "CARLA Manual Driving Cockpit")
        # A browser may retain focus after launch. Bring
        # the newly-created driving window forward so keyboard controls work
        # immediately; the in-window focus warning remains as a fallback.
        try:
            cockpit_hwnd = pygame.display.get_wm_info().get("window")
            if cockpit_hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(cockpit_hwnd, 9)  # SW_RESTORE
                user32.BringWindowToTop(cockpit_hwnd)
                user32.SetForegroundWindow(cockpit_hwnd)
                user32.SetActiveWindow(cockpit_hwnd)
                user32.SetFocus(cockpit_hwnd)
        except (AttributeError, OSError):
            pass
        pygame.event.pump()
        hud_font = pygame.font.Font(None, 28)
        speed_font = pygame.font.Font(None, 50)
        small_font = pygame.font.Font(None, 22)
        gauge_tick_font = pygame.font.Font(None, 13)
        queues = {name: queue.Queue(maxsize=1) for name in ("front", "rear", "left", "right")}
        camera_bp = blueprints.find("sensor.camera.rgb")
        camera_lock = threading.Lock()
        camera_updates = {name: 0 for name in queues}
        camera_last_frame_at = {}

        def store_latest_frame(name, image):
            """Replace a queued camera frame instead of accumulating latency."""
            target = queues[name]
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            try:
                target.put_nowait(image)
            except queue.Full:
                pass

        def add_camera(name, transform, width, height, fov=90, sensor_tick=0.1):
            bp = camera_bp
            bp.set_attribute("image_size_x", str(width))
            bp.set_attribute("image_size_y", str(height))
            bp.set_attribute("fov", str(fov))
            bp.set_attribute("sensor_tick", str(sensor_tick))
            if bp.has_attribute("motion_blur_intensity"):
                bp.set_attribute("motion_blur_intensity", "0")
            if bp.has_attribute("motion_blur_max_distortion"):
                bp.set_attribute("motion_blur_max_distortion", "0")
            sensor = world.spawn_actor(
                bp, transform, attach_to=vehicle,
                attachment_type=carla.AttachmentType.Rigid,
            )
            def receive(image, target_name=name):
                with camera_lock:
                    camera_updates[target_name] += 1
                    camera_last_frame_at[target_name] = time.monotonic()
                store_latest_frame(target_name, image)
            sensors.append(sensor)
            sensor.listen(receive)
            print(f"[startup] camera ready: {name} ({sensor.id})", flush=True)

        # Six-zone layout: map, rear view and instruments above the driving views;
        # tyre-facing side mirrors, and a large central windshield.
        top_h = int(args.window_height * 0.24)
        left_w = int(args.window_width * 0.16)
        right_w = int(args.window_width * 0.16)
        instrument_w = int(args.window_width * 0.19)
        map_rect = (0, 0, left_w, top_h)
        rear_rect = (left_w, 0, args.window_width - left_w - instrument_w, top_h)
        instrument_rect = (args.window_width - instrument_w, 0, instrument_w, top_h)
        left_rect = (0, top_h, left_w, args.window_height - top_h)
        right_rect = (args.window_width - right_w, top_h, right_w, args.window_height - top_h)
        front_rect = (left_w, top_h, args.window_width - left_w - right_w,
                      args.window_height - top_h)

        if args.camera_profile == "map":
            front_rect = (0, top_h, args.window_width, args.window_height - top_h)

        camera_views = {
            "front": carla.Transform(
                carla.Location(x=0.65, z=1.62), carla.Rotation(pitch=-3)
            ),
            # Rigid relative poses eliminate per-frame transform updates and
            # keep every view stable as the vehicle moves.
            "left": carla.Transform(
                carla.Location(x=0.65, y=-1.35, z=1.25),
                carla.Rotation(yaw=165, pitch=-20, roll=-3),
            ),
            "right": carla.Transform(
                carla.Location(x=0.65, y=1.35, z=1.25),
                carla.Rotation(yaw=-165, pitch=-20, roll=3),
            ),
            "rear": carla.Transform(
                carla.Location(x=-2.15, z=1.90), carla.Rotation(yaw=180, pitch=-10)
            ),
        }
        performance_started = time.monotonic()
        performance_frames = 0
        if args.camera_profile != "map":
            front_width, front_height = (640, 360) if args.presentation else (320, 180)
            add_camera("front", camera_views["front"], front_width, front_height, 92,
                       1.0 / args.camera_fps)
        if args.camera_profile == "parking":
            for name in ("rear", "left", "right"):
                add_camera(name, camera_views[name], 240, 135, 92,
                           1.0 / args.mirror_camera_fps)
        print(f"[startup] camera profile ready: {args.camera_profile} ({len(sensors)} sensor(s))", flush=True)

        collision_bp = blueprints.find("sensor.other.collision")
        collision_sensor = world.spawn_actor(
            collision_bp, carla.Transform(), attach_to=vehicle,
        )
        collision_sensor.listen(
            lambda _event: collision_state.__setitem__("value", True)
        )
        safety_sensors.append(collision_sensor)

        # Map loading and actor creation legitimately need the long startup
        # timeout.  The interactive loop does not: a dead server must release
        # the cockpit promptly instead of leaving a frozen, all-black window.
        client.set_timeout(args.runtime_rpc_timeout)

        border = 4
        last_scaled_frames = {}
        def draw_frame(name, rect, crop_to_fill=False):
            x, y, width, height = rect
            pygame.draw.rect(display, (0, 0, 0), rect)
            try:
                image = queues[name].get_nowait()
                # Copy the frame so it remains valid after CARLA reuses its
                # callback buffer. Retain it between callbacks to prevent
                # flashing when the display loop is faster than the sensors.
                surface = pygame.image.frombuffer(
                    image.raw_data, (image.width, image.height), "BGRA"
                ).copy()
                image_width, image_height = surface.get_size()
                inner_width = max(1, width - 2 * border)
                inner_height = max(1, height - 2 * border)
                scale_fn = max if crop_to_fill else min
                scale = scale_fn(inner_width / image_width, inner_height / image_height)
                scaled_size = (max(1, int(image_width * scale)), max(1, int(image_height * scale)))
                scaled = pygame.transform.smoothscale(surface, scaled_size)
                image_x = x + border + (inner_width - scaled_size[0]) // 2
                image_y = y + border + (inner_height - scaled_size[1]) // 2
                last_scaled_frames[name] = (scaled, image_x, image_y)
            except queue.Empty:
                pass
            frame = last_scaled_frames.get(name)
            if frame is None:
                pygame.draw.rect(display, (0, 0, 0), rect, border)
                return
            scaled, image_x, image_y = frame
            old_clip = display.get_clip()
            display.set_clip(pygame.Rect(rect))
            display.blit(scaled, (image_x, image_y))
            display.set_clip(old_clip)
            pygame.draw.rect(display, (0, 0, 0), rect, border)

        def draw_panel_label(text, rect):
            """Label intentionally disabled camera panels in safe mode."""
            x, y, width, height = rect
            pygame.draw.rect(display, (8, 12, 17), rect)
            pygame.draw.rect(display, (55, 68, 82), rect, 2)
            label = small_font.render(text, True, (142, 158, 176))
            display.blit(label, label.get_rect(center=(x + width // 2, y + height // 2)))

        clock = pygame.time.Clock()
        held_keys = HeldKeyState(args.input_latch_ms / 1000.0)
        steer = 0.0
        selected_gear = 1
        parked = False
        handbrake = False
        weather_index = 0
        visual_austerity_active = False
        weather_presets = [
            (carla.WeatherParameters.ClearNoon, "CLEAR"),
            (carla.WeatherParameters.WetNoon, "RAIN / WET ROAD"),
            (carla.WeatherParameters.HardRainNoon, "HEAVY RAIN"),
            (carla.WeatherParameters(cloudiness=35.0, fog_density=75.0,
                                     fog_distance=35.0, wetness=10.0), "FOG"),
            (carla.WeatherParameters(cloudiness=85.0, precipitation=100.0,
                                      precipitation_deposits=80.0, wetness=90.0,
                                      wind_intensity=25.0, fog_density=8.0), "SNOW / LOW GRIP"),
        ]
        # Waypoint generation uses the parsed client-side map; do it once.
        # Topology endpoint chords cut across bends and are not a road map.
        map_segments = build_road_segments(carla_map)
        road_index = RoadSegmentIndex(map_segments)
        interactive_map_bounds = map_bounds_from_segments(map_segments)
        town_background = pygame.Surface((args.window_width, args.window_height)).convert()
        town_background.fill((6, 10, 15))
        for start, end in map_segments:
            start_px = world_to_map_pixel(start, interactive_map_bounds, town_background.get_size())
            end_px = world_to_map_pixel(end, interactive_map_bounds, town_background.get_size())
            pygame.draw.line(town_background, (74, 91, 108), start_px, end_px, 3)
        print(f"[startup] curved road map ready: {len(map_segments)} cached segments", flush=True)
        prepared_route_model = None
        prepared_route_planner = None
        if args.preload_route_policy:
            prepared_route_model = load_deployable_route_policy(args.route_policy)
            if args.neural_visual and prepared_route_model.visualizer is None:
                from telemetry.visualizer import NeuralVisualizer
                prepared_route_model.visualizer = NeuralVisualizer(prepared_route_model, args.route_policy)
            prepared_route_planner = make_neural_route_planner(world)
            print(f"[startup] neural model and full road graph loaded: {args.route_policy}", flush=True)
        cached_actors = []
        actor_refresh_frame = -100
        cached_distances = {"front": 80.0, "rear": 80.0, "left": 80.0, "right": 80.0}
        cached_speed_kmh = 0.0
        cached_rpm = 850.0
        cached_actual_gear = 1
        clutch_position = 0.0
        shift_status = ""
        shift_status_until = 0
        rpm_estimator = EngineRpmEstimator(transmission_config)
        last_rpm_update = time.monotonic()
        drive_map_surface = None
        minimap_surface = None
        last_control_signature = None
        last_control_log_at = 0.0
        map_open = bool(args.map_open_on_start)
        map_key_was_down = False
        route_model = None
        route_plan = []
        route_index = 0
        route_safety = SafetySupervisor(SafetyLimits(
            max_speed_kmh=min(args.route_speed_kmh + 8.0, args.graphics_speed_cap_kmh),
            minimum_obstacle_distance_m=7.0,
            maximum_lane_error_m=2.0,
        ))
        route_active = False
        route_stalled_since = None
        route_start_assist = False
        route_destination = None
        route_status = ("CLICK A ROAD TO SET DESTINATION" if map_open else
                        "NEURAL READY · PRESS M AND CLICK A ROAD" if prepared_route_model else "")
        if args.route_destination:
            if prepared_route_model is None or args.human_demo:
                raise ValueError('--route-destination requires a preloaded neural policy')
            destination_wp = carla_map.get_waypoint(
                carla.Location(x=args.route_destination[0], y=args.route_destination[1]),
                project_to_road=True, lane_type=carla.LaneType.Driving)
            if destination_wp is None:
                raise ValueError('No driving road at requested destination')
            route_destination = destination_wp.transform.location
            route_plan = plan_neural_route(world, vehicle.get_location(), route_destination,
                                           planner=prepared_route_planner)
            if len(route_plan) < 2:
                raise ValueError('No usable route to requested destination')
            route_model = prepared_route_model
            route_active, map_open, parked, handbrake = True, False, False, False
            route_status = 'NEURAL ROUTE ACTIVE'
            print('[route] command-line destination selected: ' + json.dumps({
                'x': route_destination.x, 'y': route_destination.y,
                'route_waypoints': len(route_plan)}), flush=True)
        human_demo_active = False
        human_route_id = None
        human_sample_count = 0
        human_distance_m = 0.0
        human_previous_location = vehicle.get_location()
        last_human_sample_at = 0.0
        human_completed_count = len(list(
            Path(args.human_output_dir).glob("human-*.jsonl")
        ))

        def finish_human_demo(success, reason):
            nonlocal human_recorder, human_demo_active, human_sample_count
            nonlocal human_completed_count
            if human_recorder is None:
                human_demo_active = False
                return None
            source_path = human_recorder.path
            human_recorder.close()
            saved_path = None
            if success and human_sample_count >= 100:
                output_dir = Path(args.human_output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                saved_path = output_dir / source_path.name
                source_path.replace(saved_path)
                human_completed_count += 1
            print("[human-demo] " + json.dumps({
                "status": "saved" if saved_path else "excluded",
                "reason": reason,
                "samples": human_sample_count,
                "completed": human_completed_count,
                "target": args.human_target_episodes,
                "path": str(saved_path or source_path),
            }), flush=True)
            human_recorder = None
            human_demo_active = False
            return saved_path

        def render_minimap(size, nearby_actors):
            width, height = size
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((8, 12, 17, 215))
            transform = vehicle.get_transform()
            origin = transform.location
            forward = transform.get_forward_vector()
            right = transform.get_right_vector()
            radius_m = 70.0
            scale = min(width, height) / (radius_m * 2.0)
            center_x, center_y = width // 2, height // 2 + 7

            for (start_x, start_y), (end_x, end_y) in road_index.nearby(origin.x, origin.y, radius_m * 1.4):
                projected = []
                for point_x, point_y in ((start_x, start_y), (end_x, end_y)):
                    dx, dy = point_x - origin.x, point_y - origin.y
                    longitudinal = dx * forward.x + dy * forward.y
                    lateral = dx * right.x + dy * right.y
                    projected.append((longitudinal, lateral))
                local_points = [(lateral, longitudinal) for longitudinal, lateral in projected]
                if segment_intersects_local_radius(
                        local_points[0], local_points[1], radius_m * 1.4):
                    screen_points = [
                        (int(center_x + lateral * scale), int(center_y - longitudinal * scale))
                        for longitudinal, lateral in projected
                    ]
                    pygame.draw.line(surface, (108, 119, 132), screen_points[0], screen_points[1], 2)

            if route_plan:
                route_pixels = []
                for waypoint, _road_option in route_plan[max(0, route_index - 2):]:
                    location = waypoint.transform.location
                    dx, dy = location.x - origin.x, location.y - origin.y
                    longitudinal = dx * forward.x + dy * forward.y
                    lateral = dx * right.x + dy * right.y
                    if abs(longitudinal) <= radius_m and abs(lateral) <= radius_m:
                        route_pixels.append((
                            int(center_x + lateral * scale),
                            int(center_y - longitudinal * scale),
                        ))
                    elif route_pixels:
                        break
                if len(route_pixels) >= 2:
                    pygame.draw.lines(surface, (45, 225, 160), False, route_pixels, 4)

            for actor in nearby_actors:
                if actor.id == vehicle.id:
                    continue
                location = actor.get_location()
                dx, dy = location.x - origin.x, location.y - origin.y
                longitudinal = dx * forward.x + dy * forward.y
                lateral = dx * right.x + dy * right.y
                if abs(longitudinal) <= radius_m and abs(lateral) <= radius_m:
                    px = int(center_x + lateral * scale)
                    py = int(center_y - longitudinal * scale)
                    pygame.draw.circle(surface, (255, 184, 74), (px, py), 4)

            # The car is always the map origin. A halo, crosshair, direction
            # arrow, and label make that current-location convention explicit.
            pygame.draw.circle(surface, (34, 121, 170, 90), (center_x, center_y), 16)
            pygame.draw.circle(surface, (105, 225, 255), (center_x, center_y), 12, 2)
            pygame.draw.line(surface, (105, 225, 255),
                             (center_x - 18, center_y), (center_x + 18, center_y), 1)
            pygame.draw.line(surface, (105, 225, 255),
                             (center_x, center_y - 18), (center_x, center_y + 18), 1)
            pygame.draw.polygon(surface, (90, 220, 255), [
                (center_x, center_y - 12), (center_x - 8, center_y + 9),
                (center_x, center_y + 5), (center_x + 8, center_y + 9),
            ])
            you_surface = small_font.render("YOU", True, (116, 229, 255))
            surface.blit(you_surface, (center_x + 14, center_y - 8))
            pygame.draw.rect(surface, (210, 220, 230), surface.get_rect(), 2, border_radius=8)
            title = small_font.render("LIVE MAP  •  HEADING UP", True, (245, 245, 245))
            surface.blit(title, (10, 8))
            waypoint = carla_map.get_waypoint(origin, project_to_road=True)
            if waypoint is not None:
                location_text = f"Rd {waypoint.road_id}  Ln {waypoint.lane_id}"
            else:
                location_text = "OFF ROAD"
            coordinates = f"X {origin.x:.0f}  Y {origin.y:.0f}"
            details = small_font.render(f"{location_text}  •  {coordinates}", True, (184, 198, 212))
            surface.blit(details, (10, height - details.get_height() - 7))
            return surface

        def draw_interactive_map():
            """Draw a full-town road map and its click-to-drive affordances."""
            display.blit(town_background, (0, 0))
            map_size = (args.window_width, args.window_height)
            if route_plan:
                route_pixels = [world_to_map_pixel(
                    (wp.transform.location.x, wp.transform.location.y),
                    interactive_map_bounds, map_size) for wp, _ in route_plan[route_index:]]
                if len(route_pixels) > 1:
                    pygame.draw.lines(display, (45, 225, 160), False, route_pixels, 4)
            transform = vehicle.get_transform()
            vehicle_px = world_to_map_pixel(
                (transform.location.x, transform.location.y),
                interactive_map_bounds, map_size,
            )
            pygame.draw.circle(display, (61, 214, 255), vehicle_px, 9)
            pygame.draw.circle(display, (235, 250, 255), vehicle_px, 9, 2)
            if route_destination is not None:
                destination_px = world_to_map_pixel(
                    (route_destination.x, route_destination.y),
                    interactive_map_bounds, map_size,
                )
                pygame.draw.circle(display, (255, 178, 55), destination_px, 11, 3)
                pygame.draw.line(display, (255, 178, 55),
                                 (destination_px[0] - 14, destination_px[1]),
                                 (destination_px[0] + 14, destination_px[1]), 2)
                pygame.draw.line(display, (255, 178, 55),
                                 (destination_px[0], destination_px[1] - 14),
                                 (destination_px[0], destination_px[1] + 14), 2)
            shade = pygame.Surface((args.window_width, 48), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 190))
            display.blit(shade, (0, 0))
            title = hud_font.render(
                "DESTINATION MAP  •  CLICK A ROAD TO DRIVE  •  M/ESC TO CLOSE",
                True, (242, 246, 250),
            )
            display.blit(title, title.get_rect(center=(args.window_width // 2, 24)))
            status = small_font.render(route_status + "  |  DRIVING PAUSED", True, (210, 223, 233))
            pygame.draw.rect(display, (6, 10, 15), (0, args.window_height - 36, args.window_width, 36))
            display.blit(status, (20, args.window_height - 27))
            mouse_x, mouse_y = pygame.mouse.get_pos()
            pygame.draw.line(display, (110, 225, 255),
                             (mouse_x - 8, mouse_y), (mouse_x + 8, mouse_y), 1)
            pygame.draw.line(display, (110, 225, 255),
                             (mouse_x, mouse_y - 8), (mouse_x, mouse_y + 8), 1)

        def draw_instruments(speed, rpm, gear, requested_gear, clutch_value,
                             parked_state, parking_brake, control):
            x, y, width, height = instrument_rect
            pygame.draw.rect(display, (7, 10, 15), instrument_rect)
            pygame.draw.rect(display, (82, 98, 119), instrument_rect, 3)
            radius = max(25, min(36, height // 4, width // 6))
            centers = ((x + width // 4, y + 48), (x + width * 3 // 4, y + 48))
            tach_scale_rpm = 7000.0
            tach_color = ((255, 82, 72) if rpm >= transmission_config.redline_rpm * 0.91 else
                          (255, 186, 64) if rpm >= transmission_config.redline_rpm * 0.77
                          else (235, 240, 245))
            values = (
                (min(speed, 180.0) / 180.0, (70, 205, 255),
                 format_speed_kmh(speed), "km/h", False),
                (min(rpm, tach_scale_rpm) / tach_scale_rpm, tach_color,
                 None, "x1000 RPM", True),
            )
            for center, (fraction, color, value, unit, is_tach) in zip(centers, values):
                pygame.draw.circle(display, (12, 18, 27), center, radius)
                pygame.draw.circle(display, (90, 105, 123), center, radius, 2)
                redline_fraction = transmission_config.redline_rpm / tach_scale_rpm
                if is_tach:
                    for segment in range(12):
                        start_fraction = redline_fraction + (1.0 - redline_fraction) * segment / 12.0
                        end_fraction = redline_fraction + (1.0 - redline_fraction) * (segment + 1) / 12.0
                        start_angle = math.radians(135 + start_fraction * 270)
                        end_angle = math.radians(135 + end_fraction * 270)
                        arc_radius = radius - 5
                        start_point = (center[0] + int(arc_radius * math.cos(start_angle)),
                                       center[1] + int(arc_radius * math.sin(start_angle)))
                        end_point = (center[0] + int(arc_radius * math.cos(end_angle)),
                                     center[1] + int(arc_radius * math.sin(end_angle)))
                        pygame.draw.line(display, (230, 55, 48), start_point, end_point, 3)
                tick_count = 14 if is_tach else 10
                for tick in range(tick_count + 1):
                    tick_fraction = tick / tick_count
                    angle = math.radians(135 + tick_fraction * 270)
                    outer = (center[0] + int((radius - 3) * math.cos(angle)),
                             center[1] + int((radius - 3) * math.sin(angle)))
                    major_tick = tick % 2 == 0
                    inner_length = radius - (10 if major_tick else 6)
                    inner = (center[0] + int(inner_length * math.cos(angle)),
                             center[1] + int(inner_length * math.sin(angle)))
                    tick_color = ((255, 72, 62) if is_tach and tick_fraction >= redline_fraction
                                  else (154, 168, 184))
                    pygame.draw.line(display, tick_color, inner, outer, 2 if major_tick else 1)
                    if is_tach and tick % 4 == 0:
                        label = gauge_tick_font.render(str(tick // 2), True, tick_color)
                        label_radius = radius - 14
                        label_center = (
                            center[0] + int(label_radius * math.cos(angle)),
                            center[1] + int(label_radius * math.sin(angle)),
                        )
                        display.blit(label, label.get_rect(center=label_center))
                angle = math.radians(135 + max(0.0, min(1.0, fraction)) * 270)
                end = (center[0] + int((radius - 11) * math.cos(angle)),
                       center[1] + int((radius - 11) * math.sin(angle)))
                needle_color = (245, 247, 250) if is_tach else color
                pygame.draw.line(display, needle_color, center, end, 3)
                pygame.draw.circle(display, (224, 62, 54) if is_tach else color, center, 4)
                if value is not None:
                    value_surface = hud_font.render(value, True, (245, 248, 252))
                    display.blit(value_surface, value_surface.get_rect(center=(center[0], center[1] + 7)))
                unit_surface = small_font.render(unit, True, color)
                display.blit(unit_surface, unit_surface.get_rect(center=(center[0], center[1] + radius - 5)))

            selected = selector_name(gear, parked_state)
            for index, label in enumerate("PRND"):
                color = (70, 205, 255) if label == selected else (132, 145, 162)
                label_surface = hud_font.render(label, True, color)
                display.blit(label_surface, (x + 10 + index * 28, y + height - 56))
            actual_gear_name = manual_gear_name(requested_gear, parked_state)
            gear_box = pygame.Rect(x + width - 61, y + height - 64, 51, 27)
            pygame.draw.rect(display, (20, 33, 45), gear_box, border_radius=5)
            pygame.draw.rect(display, (70, 205, 255), gear_box, 1, border_radius=5)
            gear_surface = hud_font.render(actual_gear_name, True, (92, 220, 255))
            display.blit(gear_surface, gear_surface.get_rect(center=gear_box.center))
            if not gearbox_state_matches(requested_gear, gear):
                sync = small_font.render("GEAR SYNC", True, (255, 102, 92))
                display.blit(sync, sync.get_rect(midtop=(x + width // 2, y + 87)))
            else:
                shift = recommended_shift(
                    gear, rpm, control.throttle, transmission_config, speed,
                )
                if shift:
                    shift_surface = small_font.render(shift, True, tach_color)
                    display.blit(shift_surface, shift_surface.get_rect(midtop=(x + width // 2, y + 87)))

            bars = (("G", control.throttle, (77, 214, 144)),
                    ("B", control.brake, (255, 102, 92)),
                    ("C", clutch_value, (255, 196, 76)))
            bar_y = y + height - 23
            for index, (label, value, color) in enumerate(bars):
                bar_x = x + 10 + index * (width // 3)
                display.blit(small_font.render(label, True, (210, 220, 230)), (bar_x, bar_y - 1))
                track = pygame.Rect(bar_x + 16, bar_y + 4, max(16, width // 3 - 30), 8)
                pygame.draw.rect(display, (48, 57, 70), track)
                pygame.draw.rect(display, color,
                                 (track.x, track.y, int(track.width * max(0.0, min(1.0, value))), track.height))
            if parking_brake:
                display.blit(small_font.render("PARK", True, (255, 116, 96)), (x + width - 50, y + 6))

        def draw_parking_guides(name, rect, distance):
            x, y, width, height = rect
            if name in ("left", "right"):
                inner_x = x + width - 24 if name == "left" else x + 24
                pygame.draw.line(display, (70, 220, 150), (inner_x, y + height // 3),
                                 (inner_x, y + height - 24), 2)
                for fraction, color in ((0.55, (70, 220, 150)),
                                        (0.72, (255, 196, 76)),
                                        (0.88, (255, 92, 82))):
                    marker_y = y + int(height * fraction)
                    direction = -1 if name == "left" else 1
                    pygame.draw.line(display, color, (inner_x, marker_y),
                                     (inner_x + direction * 42, marker_y), 3)
            elif name == "rear":
                bottom = y + height - 10
                mid = x + width // 2
                pygame.draw.line(display, (70, 220, 150), (mid - width // 5, bottom),
                                 (mid - width // 12, y + height // 2), 2)
                pygame.draw.line(display, (70, 220, 150), (mid + width // 5, bottom),
                                 (mid + width // 12, y + height // 2), 2)
                for offset, color in ((12, (255, 92, 82)), (34, (255, 196, 76)), (58, (70, 220, 150))):
                    pygame.draw.line(display, color, (mid - width // 6, bottom - offset),
                                     (mid + width // 6, bottom - offset), 2)
            if distance < 3.0:
                warning = small_font.render(f"OBJECT {distance:.1f} m", True, (255, 116, 96))
                display.blit(warning, (x + 8, y + height - warning.get_height() - 7))

        def draw_control_help(focused, status_message):
            if not focused:
                warning = speed_font.render("CLICK THIS WINDOW TO DRIVE", True, (255, 210, 70))
                panel = pygame.Surface((warning.get_width() + 40, warning.get_height() + 24), pygame.SRCALPHA)
                panel.fill((0, 0, 0, 220))
                panel.blit(warning, (20, 12))
                display.blit(panel, panel.get_rect(center=(args.window_width // 2, args.window_height // 2)))
            elif status_message:
                status = hud_font.render(status_message, True, (255, 210, 70))
                display.blit(status, status.get_rect(
                    center=(front_rect[0] + front_rect[2] // 2, front_rect[1] + 24)
                ))
        agent_actions = queue.Queue(maxsize=1)
        latest_agent_command = None
        latest_agent_command_at = 0.0
        if args.agent_stdin:
            def read_agent_actions():
                for line in sys.stdin:
                    try:
                        if agent_actions.full():
                            agent_actions.get_nowait()
                        agent_actions.put_nowait(json.loads(line))
                    except (ValueError, queue.Empty, queue.Full):
                        pass
            threading.Thread(target=read_agent_actions, daemon=True).start()
        running = True
        print(f"Vehicle spawned: id={vehicle.id}, map={carla_map.name}", flush=True)
        print("[route] controller: neural policy with safety arbitration; no BasicAgent control fallback", flush=True)
        if args.neural_lane_assist:
            print("[route] bounded lane assistance enabled (+/-0.16); raw predictions remain visible", flush=True)
        print("CLICK cockpit first. W/Up=accelerator, S/Down=brake, A/D or arrows=steer")
        print("M=destination map, click road=route drive, manual input=cancels route")
        print("Shift/Ctrl=clutch, comma/period=shift down/up, 1-6=direct gear, R/N/P=selector, Space=handbrake")
        frame_number = 0
        screenshot_saved = False
        run_started_at = time.monotonic()
        # Exclude model/road-graph loading from the first runtime FPS sample.
        performance_started = run_started_at
        while running:
            map_key_pressed = False
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    held_keys.press(event.key)
                    if event.key == pygame.K_F8 and prepared_route_model is not None:
                        if prepared_route_model.visualizer is not None:
                            prepared_route_model.visualizer.open_browser()
                    if event.key == pygame.K_m and not map_key_was_down:
                        map_key_pressed = True
                elif event.type == pygame.KEYUP:
                    held_keys.release(event.key)
                elif event.type == getattr(pygame, "WINDOWFOCUSLOST", -1):
                    held_keys.clear()
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if map_open:
                        map_open = False
                    else:
                        running = False
                # M is handled below from the current keyboard state as well as
                # events.  Some Windows/SDL focus transitions drop KEYDOWN
                # events; edge-detecting the state keeps the map toggle reliable.
                elif (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                      and map_open and 48 <= event.pos[1] < args.window_height - 36):
                    map_size = (args.window_width, args.window_height)
                    world_x, world_y = map_pixel_to_world(
                        event.pos, interactive_map_bounds, map_size,
                    )
                    destination_wp = carla_map.get_waypoint(
                        carla.Location(x=world_x, y=world_y, z=0.0),
                        project_to_road=True,
                        lane_type=carla.LaneType.Driving,
                    )
                    if destination_wp is None:
                        route_status = "NO DRIVABLE ROAD AT THAT LOCATION"
                    else:
                        try:
                            route_destination = destination_wp.transform.location
                            route_plan = plan_neural_route(
                                world, vehicle.get_location(), route_destination,
                                planner=prepared_route_planner,
                            )
                            if len(route_plan) < 2:
                                raise RuntimeError("planner returned no usable route")
                            route_length_m = sum(
                                route_plan[index - 1][0].transform.location.distance(
                                    route_plan[index][0].transform.location,
                                )
                                for index in range(1, len(route_plan))
                            )
                            if args.human_demo and route_length_m < 150.0:
                                raise RuntimeError("human demonstration route must be at least 150 m")
                            route_index = 0
                            map_open = False
                            parked, handbrake = False, False
                            if args.human_demo:
                                pending_dir = Path(args.human_output_dir).parent / "human_pending"
                                map_name = carla_map.name.rsplit("/", 1)[-1].lower()
                                human_route_id = "human-{}-{}".format(
                                    map_name, time.strftime("%Y%m%d-%H%M%S"),
                                )
                                human_recorder = EpisodeRecorder(pending_dir, human_route_id)
                                human_demo_active = True
                                human_sample_count = 0
                                human_distance_m = 0.0
                                human_previous_location = vehicle.get_location()
                                last_human_sample_at = 0.0
                                route_active = False
                                route_status = "HUMAN DEMO RECORDING · FOLLOW GREEN ROUTE"
                            else:
                                policy_path = Path(args.route_policy)
                                if policy_path.is_file():
                                    route_model = prepared_route_model or load_deployable_route_policy(policy_path)
                                    route_active = True
                                    route_stalled_since = None
                                    route_start_assist = False
                                    route_status = "NEURAL ROUTE ACTIVE · MANUAL INPUT CANCELS"
                                else:
                                    # Practice mode still gets a usable green
                                    # route/map without pretending an absent
                                    # deployable neural policy can drive it.
                                    route_model = None
                                    route_active = False
                                    route_status = "MANUAL ROUTE PREVIEW · FOLLOW GREEN LINE"
                            print("[route] destination selected: " + json.dumps({
                                "x": round(route_destination.x, 1),
                                "y": round(route_destination.y, 1),
                                "target_speed_kmh": args.route_speed_kmh,
                                "controller": ("human_driver" if args.human_demo else
                                               "neural_policy" if route_active else
                                               "manual_route_preview"),
                                "policy": (str(Path(args.route_policy).resolve())
                                           if route_active else None),
                                "route_waypoints": len(route_plan),
                                "route_length_m": round(route_length_m, 1),
                            }), flush=True)
                        except Exception as exc:
                            if human_recorder is not None:
                                finish_human_demo(False, "route_setup_failed")
                            route_model = None
                            route_plan = []
                            route_active = False
                            route_status = ("SELECT A ROAD AT LEAST 150 M AWAY" if args.human_demo
                                            else "DEPLOYABLE NEURAL ROUTE POLICY REQUIRED")
                            print(f"[route] planning failed: {exc}", flush=True)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
                    if human_demo_active:
                        finish_human_demo(False, "driver_reset")
                    route_active = False
                    route_model = None
                    route_plan = []
                    route_destination = None
                    vehicle.set_transform(random.choice(spawn_points))
                    vehicle.set_velocity(carla.Vector3D())
                    vehicle.set_angular_velocity(carla.Vector3D())
                    selected_gear, cached_actual_gear, parked, handbrake, steer = 1, 1, False, False, 0.0
                    rpm_estimator.reset()
                    collision_state["value"] = False
                    held_keys.clear()
                    shift_status = "RESET · M1 · BRAKE RELEASED"
                    shift_status_until = pygame.time.get_ticks() + 1500
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                    route_active = False
                    selected_gear, parked, handbrake = 0, True, True
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    route_active = False
                    if cached_speed_kmh < 1.0:
                        selected_gear, parked, handbrake = -1, False, False
                        shift_status = "REVERSE"
                    else:
                        shift_status = "STOP BEFORE SELECTING REVERSE"
                    shift_status_until = pygame.time.get_ticks() + 1200
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_n:
                    route_active = False
                    selected_gear, parked = 0, False
                elif event.type == pygame.KEYDOWN and event.key in (
                        pygame.K_1, pygame.K_2, pygame.K_3,
                        pygame.K_4, pygame.K_5, pygame.K_6):
                    route_active = False
                    requested = event.key - pygame.K_0
                    clutch_now = 1.0 if (held_keys[pygame.K_LSHIFT] or held_keys[pygame.K_LCTRL]) else 0.0
                    if can_change_gear(cached_speed_kmh, clutch_now):
                        selected_gear, parked, handbrake = requested, False, False
                        shift_status = f"GEAR M{selected_gear}"
                    else:
                        shift_status = "CLUTCH REQUIRED WHILE MOVING"
                    shift_status_until = pygame.time.get_ticks() + 1200
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_COMMA, pygame.K_PERIOD):
                    route_active = False
                    clutch_now = 1.0 if (held_keys[pygame.K_LSHIFT] or held_keys[pygame.K_LCTRL]) else 0.0
                    if can_change_gear(cached_speed_kmh, clutch_now):
                        delta = -1 if event.key == pygame.K_COMMA else 1
                        selected_gear = max(1, min(6, selected_gear + delta if selected_gear > 0 else 1))
                        parked, handbrake = False, False
                        shift_status = f"GEAR M{selected_gear}"
                    else:
                        shift_status = "CLUTCH REQUIRED WHILE MOVING"
                    shift_status_until = pygame.time.get_ticks() + 1200
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_h:
                    handbrake = not handbrake
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_c:
                    if args.camera_profile == "map" or args.low_scenery or args.presentation:
                        continue
                    weather_index = (weather_index + 1) % len(weather_presets)
                    selected_weather = weather_presets[weather_index][0]
                    world.set_weather(
                        reduced_motion_weather(selected_weather)
                        if visual_austerity_active else selected_weather
                    )

            m_down = bool(pygame.key.get_pressed()[pygame.K_m])
            if map_key_pressed or (m_down and not map_key_was_down):
                if human_demo_active:
                    route_status = "HUMAN DEMO ACTIVE · REACH THE DESTINATION"
                else:
                    map_open = not map_open
                    held_keys.clear()
                    route_status = "CLICK A ROAD TO SET DESTINATION" if map_open else route_status
                    print("[map] destination map " + ("opened" if map_open else "closed"), flush=True)
            map_key_was_down = m_down
            keys = held_keys
            manual_drive_keys = (
                pygame.K_w, pygame.K_UP, pygame.K_s, pygame.K_DOWN,
                pygame.K_a, pygame.K_LEFT, pygame.K_d, pygame.K_RIGHT,
                pygame.K_SPACE,
            )
            if route_active and any(keys[key] for key in manual_drive_keys):
                route_active = False
                route_model = None
                route_plan = []
                route_status = "ROUTE CANCELLED · MANUAL CONTROL"
            if map_open:
                clutch_position = 0.0
                control = carla.VehicleControl(brake=1.0)
            elif args.agent_stdin:
                try:
                    payload = agent_actions.get_nowait()
                    latest_agent_command = VehicleCommand(
                        accelerator=payload.get("accelerator", 0.0),
                        brake=payload.get("brake", 0.0),
                        clutch=payload.get("clutch", 0.0),
                        hand_brake=payload.get("hand_brake", False),
                        steering_angle_deg=payload.get("steering_angle_deg", 0.0),
                        gear=payload.get("gear", 1),
                    ).sanitized(ControlConfig())
                    latest_agent_command_at = time.monotonic()
                except queue.Empty:
                    pass
                if (latest_agent_command is not None and
                        time.monotonic() - latest_agent_command_at <= args.agent_timeout):
                    command = latest_agent_command
                    selected_gear = command.gear
                    parked = False
                    handbrake = command.hand_brake
                    clutch_position = command.clutch
                    control = command.to_carla(ControlConfig())
                else:
                    clutch_position = 0.0
                    control = carla.VehicleControl(brake=1.0)
            elif route_active:
                try:
                    route_index = advance_route_index(
                        route_plan, vehicle.get_location(), route_index,
                    )
                    distance_to_destination = vehicle.get_location().distance(
                        route_destination,
                    )
                    if distance_to_destination <= 4.0 or route_index >= len(route_plan) - 2:
                        route_active = False
                        route_status = "DESTINATION REACHED"
                        control = carla.VehicleControl(brake=1.0)
                    else:
                        reference_index = min(route_index + 4, len(route_plan) - 1)
                        reference_waypoint = route_plan[reference_index][0]
                        route_features = make_observation(
                            vehicle,
                            world,
                            carla.TrafficLightState.Red,
                            cached_actors,
                            target_speed_kmh=args.route_speed_kmh,
                            reference_waypoint=reference_waypoint,
                            carla_map=carla_map,
                        )
                        prediction = route_model.predict(
                            normalize_features(route_features),
                        )
                        if frame_number % 100 == 0:
                            print('[route] neural attempt: ' + json.dumps({
                                'prediction': prediction, 'route_index': route_index,
                                'destination_distance_m': distance_to_destination,
                            }), flush=True)
                        selected_gear = automatic_route_gear(
                            cached_speed_kmh, transmission_config,
                        )
                        accelerator = max(0.0, min(1.0, float(prediction[1])))
                        brake = max(0.0, min(1.0, float(prediction[2])))
                        neural_steering = max(-1.0, min(1.0, float(prediction[0])))
                        lane_correction = 0.0
                        assisted_speed_target = args.route_speed_kmh
                        if args.neural_lane_assist:
                            neural_steering, lane_correction, assisted_speed_target = apply_lane_assistance(
                                route_features, neural_steering)
                        if simple_neural_mode:
                            now = time.monotonic()
                            if is_stall_candidate(route_features[2], accelerator, brake):
                                route_stalled_since = now if route_stalled_since is None else route_stalled_since
                            elif not route_start_assist:
                                route_stalled_since = None
                            accelerator, brake, route_start_assist = apply_stall_recovery(
                                route_features, accelerator, brake,
                                0.0 if route_stalled_since is None else now-route_stalled_since,
                                active=route_start_assist,
                                maximum_lane_error_m=1.6 if args.neural_lane_assist else 1.2,
                                max_accelerator=.2 if args.neural_lane_assist and abs(route_features[0]) > 1.2 else .35)
                            # Same small-brake deadband as the working headless driver.
                            if brake < 0.45:
                                brake = 0.0
                            accelerator, brake = limit_neural_speed(
                                accelerator, brake, route_features[2], assisted_speed_target)
                        if brake > 0.05:
                            accelerator = 0.0
                        neural_command = VehicleCommand(
                            accelerator=accelerator,
                            brake=brake,
                            steering_angle_deg=max(
                                -70.0, min(70.0, neural_steering * 70.0)
                            ),
                            gear=selected_gear,
                        )
                        safe_command, safety_reasons = route_safety.apply(
                            neural_command,
                            {
                                "speed_kmh": route_features[2],
                                "obstacle_distance_m": route_features[4],
                                "lane_error_m": abs(route_features[0]),
                                "red_light": route_features[5] > 0.7,
                                "collision": collision_state["value"],
                                "command_age_s": command_watchdog.status()["command_age_s"],
                            },
                        )
                        control = safe_command.to_carla(ControlConfig())
                        if simple_neural_mode:
                            control.manual_gear_shift = False
                        if safety_reasons:
                            route_status = "NEURAL ROUTE · SAFETY: " + ", ".join(safety_reasons)
                        elif route_start_assist:
                            route_status = "NEURAL + START ASSIST"
                        elif brake >= 0.45 and route_features[2] < 1.0:
                            if abs(route_features[0]) > (1.6 if args.neural_lane_assist else 1.2) or abs(route_features[1]) > 15.0:
                                route_status = "MODEL STOP · REALIGN MANUALLY OR BACKSPACE RESET"
                            else:
                                route_status = "MODEL REQUESTS STOP · WAITING FOR SAFE START"
                        else:
                            route_status = "NEURAL ROUTE ACTIVE"
                        if args.neural_lane_assist and not safety_reasons:
                            route_status += ' · LANE ASSIST'
                        if route_model.visualizer is not None:
                            route_model.visualizer.publish_runtime({
                                'status': route_status, 'safety_reasons': safety_reasons,
                                'speed_kmh': route_features[2], 'features': route_features,
                                'start_assist': route_start_assist,
                                'lane_assist': args.neural_lane_assist,
                                'lane_correction': lane_correction,
                                'speed_target_kmh': assisted_speed_target,
                                'route_index': route_index,
                                'destination_distance_m': distance_to_destination,
                            })
                        if frame_number % 20 == 0:
                            print('[route] state: ' + json.dumps({
                                'status': route_status, 'features': route_features,
                                'safety_reasons': safety_reasons,
                                'start_assist': route_start_assist,
                                'lane_correction': lane_correction,
                                'speed_target_kmh': assisted_speed_target,
                            }), flush=True)
                        parked, handbrake = False, False
                    clutch_position = 0.0
                except Exception as exc:
                    route_active = False
                    route_model = None
                    route_plan = []
                    route_status = "ROUTE STOPPED · NAVIGATION ERROR"
                    control = carla.VehicleControl(brake=1.0)
                    clutch_position = 0.0
                    print(f"[route] navigation stopped: {exc}", flush=True)
            else:
                control, steer = build_vehicle_control(
                    keys, pygame, steer, selected_gear=selected_gear,
                    parked=parked, handbrake=handbrake
                )
                clutch_position = 1.0 if (keys[pygame.K_LSHIFT] or keys[pygame.K_LCTRL]) else 0.0
                if not pygame.key.get_focused():
                    control.throttle = 0.0
                    control.brake = 1.0
                    held_keys.clear()
            control, throttle_neck_active = apply_graphics_throttle_neck(
                control, cached_speed_kmh,
                args.graphics_throttle_start_kmh,
                args.graphics_speed_cap_kmh,
            )
            control, steering_limit_active = apply_speed_sensitive_steering(
                control, cached_speed_kmh,
            )
            control, turn_stability_active = apply_turn_stability(
                control, cached_speed_kmh,
            )
            control, scene_limit_active = apply_scene_streaming_limit(
                control, cached_speed_kmh,
            )
            input_labels = [label for key, label in (
                (pygame.K_w, "W"), (pygame.K_UP, "UP"),
                (pygame.K_s, "S"), (pygame.K_DOWN, "DOWN"),
                (pygame.K_a, "A"), (pygame.K_LEFT, "LEFT"),
                (pygame.K_d, "D"), (pygame.K_RIGHT, "RIGHT"),
                (pygame.K_LSHIFT, "CLUTCH"), (pygame.K_LCTRL, "CLUTCH"),
                (pygame.K_SPACE, "HANDBRAKE"),
            ) if keys[key]]
            input_labels = list(dict.fromkeys(input_labels))
            control_signature = (
                tuple(input_labels), round(control.throttle, 2), round(control.brake, 2),
                round(control.steer, 2), bool(control.hand_brake), int(control.gear),
                bool(pygame.key.get_focused()),
            )
            control_now = time.monotonic()
            immediate_control_change = (last_control_signature is None or
                control_signature[0] != last_control_signature[0] or
                control_signature[4:] != last_control_signature[4:] or
                (control_signature[2] >= .95 and last_control_signature[2] < .95))
            if control_signature != last_control_signature and (
                    immediate_control_change or control_now - last_control_log_at >= .25):
                print("[control] " + json.dumps({
                    "focused": control_signature[-1], "keys": input_labels,
                    "throttle": control.throttle, "brake": control.brake,
                    "steer": control.steer, "hand_brake": control.hand_brake,
                    "gear": control.gear,
                }), flush=True)
                last_control_signature = control_signature
                last_control_log_at = control_now
            vehicle.apply_control(control)
            command_watchdog.command_received()
            if prepared_route_model is not None and prepared_route_model.visualizer is not None:
                prepared_route_model.visualizer.publish_runtime({
                    'status': route_status if not map_open else 'DESTINATION MAP OPEN · PAUSED',
                    'route_active': route_active and not map_open,
                    'applied': {'steering': control.steer, 'accelerator': control.throttle,
                                'brake': control.brake},
                })

            if args.camera_profile == "map" or args.low_scenery or args.presentation:
                world.tick(args.runtime_rpc_timeout)

            if human_demo_active and time.monotonic() - last_human_sample_at >= 0.05:
                route_index = advance_route_index(
                    route_plan, vehicle.get_location(), route_index,
                )
                reference_index = min(route_index + 4, len(route_plan) - 1)
                reference_waypoint = route_plan[reference_index][0]
                observation = make_observation(
                    vehicle, world, carla.TrafficLightState.Red, cached_actors,
                    target_speed_kmh=args.route_speed_kmh,
                    reference_waypoint=reference_waypoint,
                    carla_map=carla_map,
                )
                current_location = vehicle.get_location()
                human_distance_m += current_location.distance(human_previous_location)
                human_previous_location = current_location
                human_recorder.record(
                    observation,
                    {
                        "steering": float(control.steer),
                        "accelerator": float(control.throttle),
                        "brake": float(control.brake),
                    },
                    telemetry={
                        "speed_kmh": observation[2],
                        "obstacle_distance_m": observation[4],
                        "lane_error_m": observation[0],
                        "lane_departure": abs(observation[0]) > 2.0,
                        "collision": collision_state["value"],
                        "distance_m": human_distance_m,
                    },
                    event=["collision"] if collision_state["value"] else None,
                    metadata={
                        "source": "human_driver",
                        "map": carla_map.name.rsplit("/", 1)[-1],
                        "route_id": human_route_id,
                        "target_speed_kmh": args.route_speed_kmh,
                        "route_conditioned": True,
                        "policy_contract_version": POLICY_CONTRACT_VERSION,
                    },
                )
                human_sample_count += 1
                last_human_sample_at = time.monotonic()
                distance_to_destination = current_location.distance(route_destination)
                if collision_state["value"]:
                    finish_human_demo(False, "collision")
                    route_status = "HUMAN DEMO EXCLUDED · COLLISION · BACKSPACE TO RESET"
                    control = carla.VehicleControl(brake=1.0)
                    vehicle.apply_control(control)
                elif distance_to_destination <= 6.0:
                    saved_path = finish_human_demo(True, "destination_reached")
                    if saved_path and human_completed_count >= args.human_target_episodes:
                        route_status = "12 HUMAN DEMOS COMPLETE · TRAINING DATA READY"
                    elif saved_path:
                        route_status = "HUMAN DEMO SAVED {}/{} · PRESS M FOR ANOTHER".format(
                            human_completed_count, args.human_target_episodes,
                        )
                    else:
                        route_status = "DEMO TOO SHORT · NOT SAVED"
                    control = carla.VehicleControl(brake=1.0)
                    vehicle.apply_control(control)

            display.fill((5, 8, 12))
            if args.camera_profile != "map":
                draw_frame("front", front_rect, crop_to_fill=True)
                draw_frame("left", left_rect, crop_to_fill=True)
                draw_frame("rear", rear_rect, crop_to_fill=True)
                draw_frame("right", right_rect, crop_to_fill=True)
            if frame_number - actor_refresh_frame >= max(1, args.target_fps // 2):
                all_actors = world.get_actors()
                cached_actors = list(all_actors.filter("vehicle.*")) + list(all_actors.filter("walker.*"))
                actor_refresh_frame = frame_number
                minimap_surface = render_minimap((map_rect[2], map_rect[3]), cached_actors)
                cached_distances = nearest_distances(vehicle, world, cached_actors)
            if args.camera_profile == "map":
                if frame_number % max(1, args.target_fps // 10) == 0 or drive_map_surface is None:
                    drive_map_surface = render_minimap((front_rect[2], front_rect[3]), cached_actors)
                display.blit(drive_map_surface, front_rect[:2])
            if frame_number % max(1, args.target_fps // 10) == 0:
                cached_speed_kmh = vehicle_speed_kmh(vehicle)
                next_austerity = visual_austerity_transition(
                    visual_austerity_active,
                    cached_speed_kmh,
                    args.visual_austerity_start_kmh,
                    args.visual_austerity_resume_kmh,
                )
                if args.camera_profile != "map" and not (args.low_scenery or args.presentation) and next_austerity != visual_austerity_active:
                    visual_austerity_active = next_austerity
                    selected_weather = weather_presets[weather_index][0]
                    world.set_weather(
                        reduced_motion_weather(selected_weather)
                        if visual_austerity_active else selected_weather
                    )
                    print(
                        "[performance] high-speed visual austerity " +
                        ("enabled" if visual_austerity_active else "disabled"),
                        flush=True,
                    )
                applied_control = vehicle.get_control()
                cached_actual_gear = int(applied_control.gear)
                now = time.monotonic()
                cached_rpm = rpm_estimator.update(
                    cached_speed_kmh, selected_gear, control.throttle,
                    clutch_position, now - last_rpm_update,
                )
                last_rpm_update = now
            if args.camera_profile == "parking":
                draw_parking_guides("left", left_rect, cached_distances["left"])
                draw_parking_guides("rear", rear_rect, cached_distances["rear"])
                draw_parking_guides("right", right_rect, cached_distances["right"])
            elif args.camera_profile == "map":
                draw_panel_label("MAP DRIVING  |  M: DESTINATION MAP", rear_rect)
                for index, help_text in enumerate((
                        "W / S: ACCELERATE / BRAKE     A / D: STEER",
                        "1-6: GEAR     SHIFT: CLUTCH     R: REVERSE     SPACE: HANDBRAKE")):
                    label = small_font.render(help_text, True, (172, 193, 211))
                    display.blit(label, label.get_rect(center=(
                        rear_rect[0] + rear_rect[2] // 2,
                        rear_rect[1] + rear_rect[3] // 2 + 30 + index * 22)))
            else:
                draw_panel_label("LEFT MIRROR OFF • SAFE MODE", left_rect)
                draw_panel_label("REAR CAMERA OFF • SAFE MODE", rear_rect)
                draw_panel_label("RIGHT MIRROR OFF • SAFE MODE", right_rect)
            if minimap_surface is not None:
                display.blit(minimap_surface, (map_rect[0], map_rect[1]))
            draw_instruments(cached_speed_kmh, cached_rpm, cached_actual_gear,
                             selected_gear, clutch_position, parked,
                             handbrake or parked, control)
            if pygame.time.get_ticks() < shift_status_until:
                active_status = shift_status
            elif input_labels:
                active_status = "LIVE INPUT: " + " + ".join(input_labels)
                if throttle_neck_active:
                    active_status += " · GRAPHICS THROTTLE"
            elif route_active:
                active_status = route_status + " · M MAP · F8 NETWORK"
            elif human_demo_active:
                active_status = route_status
            elif route_status:
                active_status = route_status
            elif throttle_neck_active:
                active_status = "GRAPHICS THROTTLE"
            else:
                active_status = ""
            if visual_austerity_active:
                active_status = (active_status + " · " if active_status else "") + "REDUCED MOTION"
            if turn_stability_active:
                active_status = (active_status + " · " if active_status else "") + "TURN STABILITY"
            if steering_limit_active:
                active_status = (active_status + " · " if active_status else "") + "SPEED-SAFE STEERING"
            if scene_limit_active:
                active_status = (active_status + " · " if active_status else "") + "48 KM/H STABILITY LIMIT"
            draw_control_help(pygame.key.get_focused() or args.agent_stdin, active_status)
            if map_open:
                draw_interactive_map()
            required_frames = 0 if args.camera_profile == "map" else (4 if args.camera_profile == "parking" else 1)
            if (args.screenshot_path and not screenshot_saved and
                    frame_number >= 35 and
                    len(last_scaled_frames) >= required_frames and minimap_surface is not None):
                screenshot = Path(args.screenshot_path)
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                pygame.image.save(display, str(screenshot))
                screenshot_saved = True
                print(f"[runtime] cockpit snapshot saved: {screenshot}", flush=True)
            pygame.display.flip()
            clock.tick(max(1, args.target_fps))
            frame_number += 1
            performance_frames += 1
            performance_elapsed = time.monotonic() - performance_started
            if performance_elapsed >= 5.0:
                required_views = () if args.camera_profile == "map" else (("front", "rear", "left", "right") if args.camera_profile == "parking" else ("front",))
                with camera_lock:
                    stale_views = [name for name in required_views
                                   if time.monotonic() - camera_last_frame_at.get(name, run_started_at) > 10.0]
                if stale_views:
                    raise RuntimeError("Camera stream stalled: " + ", ".join(stale_views))
                with camera_lock:
                    view_rates = {
                        name: round(count / performance_elapsed, 1)
                        for name, count in camera_updates.items()
                    }
                    for name in camera_updates:
                        camera_updates[name] = 0
                print("[performance] " + json.dumps({
                    "render_fps": round(performance_frames / performance_elapsed, 1),
                    "view_updates_fps": view_rates,
                }), flush=True)
                performance_started = time.monotonic()
                performance_frames = 0
            if (args.max_runtime_seconds and
                    time.monotonic() - run_started_at >= args.max_runtime_seconds):
                running = False
    finally:
        actions = [("stop watchdog", command_watchdog.stop),
                   ("emergency brake", lambda: vehicle.apply_control(carla.VehicleControl(brake=1.0, hand_brake=True)))]
        if human_recorder is not None:
            actions.append(("close recorder", human_recorder.close))
        for sensor in sensors + safety_sensors:
            actions.extend([("stop sensor", sensor.stop), ("destroy sensor", sensor.destroy)])
        actions.extend([("destroy vehicle", vehicle.destroy),
                        ("restore world settings", lambda: world.apply_settings(original_settings)),
                        ("close display", pygame.quit)])
        if 'prepared_route_model' in locals() and prepared_route_model is not None and prepared_route_model.visualizer is not None:
            actions.append(("close neural visualizer", prepared_route_model.visualizer.close))
        cleanup_actions(actions)
