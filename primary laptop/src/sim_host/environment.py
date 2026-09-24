"""Framework-neutral reset/step contract; no model or learning dependencies."""
import math

from sim_host.wire import ProtocolError, fields, finite, integer

DT = 0.05
OBSERVATION_KEYS = (
    "speed_mps", "lateral_m", "heading_error_rad", "progress_m", "route_length_m",
    "speed_limit_mps", "stop_required", "obstacle_distance_m", "collision", "offroad",
)
SCENARIOS = ("lane_follow", "red_light", "obstacle")


def action_values(action):
    fields(action, ("throttle", "brake", "steer"))
    return {name: finite(action[name], name, -1 if name == "steer" else 0, 1)
            for name in ("throttle", "brake", "steer")}


def validate_snapshot(state):
    fields(state, OBSERVATION_KEYS)
    for name in ("stop_required", "collision", "offroad"):
        if type(state[name]) is not bool:
            raise ProtocolError(f"{name} must be boolean")
    for name in set(OBSERVATION_KEYS) - {"stop_required", "collision", "offroad"}:
        finite(state[name], name, -100000, 100000)
    for name in ("speed_mps", "progress_m", "obstacle_distance_m"):
        if state[name] < 0:
            raise ProtocolError(f"{name} cannot be negative")
    if state["route_length_m"] <= 0 or state["speed_limit_mps"] <= 0:
        raise ProtocolError("Route length and speed limit must be positive")
    if state["progress_m"] > state["route_length_m"]:
        raise ProtocolError("Progress exceeds route length")
    return dict(state)


def safe_action(requested, state):
    applied = dict(requested)
    reasons = []
    if applied["brake"] > 0:
        applied["throttle"] = 0.0
    applied["throttle"] = min(applied["throttle"], 0.4)
    applied["steer"] = max(-0.7, min(0.7, applied["steer"]))
    if applied != requested:
        reasons.append("control_limits")
    speed = state["speed_mps"]
    if speed >= min(state["speed_limit_mps"], 8.33):
        applied["throttle"], applied["brake"] = 0.0, max(0.3, applied["brake"])
        reasons.append("speed_limit")
    stopping_distance = 2 + speed * 0.8 + speed * speed / 8
    for blocked, reason in ((state["stop_required"], "signal_stop"),
                            (state["obstacle_distance_m"] <= stopping_distance, "obstacle_stop"),
                            (state["collision"] or state["offroad"], "unsafe_state")):
        if blocked:
            applied["throttle"], applied["brake"] = 0.0, 1.0
            reasons.append(reason)
    return applied, reasons


class EpisodeEnvironment:
    """Only the host advances physics. Rewards are provisional engineering aids."""

    def __init__(self, backend):
        self.backend = backend
        self.active = False
        self.state = None

    def reset(self, seed=0, scenario="lane_follow", max_steps=400):
        integer(seed, "seed", 0, 2**31 - 1)
        integer(max_steps, "max_steps", 1, 20000)
        if not isinstance(scenario, str) or scenario not in SCENARIOS:
            raise ProtocolError("Unknown scenario")
        self.active = False
        self.backend.brake()
        self.state = validate_snapshot(self.backend.reset(seed, scenario))
        self.steps, self.idle_steps = 0, 0
        self.max_steps = max_steps
        self.best_progress = self.state["progress_m"]
        self.active = True
        return {"observation": self.state, "info": {"backend": self.backend.name,
                "seed": seed, "scenario": scenario, "dt_seconds": DT,
                "backend_details": dict(getattr(self.backend, "details", {})),
                "reward_contract": "experimental-v1", "training_ready": False}}

    def step(self, action):
        if not self.active:
            raise ProtocolError("Reset required before stepping")
        try:
            requested = action_values(action)
            applied, interventions = safe_action(requested, self.state)
            state = validate_snapshot(self.backend.step(applied))
            if not math.isclose(state["route_length_m"], self.state["route_length_m"]):
                raise ProtocolError("Route changed during episode")
            delta = max(0.0, state["progress_m"] - self.best_progress)
            if delta > 8.33 * DT + 1:
                raise ProtocolError("Implausible route progress")
            self.best_progress = max(self.best_progress, state["progress_m"])
            self.steps += 1
            self.idle_steps = self.idle_steps + 1 if delta < 0.005 and not state["stop_required"] else 0
            reason = None
            if state["collision"]:
                reason = "collision"
            elif state["offroad"] or abs(state["lateral_m"]) > 1.5:
                reason = "off_route"
            elif abs(state["heading_error_rad"]) > math.pi / 2:
                reason = "wrong_way"
            elif state["progress_m"] >= state["route_length_m"] - 1:
                reason = "route_complete"
            terminated = reason is not None
            if not terminated and self.idle_steps >= 200:
                reason = "no_progress"
            elif not terminated and self.steps >= self.max_steps:
                reason = "step_limit"
            truncated = not terminated and reason is not None
            parts = {"new_progress": delta, "time": -0.01,
                     "lateral": -0.02 * abs(state["lateral_m"]),
                     "speeding": -0.1 * max(0, state["speed_mps"] - state["speed_limit_mps"]),
                     "intervention": -0.05 * bool(interventions),
                     "terminal": 10.0 if reason == "route_complete" else
                     -10.0 if terminated else -2.0 if reason == "no_progress" else 0.0}
            # Failures do not receive a simultaneous progress payout.
            if terminated and reason != "route_complete":
                parts["new_progress"] = 0.0
            self.state = state
            if terminated or truncated:
                self.active = False
                self.backend.brake()
            return {"observation": state, "reward": sum(parts.values()),
                    "terminated": terminated, "truncated": truncated,
                    "info": {"step": self.steps, "reason": reason,
                             "requested_action": requested, "applied_action": applied,
                             "interventions": interventions, "reward_parts": parts}}
        except Exception:
            self.abort()
            raise

    def abort(self):
        self.active = False
        self.backend.brake()

    def close(self):
        try:
            self.abort()
        finally:
            self.backend.close()
