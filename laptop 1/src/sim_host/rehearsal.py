"""Deterministic toy physics for transport testing, NOT a driving simulator."""
import math
import random
import threading

from sim_host.environment import DT


class RehearsalBackend:
    name = "rehearsal-toy"

    def __init__(self):
        self.lock = threading.Lock()
        self.last_action = {"throttle": 0.0, "brake": 1.0, "steer": 0.0}
        self.brake_count = 0
        self.state = None

    def reset(self, seed, scenario):
        with self.lock:
            self.scenario = scenario
            self.x = self.y = self.yaw = self.speed = 0.0
            self.route_length = random.Random(seed).uniform(60, 80)
            return self.snapshot()

    def snapshot(self):
        return {"speed_mps": self.speed, "lateral_m": self.y,
                "heading_error_rad": self.yaw, "progress_m": min(self.route_length, max(0, self.x)),
                "route_length_m": self.route_length, "speed_limit_mps": 8.33,
                "stop_required": self.scenario == "red_light",
                "obstacle_distance_m": max(0, 8 - self.x) if self.scenario == "obstacle" else 100.0,
                "collision": self.scenario == "obstacle" and self.x >= 8,
                "offroad": abs(self.y) > 1.75}

    def step(self, action):
        with self.lock:
            self.last_action = dict(action)
            self.speed = max(0, self.speed + (4 * action["throttle"] - 8 * action["brake"] - 0.15 * self.speed) * DT)
            self.yaw += action["steer"] * self.speed * DT * 0.12
            self.x += self.speed * math.cos(self.yaw) * DT
            self.y += self.speed * math.sin(self.yaw) * DT
            return self.snapshot()

    def brake(self):
        with self.lock:
            self.last_action = {"throttle": 0.0, "brake": 1.0, "steer": 0.0}
            self.brake_count += 1

    def close(self):
        self.brake()
