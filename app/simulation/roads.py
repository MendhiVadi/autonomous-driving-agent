"""Sample lane curves once and cheaply select nearby segments for map drawing."""
import math
from collections import defaultdict


def build_road_segments(carla_map, spacing=3.0):
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Road spacing must be positive and finite')
    lanes = defaultdict(dict)
    points = list(carla_map.generate_waypoints(spacing))
    # Include boundaries so adjacent sections meet without cutting across bends.
    for start, end in carla_map.get_topology():
        points.extend((start, end))
    for waypoint in points:
        location = waypoint.transform.location
        lanes[(waypoint.road_id, waypoint.section_id, waypoint.lane_id)][waypoint.s] = (
            location.x, location.y)
    segments = []
    for lane in lanes.values():
        ordered = sorted(lane.items())
        for (s1, start), (s2, end) in zip(ordered, ordered[1:]):
            # Never bridge a missing piece of lane or a discontinuity.
            distance = math.dist(start, end)
            if 0 < distance <= spacing * 2.1 and s2 - s1 <= spacing * 2.1:
                segments.append((start, end))
    if not segments:
        raise ValueError('No drawable driving lanes in this map')
    return segments


class RoadSegmentIndex:
    def __init__(self, segments, cell_size=50.0):
        if not math.isfinite(cell_size) or cell_size <= 0:
            raise ValueError('Cell size must be positive and finite')
        self.segments = segments
        self.cell_size = cell_size
        self.cells = defaultdict(list)
        for index, (start, end) in enumerate(segments):
            for cell in self._cells(min(start[0], end[0]), min(start[1], end[1]),
                                    max(start[0], end[0]), max(start[1], end[1])):
                self.cells[cell].append(index)

    def _cells(self, x1, y1, x2, y2):
        for x in range(math.floor(x1 / self.cell_size), math.floor(x2 / self.cell_size) + 1):
            for y in range(math.floor(y1 / self.cell_size), math.floor(y2 / self.cell_size) + 1):
                yield x, y

    def nearby(self, x, y, radius):
        indices = set()
        for cell in self._cells(x - radius, y - radius, x + radius, y + radius):
            indices.update(self.cells.get(cell, ()))
        return (self.segments[index] for index in sorted(indices))
