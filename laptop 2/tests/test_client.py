import socket
import ssl
import unittest
from unittest.mock import patch

from rl_client.client import RemoteEnvironment, validate_observation
from rl_client.wire import ProtocolError, encode

TOKEN = "test-secret-not-for-deployment-12345678"
STATE = {"speed_mps": 0, "lateral_m": 0, "heading_error_rad": 0, "progress_m": 0,
         "route_length_m": 60, "speed_limit_mps": 8.33, "stop_required": False,
         "obstacle_distance_m": 100, "collision": False, "offroad": False}


def reply(sequence=0, result=None, **kw):
    message = {"version": 1, "ok": True, "session": "a" * 32, "sequence": sequence,
               "nonce": format(sequence, "032x"), "lease_seconds": 2,
               "result": result if result is not None else {"backend": "test"}}
    message.update(kw)
    return encode(message)


class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def recv(self, size):
        return self.messages.pop(0) if self.messages else b""

    def sendall(self, data):
        self.sent.append(data)

    def settimeout(self, timeout):
        pass

    def close(self):
        self.closed = True


class ClientTests(unittest.TestCase):
    def client(self, messages):
        fake = FakeSocket(messages)
        with patch("rl_client.client.socket.create_connection", return_value=fake):
            client = RemoteEnvironment(TOKEN)
        self.addCleanup(client.disconnect)
        return client, fake

    def test_reset_and_step_shapes(self):
        step = {"observation": STATE, "reward": -.01, "terminated": False, "truncated": True, "info": {}}
        client, fake = self.client([reply(), reply(1, {"observation": STATE, "info": {}}), reply(2, step)])
        observation, info = client.reset()
        self.assertEqual(observation, STATE)
        result = client.step({"throttle": 0, "brake": 1, "steer": 0})
        self.assertEqual(len(result), 5)
        with self.assertRaises(RuntimeError):
            client.step({"throttle": 0, "brake": 1, "steer": 0})

    def test_no_step_before_reset(self):
        client, fake = self.client([reply()])
        with self.assertRaises(RuntimeError):
            client.step({})
        self.assertEqual(len(fake.sent), 1)

    def test_lost_reply_closes_without_retry(self):
        client, fake = self.client([reply()])
        with self.assertRaises(ConnectionError):
            client.reset()
        self.assertTrue(fake.closed)
        self.assertEqual(len(fake.sent), 2)

    def test_replayed_or_wrong_identity_response_closes(self):
        for kw in ({"session": "b" * 32}, {"sequence": 0}, {"nonce": "0" * 32}, {"version": True}):
            with self.subTest(kw=kw):
                response = {"sequence": 1, "result": {"observation": STATE, "info": {}}}
                response.update(kw)
                client, fake = self.client([reply(), reply(**response)])
                with self.assertRaises(ProtocolError):
                    client.reset()
                self.assertTrue(fake.closed)

    def test_malformed_observation_closes(self):
        client, fake = self.client([reply(), reply(1, {"observation": dict(STATE, speed_mps=True), "info": {}})])
        with self.assertRaises(ProtocolError):
            client.reset()
        self.assertTrue(fake.closed)

    def test_invalid_terminal_flags_close(self):
        client, fake = self.client([reply(), reply(1, {"observation": STATE, "info": {}}),
                                   reply(2, {"observation": STATE, "reward": 0,
                                             "terminated": True, "truncated": True, "info": {}})])
        client.reset()
        with self.assertRaises(ProtocolError):
            client.step({"throttle": 0, "brake": 1, "steer": 0})
        self.assertTrue(fake.closed)

    def test_nonloopback_refused_before_socket_open(self):
        with patch("rl_client.client.socket.create_connection") as connect:
            with self.assertRaises(ValueError):
                RemoteEnvironment(TOKEN, host="192.168.1.2")
            connect.assert_not_called()

    def test_failed_handshake_closes_socket(self):
        fake = FakeSocket([encode({"ok": False})])
        with patch("rl_client.client.socket.create_connection", return_value=fake):
            with self.assertRaises(ProtocolError):
                RemoteEnvironment(TOKEN)
        self.assertTrue(fake.closed)

    def test_observation_bounds(self):
        for kw in ({"route_length_m": 0}, {"progress_m": 61}, {"speed_mps": float("inf")}, {"offroad": 1}):
            with self.assertRaises(ProtocolError):
                validate_observation(dict(STATE, **kw))

    def test_close_is_idempotent(self):
        client, fake = self.client([reply(), reply(1, {"closed": True})])
        client.close()
        client.close()
        self.assertTrue(fake.closed)
        self.assertEqual(len(fake.sent), 2)

    def test_certificate_failure_sends_no_token(self):
        fake = FakeSocket([])
        with patch("rl_client.client.socket.create_connection", return_value=fake), \
             patch("rl_client.client.secure_socket", side_effect=ssl.SSLCertVerificationError("wrong certificate")):
            with self.assertRaises(ssl.SSLCertVerificationError):
                RemoteEnvironment(TOKEN, certificate="paired-public-cert.pem")
        self.assertEqual(fake.sent, [])
        self.assertTrue(fake.closed)

    def test_tls_is_established_before_first_authentication_message(self):
        raw = FakeSocket([])
        encrypted = FakeSocket([reply()])
        with patch("rl_client.client.socket.create_connection", return_value=raw), \
             patch("rl_client.client.secure_socket", return_value=encrypted) as secure:
            client = RemoteEnvironment(TOKEN, certificate="paired-public-cert.pem")
        self.addCleanup(client.disconnect)
        secure.assert_called_once_with(raw, "paired-public-cert.pem")
        self.assertEqual(raw.sent, [])
        self.assertEqual(len(encrypted.sent), 1)
