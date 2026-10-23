"""Small read/attach probe for locating CARLA startup hangs."""
import sys

import carla


def mark(message):
    print(message, flush=True)


client = carla.Client("127.0.0.1", 2000)
client.set_timeout(20.0)
mark("01 connected")
world = client.get_world()
mark(f"02 world {world.get_map().name}")
blueprints = world.get_blueprint_library()
vehicle_bp = blueprints.find("vehicle.tesla.model3")
spawn_points = world.get_map().get_spawn_points()
mark(f"03 spawn_points {len(spawn_points)}")
vehicle = None
for point in spawn_points:
    vehicle = world.try_spawn_actor(vehicle_bp, point)
    if vehicle is not None:
        break
if vehicle is None:
    raise RuntimeError("No free vehicle spawn point")
mark(f"04 vehicle {vehicle.id}")
sensors = []
try:
    topology = world.get_map().get_topology()
    mark(f"05 topology {len(topology)}")
    camera_bp = blueprints.find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", "320")
    camera_bp.set_attribute("image_size_y", "180")
    camera_bp.set_attribute("sensor_tick", "0.2")
    transforms = [
        carla.Transform(carla.Location(x=1.5, z=2.4), carla.Rotation(pitch=-10)),
        carla.Transform(carla.Location(x=-1.5, z=2.0), carla.Rotation(yaw=180, pitch=-8)),
        carla.Transform(carla.Location(x=-0.35, y=-1.02, z=1.62), carla.Rotation(yaw=-158, pitch=-5)),
        carla.Transform(carla.Location(x=-0.35, y=1.02, z=1.62), carla.Rotation(yaw=158, pitch=-5)),
    ]
    for index, transform in enumerate(transforms, start=1):
        sensor = world.spawn_actor(camera_bp, transform, attach_to=vehicle)
        sensor.listen(lambda _image: None)
        sensors.append(sensor)
        mark(f"{5 + index:02d} camera_{index} {sensor.id}")
    world.wait_for_tick(seconds=10.0)
    mark("10 tick received")
finally:
    for sensor in sensors:
        sensor.stop()
        sensor.destroy()
    vehicle.destroy()
    mark("11 cleanup")
