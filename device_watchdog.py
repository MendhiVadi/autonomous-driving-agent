"""Heartbeat and independent stale-command protection."""
import threading
import time


class LinkWatchdog:
    def __init__(self, timeout_s=1.0):
        self.timeout_s = timeout_s
        self.last_heartbeat = 0.0
        self.last_command = 0.0

    def heartbeat(self):
        self.last_heartbeat = time.monotonic()

    def command_received(self):
        self.last_command = time.monotonic()

    def healthy(self):
        now = time.monotonic()
        return (now - self.last_heartbeat <= self.timeout_s and
                now - self.last_command <= self.timeout_s)

    def status(self):
        now = time.monotonic()
        return {"healthy": self.healthy(),
                "heartbeat_age_s": now - self.last_heartbeat,
                "command_age_s": now - self.last_command}


class CommandWatchdog:
    """Invoke a fail-safe callback if command publication stops."""

    def __init__(self, timeout_s=0.5, poll_interval_s=0.05):
        self.timeout_s = float(timeout_s)
        if self.timeout_s <= 0:
            raise ValueError("Command watchdog timeout must be positive")
        if float(poll_interval_s) <= 0:
            raise ValueError("Command watchdog poll interval must be positive")
        self.poll_interval_s = min(float(poll_interval_s), self.timeout_s / 2.0)
        self.last_command = time.monotonic()
        self._armed = False
        self._triggered = False
        self._lock = threading.Lock()
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
        if self._thread is not None:
            raise RuntimeError("CommandWatchdog is already running")
        self._on_stale = on_stale
        self._stop.clear()
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
                    # A destroyed/disconnected CARLA actor is already safe; the
                    # driving loop owns reporting and cleanup.
                    pass

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.timeout_s * 2.0))
            self._thread = None
