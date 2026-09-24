"""Serializable CARLA map features for the Device 2 overhead map."""
import math


def _point(location):
    return {"x": round(location.x, 2), "y": round(location.y, 2), "z": round(location.z, 2)}


def _angle_difference(left, right):
    return (left - right + 180.0) % 360.0 - 180.0


def _choose_continuation(cursor, choices):
    """Prefer the smallest turn relative to the current route segment."""
    previous_yaw = cursor.transform.rotation.yaw
    return min(choices, key=lambda item: abs(_angle_difference(
        item.transform.rotation.yaw, previous_yaw
    )))


def build_map_features(vehicle, world, radius_m=80.0, sample_m=5.0):
    """Return ego lane, nearby route geometry, lights, and road metadata."""
    carla_map = world.get_map()
    transform = vehicle.get_transform()
    waypoint = carla_map.get_waypoint(transform.location, project_to_road=True)
    if waypoint is None:
        raise RuntimeError("Vehicle is outside the drivable map; no map features are available.")
    route = []
    cursor = waypoint
    for _ in range(max(1, int(radius_m / sample_m))):
        route.append(_point(cursor.transform.location))
        choices = cursor.next(sample_m)
        if not choices:
            break
        cursor = _choose_continuation(cursor, choices)

    lights = []
    for light in world.get_actors().filter("traffic.traffic_light*"):
        location = light.get_transform().location
        dx = location.x - transform.location.x
        dy = location.y - transform.location.y
        if math.hypot(dx, dy) <= radius_m:
            lights.append({"id": light.id, "state": str(light.state), "location": _point(location)})

    return {
        "map": carla_map.name,
        "ego": _point(transform.location),
        "ego_yaw_deg": round(transform.rotation.yaw, 2),
        "road_id": waypoint.road_id,
        "lane_id": waypoint.lane_id,
        "lane_type": str(waypoint.lane_type),
        "is_junction": waypoint.is_junction,
        "route_ahead": route,
        "traffic_lights": lights,
    }
