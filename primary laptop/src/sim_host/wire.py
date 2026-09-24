"""Versioned, bounded JSON-lines transport. Independent application-owned copy."""
import json
import math
import socket
import time

VERSION = 1
MAX_BYTES = 16384


class ProtocolError(ValueError):
    pass


def finite(value, name, low, high):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    except OverflowError:
        valid = False
    if not valid:
        raise ProtocolError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError(f"{name} must be an integer in [{low}, {high}]")
    return value


def fields(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ProtocolError("Unexpected or missing message fields")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("Duplicate JSON field")
        result[key] = value
    return result


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ProtocolError("Nonfinite JSON number")
    return number


def encode(message):
    try:
        data = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    except (ValueError, TypeError, OverflowError) as exc:
        raise ProtocolError("Message is not finite JSON") from exc
    if len(data) > MAX_BYTES:
        raise ProtocolError("Message exceeds size limit")
    return data


def receive(connection, deadline):
    """Absolute local deadline defeats slow-drip messages; no pipelined commands."""
    buffer = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Message deadline expired")
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, MAX_BYTES + 1 - len(buffer)))
        if not chunk:
            raise ConnectionError("Peer disconnected")
        buffer.extend(chunk)
        if len(buffer) > MAX_BYTES:
            raise ProtocolError("Message exceeds size limit")
        if b"\n" in buffer:
            if not buffer.endswith(b"\n") or buffer.count(b"\n") != 1:
                raise ProtocolError("Pipelined messages are not allowed")
            try:
                message = json.loads(buffer, object_pairs_hook=_object, parse_float=_float,
                                     parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("Nonfinite JSON")))
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise ProtocolError("Invalid JSON message") from exc
            if not isinstance(message, dict):
                raise ProtocolError("Message must be an object")
            return message


def send(connection, message, timeout=2.0):
    connection.settimeout(timeout)
    connection.sendall(encode(message))
