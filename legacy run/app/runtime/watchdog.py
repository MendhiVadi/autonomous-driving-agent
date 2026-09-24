"""Heartbeat and independent stale-command protection."""
import math
import logging
import threading
import time


class LinkWatchdog:
    def __init__(self, timeout_s=1.0):
        self.timeout_s = float(timeout_s)
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("Link watchdog timeout must be finite and positive")
        self.last_heartbeat = None
        self.last_command = None

    def heartbeat(self):
        self.last_heartbeat = time.monotonic()

    def command_received(self):
        self.last_command = time.monotonic()

    def healthy(self):
        now = time.monotonic()
        return (self.last_heartbeat is not None and self.last_command is not None
                and 0 <= now - self.last_heartbeat <= self.timeout_s
                and 0 <= now - self.last_command <= self.timeout_s)

    def status(self):
        now = time.monotonic()
        return {"healthy": self.healthy(),
                "heartbeat_age_s": None if self.last_heartbeat is None else now - self.last_heartbeat,
                "command_age_s": None if self.last_command is None else now - self.last_command}


class CommandWatchdog:
    """Invoke a fail-safe callback if command publication stops."""

    def __init__(self, timeout_s=0.5, poll_interval_s=0.05):
        self.timeout_s = float(timeout_s)
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("Command watchdog timeout must be positive")
        if not math.isfinite(float(poll_interval_s)) or float(poll_interval_s) <= 0:
            raise ValueError("Command watchdog poll interval must be positive")
        self.poll_interval_s = min(float(poll_interval_s), self.timeout_s / 2.0)
        self.last_command = time.monotonic()
        self._armed = False
        self._triggered = False
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._on_stale = None

    def command_received(self):
        with self._lock:
            self.last_command = time.monotonic()
            self._armed = True
            self._triggered = False

    def status(self):
        with self._lock:
            age = time.monotonic() - self.last_command if self._armed else 0.0
            return {"healthy": not self._armed or age <= self.timeout_s,
                    "command_age_s": age, "triggered": self._triggered}

    def start(self, on_stale):
        if not callable(on_stale):
            raise ValueError("Emergency brake callback must be callable")
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("CommandWatchdog is already running or still stopping")
            self._on_stale = on_stale
            self._stop.clear()
            with self._lock:
                # Cover a stall before the first command, including after restart.
                self.last_command = time.monotonic()
                self._armed = True
                self._triggered = False
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="command-watchdog")
            self._thread.start()

    def _run(self):
        while not self._stop.wait(self.poll_interval_s):
            should_trigger = False
            with self._lock:
                age = time.monotonic() - self.last_command
                if self._armed and age > self.timeout_s and not self._triggered:
                    self._triggered = True
                    should_trigger = True
            if should_trigger:
                try:
                    self._on_stale()
                except Exception:
                    logging.exception("Emergency brake callback failed; retrying while stale")
                    with self._lock:
                        self._triggered = False

    def stop(self):
        with self._lifecycle_lock:
            self._stop.set()
            worker = self._thread
        if worker is None or worker is threading.current_thread():
            return
        worker.join(timeout=max(1.0, self.timeout_s * 2.0))
        with self._lifecycle_lock:
            # A blocked callback may outlive join's timeout. Keep ownership so
            # start() cannot clear its stop event and create a second worker.
            if self._thread is worker and not worker.is_alive():
                self._thread = None
