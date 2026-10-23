"""Experimental empty-road CARLA adapter; deliberately not traffic-ready."""
import math
import random
import threading

from sim_host.environment import DT
from sim_host.profiles import PRESENTATION
from sim_host.wire import ProtocolError
from sim_host.world import cleanup_actions, require_idle_world, load_map, warm_up_tiles, create_client


class CarlaBackend:
    name = "carla-empty-road-experimental"

    def __init__(self, map_name="Town02_Opt", spawn_index=None):
        import carla
        self.carla = carla
        self.map_name = map_name
        self.spawn_index = spawn_index
        self.client = create_client(carla)
        self.client.set_timeout(5)
        self.world = None
        self.vehicle = None
        self.sensor = None
        self.control_lock = threading.Lock()
        self.collided = threading.Event()
        self.original_settings = None
        self.original_weather = None
        self.details = {}

    def _prepare(self):
        world = self.client.get_world()
        require_idle_world(world)
        # Validate before changing anything; no implicit map installation.
        available = self.client.get_available_maps()
        matches = [name for name in available if name.rsplit("/", 1)[-1] == self.map_name]
        if len(matches) != 1:
            raise ValueError("Requested map must uniquely match an installed map")
        self.client.set_timeout(90)
        try:
            world = load_map(self.client, matches[0], self.carla)
            self.world = world
            self.map = world.get_map()
            self.original_settings, self.original_weather = world.get_settings(), world.get_weather()
            settings = world.get_settings()
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = DT
            settings.no_rendering_mode = False
            settings.substepping = True
            settings.max_substep_delta_time = 0.01
            settings.max_substeps = 10
            world.apply_settings(settings)
            world.set_weather(self.carla.WeatherParameters(
                cloudiness=20, sun_altitude_angle=45, wind_intensity=PRESENTATION.wind))
            self.details = {"map": self.map.name, "rendering": not world.get_settings().no_rendering_mode,
                            "wind_intensity": world.get_weather().wind_intensity,
                            "fixed_delta_seconds": world.get_settings().fixed_delta_seconds}
        finally:
            self.client.set_timeout(5)

    def _route(self, spawn):
        waypoint = self.map.get_waypoint(spawn.location)
        if waypoint is None or waypoint.is_junction:
            return None
        route = [waypoint]
        # First curriculum: a short same-lane segment with no junctions. No
        # external navigation agent, intersection assumptions, or traffic actors.
        for _ in range(30):
            candidates = waypoint.next(2)
            if len(candidates) != 1:
                break
            nxt = candidates[0]
            if (nxt.is_junction or nxt.road_id != waypoint.road_id or
                    nxt.lane_id != waypoint.lane_id):
                break
            route.append(nxt)
            waypoint = nxt
        return route if len(route) >= 16 else None

    def _destroy_episode(self):
        # Collision callbacks capture a per-episode Event, not mutable self state.
        sensor, vehicle = self.sensor, self.vehicle
        self.sensor = self.vehicle = None
        actions = []
        if sensor is not None:
            actions += [("stop collision sensor", sensor.stop), ("destroy collision sensor", sensor.destroy)]
        if vehicle is not None:
            actions += [("destroy episode vehicle", vehicle.destroy)]
        cleanup_actions(actions)

    def reset(self, seed, scenario):
        if scenario != "lane_follow":
            raise ProtocolError("CARLA adapter currently supports only empty-road lane_follow")
        self.brake()
        self._destroy_episode()
        if self.world is None:
            self._prepare()
        elif any(self.world.get_actors().filter(pattern) for pattern in ("vehicle.*", "walker.*", "sensor.*")):
            raise RuntimeError("Unexpected actors appeared; refusing to reset another client's world")
        spawn_points = list(self.map.get_spawn_points())
        if self.spawn_index is not None:
            if not 0 <= self.spawn_index < len(spawn_points):
                raise ValueError("Diagnostic spawn index is outside this map")
            spawn_points = [spawn_points[self.spawn_index]]
        else:
            random.Random(seed).shuffle(spawn_points)
        blueprint = self.world.get_blueprint_library().find("vehicle.ford.mustang")
        blueprint.set_attribute("role_name", "hero")
        try:
            for spawn in spawn_points:
                route = self._route(spawn)
                if route is None:
                    continue
                vehicle = self.world.try_spawn_actor(blueprint, spawn)
                if vehicle is not None:
                    self.vehicle, self.route = vehicle, route
                    break
            if self.vehicle is None:
                raise RuntimeError("No clear same-lane route of at least 30 metres on this map")
            self.details["fixed_spawn_index"] = self.spawn_index
            self.arc = [0.0]
            for start, end in zip(self.route, self.route[1:]):
                self.arc.append(self.arc[-1] + start.transform.location.distance(end.transform.location))
            self.segment = 0
            self.collided = threading.Event()
            episode_collision = self.collided
            self.sensor = self.world.spawn_actor(self.world.get_blueprint_library().find("sensor.other.collision"),
                                                self.carla.Transform(), attach_to=self.vehicle)
            self.sensor.listen(lambda event: episode_collision.set())
            self.brake()
            warm_up_tiles(self.world, self.vehicle, self.client, self.carla, self.map.name)
            self.client.set_timeout(5)
            for _ in range(10):
                self.world.tick(5)
            return self.snapshot()
        except Exception:
            self._destroy_episode()
            raise

    def snapshot(self):
        transform = self.vehicle.get_transform()
        location = transform.location
        velocity = self.vehicle.get_velocity()
        # Search only a small contiguous route window, so a crossing/parallel
        # lane cannot jump directly to a distant future segment for reward.
        candidates = []
        for index in range(max(0, self.segment - 2), min(len(self.route) - 1, self.segment + 4)):
            a, b = self.route[index].transform.location, self.route[index + 1].transform.location
            dx, dy = b.x - a.x, b.y - a.y
            length2 = dx * dx + dy * dy
            if length2 <= 1e-9:
                continue
            u = max(0, min(1, ((location.x - a.x) * dx + (location.y - a.y) * dy) / length2))
            distance = math.hypot(location.x - a.x - u * dx, location.y - a.y - u * dy)
            lateral = ((location.y - a.y) * dx - (location.x - a.x) * dy) / math.sqrt(length2)
            progress = self.arc[index] + u * (self.arc[index + 1] - self.arc[index])
            candidates.append((distance, index, lateral, progress, math.atan2(dy, dx)))
        if not candidates:
            raise RuntimeError("Route has no valid segments")
        distance, self.segment, lateral, progress, yaw = min(candidates)
        heading = math.remainder(math.radians(transform.rotation.yaw) - yaw, math.tau)
        road = self.map.get_waypoint(location, project_to_road=False, lane_type=self.carla.LaneType.Driving)
        light = self.vehicle.get_traffic_light() if self.vehicle.is_at_traffic_light() else None
        stop = light is not None and light.get_state() != self.carla.TrafficLightState.Green
        self.world.get_spectator().set_transform(self.carla.Transform(
            location - transform.get_forward_vector() * 7 + self.carla.Location(z=3.2),
            self.carla.Rotation(pitch=-12, yaw=transform.rotation.yaw)))
        return {"speed_mps": math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2),
                "lateral_m": lateral, "heading_error_rad": heading, "progress_m": progress,
                "route_length_m": self.arc[-1], "speed_limit_mps": max(1, self.vehicle.get_speed_limit() / 3.6),
                "stop_required": stop, "obstacle_distance_m": 100.0,
                "collision": self.collided.is_set(),
                "offroad": road is None or distance > min(1.5, self.route[self.segment].lane_width / 2)}

    def step(self, action):
        owned_ids = {actor.id for actor in (self.vehicle, self.sensor) if actor is not None}
        actors = self.world.get_actors()
        if any(actor.id not in owned_ids for pattern in ("vehicle.*", "walker.*", "sensor.*")
               for actor in actors.filter(pattern)):
            raise RuntimeError("Unexpected actors: this adapter is restricted to an empty road")
        with self.control_lock:
            if self.vehicle is None:
                raise RuntimeError("No active vehicle")
            self.vehicle.apply_control(self.carla.VehicleControl(**action, reverse=False))
        self.world.tick(5)
        return self.snapshot()

    def brake(self):
        with self.control_lock:
            if self.vehicle is not None:
                self.vehicle.apply_control(self.carla.VehicleControl(brake=1.0, hand_brake=True))

    def close(self):
        self._destroy_episode()
        actions = []
        if self.world is not None and self.original_weather is not None:
            actions.append(("restore weather", lambda: self.world.set_weather(self.original_weather)))
        if self.world is not None and self.original_settings is not None:
            actions.append(("restore settings", lambda: self.world.apply_settings(self.original_settings)))
        cleanup_actions(actions)
        self.world = None
