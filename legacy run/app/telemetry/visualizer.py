"""Read-only, loopback visualization of the actual policy forward pass."""
import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class NeuralVisualizer:
    def __init__(self, model, path, open_browser=True, save_session=True):
        self.lock = threading.Lock()
        self.sequence = 0
        self.latest = None
        self.runtime = {}
        self.browser_seen = False
        self.model = {"sizes": model.sizes, "weights": model.weights,
                      "name": Path(path).name}
        self.model_json = json.dumps(self.model, allow_nan=False).encode()
        self.page = Path(__file__).with_name("neural_visualizer.html").read_bytes()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                expected_host = f"127.0.0.1:{self.server.server_port}"
                if self.headers.get("Host") != expected_host:
                    self.send_error(421, "Unexpected host")
                    return
                if self.headers.get("Origin") not in (None, "http://" + expected_host):
                    self.send_error(403, "Cross-origin requests are forbidden")
                    return
                if self.path == "/":
                    body, kind = owner.page, "text/html; charset=utf-8"
                elif self.path == "/state":
                    with owner.lock:
                        snapshot = owner.latest
                        runtime = dict(owner.runtime)
                    if not owner.browser_seen:
                        owner.browser_seen = True
                        print('[neural visual] browser connected', flush=True)
                    live = json.dumps({"sample": snapshot, "runtime": runtime,
                                       "now": time.time()}, allow_nan=False).encode()
                    body = b'{"model":' + owner.model_json + b"," + live[1:]
                    kind = "application/json"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
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
        root = Path(__file__).resolve().parents[2]
        try:
            if not save_session:
                if open_browser:
                    self.open_browser()
                return
            (root / 'logs').mkdir(exist_ok=True)
            (root / 'logs' / 'neural-visual.json').write_text(
                json.dumps({'url': self.url, 'pid': os.getpid()}), encoding='utf-8')
            (root / 'run').mkdir(exist_ok=True)
            (root / 'run' / 'Open neural activity.url').write_text(
                '[InternetShortcut]\nURL=' + self.url + '\n', encoding='utf-8')
        except OSError as exc:
            print(f'[neural visual] could not save browser shortcut: {exc}', flush=True)
        if open_browser:
            self.open_browser()

    def open_browser(self):
        def launch():
            try:
                if os.name == 'nt':
                    os.startfile(self.url)
                elif not webbrowser.open(self.url, new=2):
                    raise RuntimeError('No browser accepted the URL')
                print('[neural visual] browser launch requested; F8 reopens ' + self.url, flush=True)
            except Exception as exc:
                print(f'[neural visual] browser could not open: {exc}. Open {self.url}', flush=True)
        threading.Thread(target=launch, daemon=True).start()

    def publish_runtime(self, values):
        with self.lock:
            self.runtime.update(values)

    def publish(self, layers):
        # One immutable snapshot; no disk/network I/O in the driving loop.
        with self.lock:
            self.sequence += 1
            self.latest = {"sequence": self.sequence, "time": time.time(),
                           "layers": [list(layer) for layer in layers]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
