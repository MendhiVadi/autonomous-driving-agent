"""Decisions for a stationary neural-route car that cannot restart, without a simulator.

The start assist only helps a car already within about a lane of its route. A car
further off (or angled more than 15 degrees) used to sit braked forever with
"MODEL STOP - REALIGN MANUALLY". ``OffRouteMonitor`` times that state and says when
to put the car back on its route; the cockpit publishes the countdown to the HUD
and the activity page.
"""
import time

LANE_LIMIT_M = 1.2
LANE_LIMIT_ASSISTED_M = 1.6
HEADING_LIMIT_DEG = 15.0
REALIGN_DELAY_S = 3.0
MAX_AUTO_REALIGNS = 3
MAX_SNAP_DISTANCE_M = 40.0
SNAP_SEARCH_WAYPOINTS = 30
OCCUPIED_RADIUS_M = 4.0
# Mirror learning.assistance.apply_stall_recovery's defaults (tests keep them in step).
START_DELAY_S = 2.0
START_BRAKE_DELAY_S = 5.0
MODEL_BRAKE_REQUEST = 0.45


def is_off_route(features, lane_assist):
    """True when lane error or heading error is beyond what start assist tolerates."""
    limit = LANE_LIMIT_ASSISTED_M if lane_assist else LANE_LIMIT_M
    return abs(float(features[0])) > limit or abs(float(features[1])) > HEADING_LIMIT_DEG


def start_wait_total(model_brake):
    """Seconds the stall recovery waits before it overrides a stopped car's brake."""
    return START_BRAKE_DELAY_S if float(model_brake) >= MODEL_BRAKE_REQUEST else START_DELAY_S


def wait_report(kind, label, elapsed_s, total_s):
    """The ``runtime.wait`` object the activity page expects."""
    total = max(0.1, float(total_s))
    return {"kind": kind, "label": str(label)[:40],
            "elapsed_s": round(max(0.0, min(float(elapsed_s), total)), 2),
            "total_s": round(total, 2)}


class OffRouteMonitor:
    """Times a stationary, off-route car and rations automatic re-alignments."""

    def __init__(self, delay_s=REALIGN_DELAY_S, max_attempts=MAX_AUTO_REALIGNS, clock=time.monotonic):
        self.delay_s = float(delay_s)
        self.max_attempts = int(max_attempts)
        self.clock = clock
        self.attempts = 0
        self._since = None

    def reset_route(self):
        """A new route gets a fresh allowance."""
        self.attempts = 0
        self._since = None

    def update(self, stationary, off_route, blocked):
        """Return ``{"phase", "elapsed_s", "total_s"}``.

        Phases: ``idle`` (nothing to recover), ``waiting`` (counting down), ``ready``
        (re-align now), ``exhausted`` (allowance used up; needs the driver).
        ``blocked`` (collision, obstacle, red light) pauses the clock: those stops are
        deliberate and are never "recovered" automatically.
        """
        if not (stationary and off_route) or blocked:
            self._since = None
            return {"phase": "idle", "elapsed_s": 0.0, "total_s": self.delay_s}
        now = self.clock()
        if self._since is None:
            self._since = now
        elapsed = now - self._since
        if self.attempts >= self.max_attempts:
            return {"phase": "exhausted", "elapsed_s": elapsed, "total_s": self.delay_s}
        if elapsed >= self.delay_s:
            return {"phase": "ready", "elapsed_s": self.delay_s, "total_s": self.delay_s}
        return {"phase": "waiting", "elapsed_s": elapsed, "total_s": self.delay_s}

    def record_attempt(self):
        self.attempts += 1
        self._since = None


def choose_snap_index(plan, location, route_index, max_distance_m=MAX_SNAP_DISTANCE_M,
                      search=SNAP_SEARCH_WAYPOINTS):
    """Nearest planned waypoint at or ahead of ``route_index``; ``None`` if none is close enough."""
    if not plan:
        return None
    start = max(0, min(int(route_index), len(plan) - 1))
    end = min(len(plan), start + max(1, int(search)))
    best = min(range(start, end), key=lambda i: plan[i][0].transform.location.distance(location))
    if plan[best][0].transform.location.distance(location) > max_distance_m:
        return None
    return best


def snap_pose(plan, index, lift_m=0.3):
    """``((x, y, z), yaw)`` for the car on waypoint ``index``, lifted slightly off the road."""
    transform = plan[index][0].transform
    location = transform.location
    return (location.x, location.y, location.z + lift_m), transform.rotation.yaw


def spot_is_free(target, others, radius_m=OCCUPIED_RADIUS_M):
    """False if another road user is within ``radius_m`` of the target point."""
    return all(other.distance(target) > radius_m for other in others)
