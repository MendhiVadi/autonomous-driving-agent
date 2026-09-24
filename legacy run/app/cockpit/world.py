"""Small vehicle queries and spawn selection shared by the cockpit."""
import math

def vehicle_speed_kmh(vehicle):
    velocity = vehicle.get_velocity()
    return math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) * 3.6


def nearest_distances(vehicle, world, actors=None):
    """Nearest road-user distance in each mirror direction, in metres."""
    transform = vehicle.get_transform()
    location = transform.location
    forward = transform.get_forward_vector()
    right = transform.get_right_vector()
    nearest = {"front": 80.0, "rear": 80.0, "left": 80.0, "right": 80.0}
    if actors is None:
        actors = list(world.get_actors().filter("vehicle.*")) + list(world.get_actors().filter("walker.*"))
    for actor in actors:
        if actor.id == vehicle.id:
            continue
        relative = actor.get_location() - location
        distance = relative.length()
        longitudinal = relative.x * forward.x + relative.y * forward.y
        lateral = relative.x * right.x + relative.y * right.y
        if abs(longitudinal) >= abs(lateral):
            key = "front" if longitudinal >= 0 else "rear"
        else:
            key = "right" if lateral >= 0 else "left"
        nearest[key] = min(nearest[key], distance)
    return nearest


def try_spawn_vehicle(world, blueprint, spawn_points):
    """Try every candidate spawn point until CARLA accepts one."""
    for point in spawn_points:
        vehicle = world.try_spawn_actor(blueprint, point)
        if vehicle is not None:
            return vehicle
    return None
