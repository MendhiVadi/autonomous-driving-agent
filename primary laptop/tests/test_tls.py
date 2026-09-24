"""Real TLS sockets with disposable test-only certificate and token."""
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from sim_host.environment import EpisodeEnvironment
from sim_host.gateway import Gateway
from sim_host.rehearsal import RehearsalBackend
from sim_host.transport import local_address, load_token, server_context
from sim_host.wire import receive, send


class TlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name) / "pairing"
        script = Path(__file__).resolve().parents[1] / "prepare_pairing.py"
        result = subprocess.run([sys.executable, "-I", "-B", str(script), "--directory", str(cls.directory)],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError("Test certificate generation failed: " + result.stderr)

    def setUp(self):
        self.environment = EpisodeEnvironment(RehearsalBackend())
        self.server = Gateway(("127.0.0.1", 0), load_token(self.directory), self.environment,
                              tls_context=server_context(self.directory), lease_seconds=.2)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.environment.close()

    def connect(self, trusted=True, hostname="carla-sim-host"):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if trusted:
            context.load_verify_locations(str(self.directory / "server-cert.pem"))
        raw = socket.create_connection(self.server.server_address, timeout=2)
        try:
            connection = context.wrap_socket(raw, server_hostname=hostname)
        except Exception:
            raw.close()
            raise
        self.addCleanup(connection.close)
        return connection

    def test_certificate_and_token_allow_authenticated_session(self):
        connection = self.connect()
        send(connection, {"version": 1, "type": "hello", "token": load_token(self.directory)})
        reply = receive(connection, time.monotonic() + 2)
        self.assertTrue(reply["ok"])
        self.assertIn(connection.version(), ("TLSv1.2", "TLSv1.3"))

    def test_wrong_token_rejected_inside_tls(self):
        connection = self.connect()
        send(connection, {"version": 1, "type": "hello", "token": "wrong"})
        self.assertFalse(receive(connection, time.monotonic() + 2)["ok"])
        self.assertFalse(self.environment.active)

    def test_unknown_certificate_rejected_before_authentication(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.connect(trusted=False)
        self.assertFalse(self.environment.active)

    def test_wrong_server_name_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.connect(hostname="another-server")

    def test_plaintext_is_not_accepted_on_tls_socket(self):
        with socket.create_connection(self.server.server_address, timeout=2) as connection:
            send(connection, {"version": 1, "type": "hello", "token": "not-a-secret"})
            try:
                data = connection.recv(1024)
            except (OSError, ConnectionError):
                data = b""
            self.assertNotIn(b'"ok":true', data)
        self.assertFalse(self.environment.active)

    def test_peer_allowlist_rejects_unpaired_address(self):
        self.server.allowed_peer = "192.168.100.200"
        with socket.create_connection(self.server.server_address, timeout=2) as connection:
            self.assertEqual(connection.recv(1), b"")

    def test_expired_command_lease_brakes_over_tls(self):
        connection = self.connect()
        send(connection, {"version": 1, "type": "hello", "token": load_token(self.directory)})
        reply = receive(connection, time.monotonic() + 2)
        send(connection, {"version": 1, "session": reply["session"], "sequence": 1,
                          "nonce": reply["nonce"], "operation": "reset",
                          "payload": {"seed": 7, "scenario": "lane_follow", "max_steps": 5}})
        receive(connection, time.monotonic() + 2)
        end = time.monotonic() + 2
        while self.environment.active and time.monotonic() < end:
            time.sleep(.01)
        self.assertFalse(self.environment.active)
        self.assertEqual(self.environment.backend.last_action["brake"], 1)

    def test_public_wildcard_and_hostnames_refused(self):
        for host in ("0.0.0.0", "8.8.8.8", "::1", "localhost", "127.0.0.2"):
            with self.assertRaises(ValueError):
                local_address(host)

    def test_private_bind_requires_tls_and_exact_peer(self):
        for options in ({}, {"tls_context": server_context(self.directory)}):
            with self.assertRaises(ValueError):
                Gateway(("192.168.1.2", 0), load_token(self.directory), self.environment, **options)
