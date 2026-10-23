"""Authenticated local/private-TLS gateway. No model or trainer."""
import argparse
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import socketserver
import threading
import time

from sim_host.environment import EpisodeEnvironment
from sim_host.rehearsal import RehearsalBackend
from sim_host.watchdog import CommandWatchdog
from sim_host.transport import local_address, load_token, server_context
from sim_host.wire import VERSION, ProtocolError, fields, finite, integer, receive, send


class Gateway(socketserver.TCPServer):
    allow_reuse_address = False
    request_queue_size = 2

    def __init__(self, address, token, environment, lease_seconds=2.0, tls_context=None, allowed_peer=None):
        host = local_address(address[0])
        if host != "127.0.0.1" and (tls_context is None or allowed_peer is None):
            raise ValueError("Private-network binding requires TLS and an explicit peer address")
        self.tls_context = tls_context
        self.allowed_peer = local_address(allowed_peer) if allowed_peer is not None else None
        integer(address[1], "port", 0, 65535)
        if not isinstance(token, str) or len(token) < 32 or not token.isascii():
            raise ValueError("Set SIM_GATEWAY_TOKEN to at least 32 ASCII characters")
        self.token = token
        self.environment = environment
        self.lease_seconds = finite(lease_seconds, "lease_seconds", 0.1, 10)
        self.end_time = float("inf")
        self.completed_sessions = 0
        self.fatal_error = None
        super().__init__(address, GatewayHandler)

    def verify_request(self, request, client_address):
        return self.allowed_peer is None or client_address[0] == self.allowed_peer


class GatewayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        env = server.environment
        authenticated = False
        watchdog = CommandWatchdog(server.lease_seconds, min(0.05, server.lease_seconds / 4))
        expired = threading.Event()

        def stale():
            expired.set()
            env.abort()
            try:
                self.request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        try:
            if server.tls_context is not None:
                self.request.settimeout(3)
                self.request = server.tls_context.wrap_socket(self.request, server_side=True)
            hello = receive(self.request, time.monotonic() + 2)
            fields(hello, ("version", "type", "token"))
            integer(hello["version"], "version", VERSION, VERSION)
            if hello["type"] != "hello" or not isinstance(hello["token"], str) or not hello["token"].isascii():
                raise ProtocolError("Authentication failed")
            if not hmac.compare_digest(hello["token"], server.token):
                raise ProtocolError("Authentication failed")
            authenticated = True
            session, nonce, seq = secrets.token_hex(16), secrets.token_hex(16), 0
            deadline = time.monotonic() + server.lease_seconds
            send(self.request, {"version": VERSION, "ok": True, "session": session,
                                "sequence": seq, "nonce": nonce, "lease_seconds": server.lease_seconds,
                                "result": {"backend": env.backend.name, "training_ready": False}})
            watchdog.start(stale)
            while not expired.is_set():
                message = receive(self.request, min(deadline, server.end_time))
                fields(message, ("version", "session", "sequence", "nonce", "operation", "payload"))
                integer(message["version"], "version", VERSION, VERSION)
                integer(message["sequence"], "sequence", 1, 2**31 - 1)
                if (message["session"] != session or message["nonce"] != nonce or
                        message["sequence"] != seq + 1 or time.monotonic() > deadline or expired.is_set()):
                    raise ProtocolError("Expired, replayed, or out-of-order command")
                operation, payload = message["operation"], message["payload"]
                # Reset/physics may take longer than the command lease. No further
                # ticks are possible while the serialized request is in flight.
                if not watchdog.suspend() or expired.is_set():
                    raise ProtocolError("Command lease expired")
                if operation == "reset":
                    fields(payload, ("seed", "scenario", "max_steps"))
                    result = env.reset(**payload)
                elif operation == "step":
                    result = env.step(payload)
                elif operation == "close":
                    fields(payload, ())
                    env.abort()
                    result = {"closed": True}
                else:
                    raise ProtocolError("Unknown operation")
                seq += 1
                nonce = secrets.token_hex(16)
                deadline = time.monotonic() + server.lease_seconds
                send(self.request, {"version": VERSION, "ok": True, "session": session,
                                    "sequence": seq, "nonce": nonce, "lease_seconds": server.lease_seconds,
                                    "result": result})
                if operation == "close":
                    break
                watchdog.command_received()
        except (OSError, ConnectionError, TimeoutError, ProtocolError, TypeError, RecursionError):
            # Do not echo secrets, invalid payloads, or local exception details.
            try:
                send(self.request, {"version": VERSION, "ok": False, "error": "Session rejected; reconnect and reset"}, 0.2)
            except OSError:
                pass
        except Exception as exc:
            server.fatal_error = exc
            logging.exception("Environment failed; terminating session")
        finally:
            try:
                watchdog.stop()
                if authenticated:
                    try:
                        env.abort()
                    except Exception as exc:
                        if server.fatal_error is None:
                            server.fatal_error = exc
                        logging.exception("Emergency braking failed during session cleanup")
                    finally:
                        server.completed_sessions += 1
            finally:
                if server.tls_context is not None:
                    self.request.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--allow-peer")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--credentials", type=Path, default=Path(__file__).resolve().parents[2] / "credentials")
    parser.add_argument("--backend", choices=("rehearsal", "carla"), default="rehearsal")
    parser.add_argument("--map", default="Town02_Opt")
    parser.add_argument("--spawn-index", type=int, default=None, help="Optional fixed diagnostic spawn; otherwise seeded selection")
    parser.add_argument("--max-runtime-seconds", type=float, default=0)
    parser.add_argument("--single-session", action="store_true", help="Exit after the first authenticated client disconnects")
    args = parser.parse_args(argv)
    duration = finite(args.max_runtime_seconds, "runtime", 0, 86400)
    if args.spawn_index is not None:
        integer(args.spawn_index, "spawn_index", 0, 100000)
    tls = server_context(args.credentials) if args.tls else None
    token = load_token(args.credentials) if args.tls else os.environ.get("SIM_GATEWAY_TOKEN", "")
    backend = RehearsalBackend()
    if args.backend == "carla":
        from sim_host.carla_backend import CarlaBackend
        backend = CarlaBackend(args.map, spawn_index=args.spawn_index)
    env = EpisodeEnvironment(backend)
    try:
        with Gateway((args.bind, args.port), token, env, tls_context=tls, allowed_peer=args.allow_peer) as server:
            server.timeout = 0.2
            if duration:
                server.end_time = time.monotonic() + duration
            print(json.dumps({"ready": True, "address": args.bind, "port": server.server_address[1], "tls": bool(tls),
                              "backend": backend.name, "training": False}), flush=True)
            started = time.monotonic()
            while not duration or time.monotonic() - started < duration:
                server.handle_request()
                if server.fatal_error is not None:
                    raise RuntimeError("Simulator environment failed; inspect the host log") from server.fatal_error
                if args.single_session and server.completed_sessions:
                    break
    finally:
        env.close()


if __name__ == "__main__":
    main()
