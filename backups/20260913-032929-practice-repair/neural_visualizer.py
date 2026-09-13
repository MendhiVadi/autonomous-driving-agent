"""Read-only, loopback visualization of the actual policy forward pass."""
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NeuralVisualizer:
    def __init__(self, model, path, open_browser=True):
        self.lock = threading.Lock()
        self.sequence = 0
        self.latest = None
        self.model = {"sizes": model.sizes, "weights": model.weights,
                      "name": Path(path).name}
        self.page = Path(__file__).with_name("neural_visualizer.html").read_bytes()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    body, kind = owner.page, "text/html; charset=utf-8"
                elif self.path == "/state":
                    with owner.lock:
                        snapshot = owner.latest
                    body = json.dumps({"model": owner.model, "sample": snapshot,
                                       "now": time.time()}, allow_nan=False).encode()
                    kind = "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        print(f"[neural visual] {self.url}", flush=True)
        if open_browser:
            threading.Thread(target=webbrowser.open, args=(self.url,), daemon=True).start()

    def publish(self, layers):
        # One immutable snapshot; no disk/network I/O in the driving loop.
        with self.lock:
            self.sequence += 1
            self.latest = {"sequence": self.sequence, "time": time.time(),
                           "layers": [list(layer) for layer in layers]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
