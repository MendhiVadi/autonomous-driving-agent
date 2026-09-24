"""Framework-neutral remote reset/step client."""
import socket
import time

from rl_client.wire import VERSION, ProtocolError, fields, finite, integer, receive, send
from rl_client.transport import local_address, secure_socket


class RemoteEnvironment:
    """Gym-style return values without importing or installing a learning framework.

    No retries: a lost reply may follow an applied action. Reconnect and reset.
    Private-network addresses require the paired server's certificate.
    """

    def __init__(self, token, host="127.0.0.1", port=8765, timeout=180.0, certificate=None):
        host = local_address(host)
        if host != "127.0.0.1" and certificate is None:
            raise ValueError("Private-network operation requires a paired TLS certificate")
        integer(port, "port", 1, 65535)
        finite(timeout, "timeout", 0.1, 180)
        if not isinstance(token, str) or len(token) < 32 or not token.isascii():
            raise ValueError("A secret of at least 32 ASCII characters is required")
        self.socket = None
        self.active = False
        self.timeout = timeout
        try:
            self.socket = socket.create_connection((host, port), timeout=min(timeout, 5))
            if certificate is not None:
                self.socket = secure_socket(self.socket, certificate)
            send(self.socket, {"version": VERSION, "type": "hello", "token": token})
            reply = self._reply()
            if reply["sequence"] != 0:
                raise ProtocolError("Invalid initial sequence")
            self.session = reply["session"]
            self.sequence = 0
            self.nonce = reply["nonce"]
            self.backend = reply["result"].get("backend")
        except Exception:
            self.disconnect()
            raise

    def _reply(self):
        reply = receive(self.socket, time.monotonic() + self.timeout)
        if reply.get("ok") is not True:
            raise ProtocolError("Host rejected the session; reconnect and reset")
        fields(reply, ("version", "ok", "session", "sequence", "nonce", "lease_seconds", "result"))
        integer(reply["version"], "version", VERSION, VERSION)
        integer(reply["sequence"], "sequence", 0, 2**31 - 1)
        finite(reply["lease_seconds"], "lease_seconds", 0.1, 10)
        for name in ("session", "nonce"):
            value = reply[name]
            if not isinstance(value, str) or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
                raise ProtocolError("Invalid session identity")
        if not isinstance(reply["result"], dict):
            raise ProtocolError("Result must be an object")
        return reply

    def _request(self, operation, payload):
        if self.socket is None:
            raise RuntimeError("Connection is closed; reconnect and reset")
        try:
            expected = self.sequence + 1
            send(self.socket, {"version": VERSION, "session": self.session, "sequence": expected,
                               "nonce": self.nonce, "operation": operation, "payload": payload})
            reply = self._reply()
            if reply["session"] != self.session or reply["sequence"] != expected or reply["nonce"] == self.nonce:
                raise ProtocolError("Response identity or ordering mismatch")
            self.sequence, self.nonce = expected, reply["nonce"]
            return reply["result"]
        except Exception:
            self.disconnect()
            raise

    def reset(self, *, seed=0, scenario="lane_follow", max_steps=400):
        self.active = False
        result = self._request("reset", {"seed": seed, "scenario": scenario, "max_steps": max_steps})
        try:
            fields(result, ("observation", "info"))
            validate_observation(result["observation"])
            if not isinstance(result["info"], dict):
                raise ProtocolError("Invalid reset info")
        except Exception:
            self.disconnect()
            raise
        self.active = True
        return result["observation"], result["info"]

    def step(self, action):
        if not self.active:
            raise RuntimeError("Reset is required before step")
        result = self._request("step", action)
        try:
            fields(result, ("observation", "reward", "terminated", "truncated", "info"))
            validate_observation(result["observation"])
            finite(result["reward"], "reward", -1000000, 1000000)
            if (type(result["terminated"]) is not bool or type(result["truncated"]) is not bool or
                    result["terminated"] and result["truncated"] or not isinstance(result["info"], dict)):
                raise ProtocolError("Invalid step result")
        except Exception:
            self.disconnect()
            raise
        self.active = not (result["terminated"] or result["truncated"])
        return (result["observation"], result["reward"], result["terminated"], result["truncated"], result["info"])

    def disconnect(self):
        self.active = False
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def close(self):
        try:
            if self.socket is not None:
                self._request("close", {})
        except (OSError, ConnectionError, ProtocolError):
            pass
        finally:
            self.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def validate_observation(state):
    fields(state, ("speed_mps", "lateral_m", "heading_error_rad", "progress_m", "route_length_m",
                   "speed_limit_mps", "stop_required", "obstacle_distance_m", "collision", "offroad"))
    for name, value in state.items():
        if name in ("stop_required", "collision", "offroad"):
            if type(value) is not bool:
                raise ProtocolError("Invalid observation flag")
        else:
            finite(value, name, -100000, 100000)
    if (state["speed_mps"] < 0 or state["obstacle_distance_m"] < 0 or
            state["route_length_m"] <= 0 or state["speed_limit_mps"] <= 0 or
            not 0 <= state["progress_m"] <= state["route_length_m"]):
        raise ProtocolError("Invalid observation bounds")
