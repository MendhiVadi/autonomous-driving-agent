"""Route-planning wrapper kept separate from the trainable policy."""
import os
import sys
from pathlib import Path


def _load_agents():
    root = Path(os.environ.get("CARLA_ROOT", r"C:\Users\medha\Documents\CARLA\CARLA_0.9.16"))
    agents_root = str(root / "PythonAPI" / "carla")
    if agents_root not in sys.path:
        sys.path.insert(0, agents_root)


def plan_route(world, origin, destination, sampling_resolution=2.0):
    _load_agents()
    from agents.navigation.global_route_planner import GlobalRoutePlanner
    planner = GlobalRoutePlanner(world.get_map(), sampling_resolution)
    return planner.trace_route(origin, destination)
