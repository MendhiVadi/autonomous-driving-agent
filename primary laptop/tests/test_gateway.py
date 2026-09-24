import socket
import threading
import time
import unittest

from sim_host.environment import EpisodeEnvironment
from sim_host.carla_backend import CarlaBackend
from sim_host.gateway import Gateway
from sim_host.rehearsal import RehearsalBackend
from sim_host.wire import ProtocolError, receive, send

TOKEN = "test-secret-not-for-deployment-12345678"


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.backend = RehearsalBackend()
        self.env = EpisodeEnvironment(self.backend)
        self.server = Gateway(("127.0.0.1", 0), TOKEN, self.env, lease_seconds=.3)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.thread.start()
        self.connections = []

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.env.close()

    def connect(self, token=TOKEN):
        connection = socket.create_connection(self.server.server_address, timeout=2)
        self.connections.append(connection)
        send(connection, {"version": 1, "type": "hello", "token": token})
        reply = receive(connection, time.monotonic() + 2)
        return connection, reply

    def command(self, reply, op="reset", payload=None):
        return {"version": 1, "session": reply["session"], "sequence": reply["sequence"] + 1,
                "nonce": reply["nonce"], "operation": op,
                "payload": {"seed": 7, "scenario": "lane_follow", "max_steps": 5} if payload is None else payload}

    def exchange(self, connection, message):
        send(connection, message)
        return receive(connection, time.monotonic() + 2)

    def wait_aborted(self):
        deadline = time.monotonic() + 2
        while self.env.active and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.env.active)
        self.assertEqual(self.backend.last_action["brake"], 1)

    def test_authentication_required(self):
        connection, reply = self.connect("incorrect")
        self.assertFalse(reply["ok"])
        self.assertFalse(self.env.active)

    def test_non_ascii_auth_rejected_without_server_crash(self):
        _, reply = self.connect("é" * 32)
        self.assertFalse(reply["ok"])
        _, reply = self.connect()
        self.assertTrue(reply["ok"])

    def test_reset_step_close_over_real_socket(self):
        connection, reply = self.connect()
        reply = self.exchange(connection, self.command(reply))
        self.assertTrue(reply["ok"])
        reply = self.exchange(connection, self.command(reply, "step", {"throttle": .2, "brake": 0, "steer": 0}))
        self.assertGreater(reply["result"]["observation"]["speed_mps"], 0)
        reply = self.exchange(connection, self.command(reply, "close", {}))
        self.assertTrue(reply["result"]["closed"])
        self.wait_aborted()

    def test_replay_terminates_session(self):
        connection, reply = self.connect()
        message = self.command(reply)
        self.exchange(connection, message)
        result = self.exchange(connection, message)
        self.assertFalse(result["ok"])
        self.wait_aborted()

    def test_sequence_session_nonce_and_version_rejected(self):
        for name, value in (("sequence", 4), ("sequence", True), ("session", "old"),
                            ("nonce", "old"), ("version", True), ("version", 2)):
            with self.subTest(name=name, value=value):
                connection, reply = self.connect()
                reply = self.exchange(connection, self.command(reply))
                message = self.command(reply, "step", {"throttle": .2, "brake": 0, "steer": 0})
                message[name] = value
                self.assertFalse(self.exchange(connection, message)["ok"])
                self.wait_aborted()
                connection.close()

    def test_disconnect_brakes(self):
        connection, reply = self.connect()
        self.exchange(connection, self.command(reply))
        connection.close()
        self.wait_aborted()

    def test_silent_client_lease_expires(self):
        connection, reply = self.connect()
        self.exchange(connection, self.command(reply))
        self.wait_aborted()

    def test_reconnect_requires_fresh_reset(self):
        connection, reply = self.connect()
        old = self.exchange(connection, self.command(reply))
        connection.close()
        self.wait_aborted()
        connection, reply = self.connect()
        self.assertNotEqual(old["session"], reply["session"])
        result = self.exchange(connection, self.command(reply, "step", {"throttle": .2, "brake": 0, "steer": 0}))
        self.assertFalse(result["ok"])

    def test_unknown_field_fails_closed(self):
        connection, reply = self.connect()
        reply = self.exchange(connection, self.command(reply))
        request = self.command(reply)
        request["unexpected"] = 1
        self.assertFalse(self.exchange(connection, request)["ok"])
        self.wait_aborted()

    def test_unsupported_carla_scenario_allows_a_fresh_session(self):
        original = self.backend.reset

        def empty_road_only(seed, scenario):
            if scenario != "lane_follow":
                # Exercise the real adapter's validation without importing CARLA.
                return CarlaBackend.reset(object(), seed, scenario)
            return original(seed, scenario)

        self.backend.reset = empty_road_only
        for scenario in ("red_light", "obstacle"):
            with self.subTest(scenario=scenario):
                connection, reply = self.connect()
                rejected = self.exchange(connection, self.command(reply, payload={
                    "seed": 7, "scenario": scenario, "max_steps": 5}))
                self.assertFalse(rejected["ok"])
                self.wait_aborted()
                self.assertIsNone(self.server.fatal_error)
                connection.close()
                connection, reply = self.connect()
                reply = self.exchange(connection, self.command(reply))
                self.assertTrue(reply["ok"])
                self.assertTrue(self.exchange(connection, self.command(reply, "close", {}))["ok"])
                connection.close()
                self.wait_aborted()

    def test_disconnect_brake_failure_is_visible_to_launcher(self):
        connection, reply = self.connect()
        self.exchange(connection, self.command(reply))
        original = self.backend.brake
        failure = RuntimeError("simulated braking RPC failure")

        def broken():
            raise failure

        self.backend.brake = broken
        try:
            with self.assertLogs(level="ERROR"):
                connection.close()
                deadline = time.monotonic() + 2
                while not self.server.completed_sessions and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertEqual(self.server.completed_sessions, 1)
                self.assertIs(self.server.fatal_error, failure)
        finally:
            self.backend.brake = original

    def test_nonloopback_binding_refused(self):
        with self.assertRaises(ValueError):
            Gateway(("0.0.0.0", 0), TOKEN, self.env)

    def test_weak_token_refused(self):
        with self.assertRaises(ValueError):
            Gateway(("127.0.0.1", 0), "short", self.env)

    def test_slow_reset_is_not_confused_with_stale_command(self):
        original = self.backend.reset
        def slow(seed, scenario):
            time.sleep(.4)
            return original(seed, scenario)
        self.backend.reset = slow
        connection, reply = self.connect()
        reply = self.exchange(connection, self.command(reply))
        self.assertTrue(reply["ok"])
        self.assertTrue(self.env.active)
        reply = self.exchange(connection, self.command(reply, "close", {}))
        self.assertTrue(reply["ok"])

    def test_fatal_backend_error_is_visible_to_launcher(self):
        def broken(seed, scenario):
            raise RuntimeError("simulated map load failure")
        self.backend.reset = broken
        connection, reply = self.connect()
        with self.assertLogs(level="ERROR"):
            with self.assertRaises(ConnectionError):
                self.exchange(connection, self.command(reply))
        self.assertIsInstance(self.server.fatal_error, RuntimeError)
        self.wait_aborted()
