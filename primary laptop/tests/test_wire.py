import socket
import time
import unittest

from sim_host.wire import MAX_BYTES, ProtocolError, encode, receive


class WireTests(unittest.TestCase):
    def decode(self, payload):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        left.sendall(payload)
        return receive(right, time.monotonic() + .2)

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'{"x":1,"x":2}\n')

    def test_nonfinite_rejected(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'{"x":NaN}\n')

    def test_exponent_overflow_rejected(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'{"x":1e999}\n')

    def test_trailing_commands_rejected(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'{}\n{}\n')

    def test_object_required(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'[]\n')

    def test_invalid_utf8_rejected(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'{"x":"\xff"}\n')

    def test_missing_newline_times_out(self):
        with self.assertRaises(TimeoutError):
            self.decode(b'{}')

    def test_oversized_frame_rejected(self):
        with self.assertRaises(ProtocolError):
            self.decode(b'x' * (MAX_BYTES + 1))

    def test_encode_rejects_nonfinite_and_large(self):
        for message in ({"x": float("nan")}, {"x": "a" * MAX_BYTES}):
            with self.assertRaises(ProtocolError):
                encode(message)
