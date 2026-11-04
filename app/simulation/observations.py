"""CARLA state observations for the retained eight-input policy."""
import math

def wrap_angle(angle):
    if not math.isfinite(angle):
        raise ValueError("Heading must be finite")
    # Constant time even for corrupt but finite, very large angles.
    angle = math.fmod(angle, 360.0)
    if angle > 180.0:
        angle -= 360.0
    elif angle < -180.0:
        angle += 360.0
    return angle


def dot(a, b):
    return a.x * b.x + a.y * b.y + a.z * b.z


def make_observation(vehicle, world, red_state, nearby_vehicles=None,
                     target_speed_kmh=35.0, reference_waypoint=None, carla_map=None):
    transform = vehicle.get_transform()
    location = transform.location
    if carla_map is None:
        carla_map = world.get_map()
    waypoint = carla_map.get_waypoint(location, project_to_road=True)
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
