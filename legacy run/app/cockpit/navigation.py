"""Map projection, route selection and legacy route-policy loading."""
from runtime.paths import carla_root as get_carla_root

import os
import sys
from pathlib import Path

from learning.model import load_deployable_policy

def segment_intersects_local_radius(start, end, radius):
    """Return true when a 2D segment passes through the local map square."""
    start_x, start_y = start
    end_x, end_y = end
    if (max(start_x, end_x) < -radius or min(start_x, end_x) > radius or
            max(start_y, end_y) < -radius or min(start_y, end_y) > radius):
        return False
    return True


def map_bounds_from_segments(segments):
    """Return stable world-space bounds for the interactive road map."""
    points = [point for segment in segments for point in segment]
    if not points:
        return (-1.0, -1.0, 1.0, 1.0)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def world_to_map_pixel(world_xy, bounds, size, margin=60):
    """Project a CARLA world XY point onto the full-screen map."""
    min_x, min_y, max_x, max_y = bounds
    width, height = size
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)
    scale = min(max(1.0, width - 2 * margin) / span_x,
                max(1.0, height - 2 * margin) / span_y)
    offset_x = (width - span_x * scale) / 2.0
    offset_y = (height - span_y * scale) / 2.0
    px = offset_x + (float(world_xy[0]) - min_x) * scale
    py = height - (offset_y + (float(world_xy[1]) - min_y) * scale)
    return px, py


def map_pixel_to_world(pixel_xy, bounds, size, margin=60):
    """Invert ``world_to_map_pixel`` for destination selection."""
    min_x, min_y, max_x, max_y = bounds
    width, height = size
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)
    scale = min(max(1.0, width - 2 * margin) / span_x,
                max(1.0, height - 2 * margin) / span_y)
    offset_x = (width - span_x * scale) / 2.0
    offset_y = (height - span_y * scale) / 2.0
    world_x = min_x + (float(pixel_xy[0]) - offset_x) / scale
    world_y = min_y + (height - float(pixel_xy[1]) - offset_y) / scale
    return world_x, world_y


def make_neural_route_planner(world, sampling_resolution=2.0):
    """Build the road graph once, before interactive destination selection."""
    agents_root = Path(os.environ.get("CARLA_ROOT", str(get_carla_root()))) / "PythonAPI" / "carla"
    if str(agents_root) not in sys.path:
        sys.path.insert(0, str(agents_root))
    from agents.navigation.global_route_planner import GlobalRoutePlanner
    return GlobalRoutePlanner(world.get_map(), float(sampling_resolution))


def plan_neural_route(world, origin, destination, sampling_resolution=2.0, planner=None):
    """Plan geometry only; vehicle controls remain exclusively neural."""
    if planner is None:
        planner = make_neural_route_planner(world, sampling_resolution)
    return planner.trace_route(origin, destination)


def load_deployable_route_policy(path):
    """Require a route-conditioned, deployable artifact with no legacy fallback."""
    return load_deployable_policy(path, require_route_conditioned=True)


def advance_route_index(route, location, current_index=0, search_ahead=20):
    """Track the closest upcoming route waypoint without moving backwards."""
    if not route:
        return 0
    start = max(0, min(int(current_index), len(route) - 1))
    end = min(len(route), start + max(1, int(search_ahead)))
    return min(
        range(start, end),
        key=lambda index: route[index][0].transform.location.distance(location),
    )
