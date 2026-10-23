"""Keep the CARLA + neural-driver stack alive, logged, and thermally sane.

Before this existed the launcher fired processes into detached Scheduled Tasks
and forgot about them. Nothing captured their output and nothing noticed when
one died, so when a component wedged on 2026-09-09 the whole stack simply
stopped and left no evidence behind.

This supervisor is the single detached process instead. It starts the two
components in dependency order, tees every line they write to a per-component
log, probes them for liveness rather than trusting that a live PID means a
working process, and restarts what dies with exponential backoff. It also
refuses to restart into a thermal wall: this machine has no discrete GPU and
already hibernated itself once under this exact load.

No local gesture/webcam engine is included in this stack. A separately operated
computer may provide bounded final intent-bias JSON through the optional UDP
receiver, but this supervisor only ever runs CARLA and the car that drives
itself in it.
"""

from __future__ import annotations

from runtime.paths import carla_root as get_carla_root

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

from runtime.health import check_system_health
from simulation.environment import input_heartbeat_ready


DEFAULT_CARLA_ROOT = Path(str(get_carla_root()))


# --------------------------------------------------------------------------
# Restart policy (pure logic, unit tested)
# --------------------------------------------------------------------------
@dataclass
class RestartPolicy:
    """Exponential backoff with a give-up rule for a component that keeps dying.

    A component that crashes instantly and forever is a bug, not a blip;
    hammering it wastes the thermal budget that caused the problem in the first
    place. ``healthy_after_s`` of uptime clears the record so an occasional
    restart weeks apart never accumulates toward the limit.
    """

    base_delay_s: float = 5.0
    max_delay_s: float = 120.0
    max_failures: int = 8
    healthy_after_s: float = 300.0
    failures: int = 0

    def record_start(self) -> None:
        self.failures += 1

    def record_exit(self, uptime_s: float) -> None:
        """A run that lasted long enough counts as recovery, not a failure."""
        if uptime_s >= self.healthy_after_s:
            self.failures = 0

    def delay_s(self) -> float:
        if self.failures <= 1:
            return 0.0
        return min(self.base_delay_s * (2 ** (self.failures - 2)), self.max_delay_s)

    def exhausted(self) -> bool:
        return self.failures > self.max_failures


# --------------------------------------------------------------------------
# Liveness probes
# --------------------------------------------------------------------------
def tcp_probe(host: str, port: int, timeout_s: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def carla_rpc_probe(host: str, port: int, timeout_s: float = 3.0) -> bool:
    """A crashed renderer can leave its TCP listener open indefinitely."""
    try:
        import carla
        client = carla.Client(host, port)
        client.set_timeout(timeout_s)
        client.get_server_version()
        world = client.get_world()
        # Observe without ticking: a dead synchronous tick owner must also fail.
        world.wait_for_tick(seconds=timeout_s)
        return True
    except (RuntimeError, OSError, ImportError):
        return False


# --------------------------------------------------------------------------
# Process-tree handling
#
# Two things here spawn the real worker as a *child* of the process we launch:
#   * CarlaUE4.exe is a shim that starts CarlaUE4-Win64-Shipping.exe;
#   * these venvs use a redirector python.exe that re-executes the base
#     interpreter (C:\...\Python311\python.exe) as a child.
# So Popen.terminate() kills a stub and orphans the process doing the work.
# That is how a stale CARLA server was left holding port 2000 while a second
# one started - two renderers on one iGPU, which is precisely the thermal
# overload this whole change set exists to prevent.
# --------------------------------------------------------------------------
ORPHAN_PATTERNS = ("CarlaUE4", "neural_drive_agent.py")


def _powershell(script: str, timeout_s: float = 30.0) -> str:
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout or ""


def terminate_tree(pid: int, timeout_s: float = 10.0) -> bool:
    """Stop an owned process tree; return whether the system call succeeded."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or pid == os.getpid():
        return False
    if not sys.platform.startswith("win"):
        return False
    try:
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                capture_output=True, timeout=timeout_s)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def find_orphans(patterns=ORPHAN_PATTERNS):
    """PIDs of stack processes already running before we start our own.

    The image name is checked as well as the command line. Matching on command
    line alone would also hit a shell or editor that merely mentions one of
    these script names, and this list feeds a forced tree kill.
    """
    if not sys.platform.startswith("win"):
        return []
    escaped = "|".join(pattern.replace(".", r"\.") for pattern in patterns)
    script = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -match '^CarlaUE4') -or "
        "($_.Name -match '^python' -and $_.CommandLine -match '" + escaped + "') } | "
        "ForEach-Object { $_.ProcessId }"
    )
    pids = []
    for line in _powershell(script).splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


@dataclass
class Component:
    name: str
    argv: list
    cwd: Path
    log_path: Path
    probe: object = None            # callable() -> bool, or None to skip probing
    ready_grace_s: float = 45.0     # probe failures are tolerated this long after a start
    probe_failures_allowed: int = 3
    depends_on: tuple = ()
    policy: RestartPolicy = field(default_factory=RestartPolicy)

    process: object = None
    started_at: float = 0.0
    next_start_at: float = 0.0
    probe_failures: int = 0
    probe_ok: bool = False
    log_handle: object = None
    gave_up: bool = False

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def is_ready(self) -> bool:
        """Running *and* actually answering.

        Readiness must never be inferred from the grace window: doing that let
        the launcher print READY, and let the neural driver start, while CARLA
        was still minutes away from accepting RPC connections. The grace window
        only decides when a failing probe starts counting against the process,
        not whether the component is usable yet.
        """
        if not self.is_running():
            return False
        if self.probe is None:
            return True
        return self.probe_ok


class Supervisor:
    def __init__(self, components, log_dir: Path, poll_s: float = 3.0,
                 thermal_guard: bool = True, status_path: Path = None,
                 sweep_on_start: bool = False, max_log_mb: float = 50.0,
                 log_generations: int = 3) -> None:
        self.components = {component.name: component for component in components}
        self.log_dir = log_dir
        self.poll_s = poll_s
        self.thermal_guard = thermal_guard
        self.status_path = status_path
        self.sweep_on_start = sweep_on_start
        self.max_log_bytes = int(max_log_mb * 1024 * 1024)
        self.log_generations = max(1, int(log_generations))
        self._stop = threading.Event()
        self._thermal_block_until = 0.0
        self._thermal_reason = ""

    # -- logging ----------------------------------------------------------
    def log(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [supervisor] {message}"
        print(line, flush=True)
        try:
            with (self.log_dir / "supervisor.log").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    # -- thermal ----------------------------------------------------------
    def thermal_ok(self) -> bool:
        """Consult the event log, but no more than once a minute."""
        if not self.thermal_guard:
            return True
        now = time.monotonic()
        if now < self._thermal_block_until:
            return False
        verdict = check_system_health()
        if verdict.safe:
            self._thermal_reason = ""
            return True
        self._thermal_reason = verdict.reason
        # Re-check periodically rather than sleeping out the whole cooldown, so
        # a manual stop still gets a response promptly.
        self._thermal_block_until = now + min(60.0, max(5.0, verdict.cooldown_remaining_s))
        self.log(f"holding launches: {verdict.reason}")
        return False

    # -- process lifecycle -------------------------------------------------
    def rotate_log(self, path: Path) -> None:
        """Roll a component log that has grown past the cap, keeping a few back.

        The neural driver emits a telemetry line roughly twice a second, so a
        stack left supervised for days would otherwise fill the disk - which
        would take the whole thing down again for a new reason.
        """
        limit = self.max_log_bytes
        if limit <= 0:
            return
        try:
            if not path.exists() or path.stat().st_size < limit:
                return
            for index in range(self.log_generations - 1, 0, -1):
                older = path.with_suffix(path.suffix + f".{index}")
                newer = path.with_suffix(path.suffix + f".{index + 1}")
                if older.exists():
                    older.replace(newer)
            path.replace(path.with_suffix(path.suffix + ".1"))
            self.log(f"rotated {path.name} at {limit // (1024 * 1024)}MB")
        except OSError as exc:
            self.log(f"could not rotate {path.name}: {exc}")

    def start(self, component: Component) -> None:
        component.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.rotate_log(component.log_path)
        component.log_handle = component.log_path.open("a", encoding="utf-8", errors="replace")
        component.log_handle.write(
            f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} starting {component.name} =====\n")
        component.log_handle.flush()
        try:
            component.process = subprocess.Popen(
                component.argv,
                cwd=str(component.cwd),
                stdout=component.log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                # A new process group lets us signal the child without the
                # supervisor's own console handler taking it down first.
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            component.log_handle.close()
            component.log_handle = None
            component.policy.record_start()
            component.next_start_at = time.monotonic() + max(component.policy.delay_s(), 5.0)
            self.log(f"{component.name}: failed to start: {exc}")
            return
        component.started_at = time.monotonic()
        component.probe_failures = 0
        component.probe_ok = False
        component.policy.record_start()
        self.log(f"{component.name}: started pid {component.process.pid} "
                 f"(attempt {component.policy.failures}, log {component.log_path.name})")

    def stop(self, component: Component, reason: str) -> None:
        if component.process is None:
            return
        if component.process.poll() is None:
            self.log(f"{component.name}: stopping ({reason})")
            # Tree kill, not terminate: the direct child is often only a shim.
            terminate_tree(component.process.pid)
            try:
                component.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.log(f"{component.name}: did not exit after a tree kill; killing the handle")
                try:
                    component.process.kill()
                    component.process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    self.log(f"{component.name}: unkillable, abandoning the handle")
            except OSError as exc:
                self.log(f"{component.name}: wait failed: {exc}")
        if component.log_handle is not None:
            try:
                component.log_handle.close()
            except OSError:
                pass
            component.log_handle = None
        component.process = None

    def dependencies_ready(self, component: Component) -> bool:
        return all(self.components[name].is_ready() for name in component.depends_on
                   if name in self.components)

    # -- main loop ---------------------------------------------------------
    def tick(self) -> None:
        now = time.monotonic()
        for component in self.components.values():
            if component.gave_up:
                continue

            if component.is_running():
                if component.probe is not None:
                    # Probe from the first tick so readiness is real, but only
                    # hold failures against the process once it has had its
                    # grace window to finish starting.
                    if component.probe():
                        if component.probe_failures or not component.probe_ok:
                            self.log(f"{component.name}: probe healthy")
                        component.probe_failures = 0
                        component.probe_ok = True
                    elif now - component.started_at >= component.ready_grace_s:
                        component.probe_ok = False
                        component.probe_failures += 1
                        self.log(f"{component.name}: probe failed "
                                 f"({component.probe_failures}/{component.probe_failures_allowed + 1})")
                        if component.probe_failures > component.probe_failures_allowed:
                            # Alive but not answering - the exact shape of the
                            # 16:30 hang. Recycle it rather than wait for Windows.
                            uptime = now - component.started_at
                            self.stop(component, "unresponsive to liveness probe")
                            component.policy.record_exit(uptime)
                            component.next_start_at = now + component.policy.delay_s()
                continue

            # Not running: either never started, or it exited.
            if component.process is not None:
                code = component.process.poll()
                uptime = now - component.started_at
                self.stop(component, f"exited with code {code}")
                component.policy.record_exit(uptime)
                self.log(f"{component.name}: exited code {code} after {uptime:.0f}s")
                component.next_start_at = now + component.policy.delay_s()

            if component.policy.exhausted():
                component.gave_up = True
                self.log(f"{component.name}: giving up after {component.policy.failures} "
                         f"failed starts - see {component.log_path}")
                continue
            if now < component.next_start_at:
                continue
            if not self.dependencies_ready(component):
                continue
            if not self.thermal_ok():
                continue
            self.start(component)

    def write_status(self) -> None:
        if self.status_path is None:
            return
        status = {
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "supervisor_pid": os.getpid(),
            "thermal_hold": self._thermal_reason,
            "components": {
                name: {
                    "running": component.is_running(),
                    "ready": component.is_ready(),
                    "pid": component.process.pid if component.is_running() else None,
                    "uptime_s": round(time.monotonic() - component.started_at, 1)
                                if component.is_running() else 0.0,
                    "restarts": max(0, component.policy.failures - 1),
                    "gave_up": component.gave_up,
                    "log": str(component.log_path),
                }
                for name, component in self.components.items()
            },
        }
        try:
            self.status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        except OSError:
            pass

    def sweep_orphans(self) -> None:
        """Refuse existing sessions instead of terminating processes we do not own."""
        mine = {os.getpid()}
        orphans = [pid for pid in find_orphans() if pid not in mine]
        if not orphans:
            return
        raise RuntimeError("Existing CARLA/driver processes detected; close their owning session first. "
                           "Refusing to terminate unowned processes: " + str(orphans))

    def run(self) -> int:
        self.log(f"supervising {', '.join(self.components)} (pid {os.getpid()})")
        if self.sweep_on_start:
            self.sweep_orphans()
        try:
            while not self._stop.is_set():
                if (self.log_dir / "stop.request").exists():
                    (self.log_dir / "stop.request").unlink()
                    self.request_stop()
                    break
                self.tick()
                self.write_status()
                self._stop.wait(self.poll_s)
        finally:
            for component in self.components.values():
                self.stop(component, "supervisor shutting down")
            self.write_status()
            self.log("supervisor stopped")
        return 0

    def request_stop(self, *_args) -> None:
        self.log("stop requested")
        self._stop.set()


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------
def build_components(args) -> list:
    app_root = Path(__file__).resolve().parent.parent
    carla_root = Path(args.carla_root)
    log_dir = Path(args.log_dir)
    carla_python = carla_root / "carla_env" / "Scripts" / "python.exe"

    carla = Component(
        name="carla",
        argv=[str(carla_root / "CarlaUE4.exe"),
              "-RenderOffScreen", f"-{args.render_api}", "-quality-level=Low", "-nosound",
              "-NoVSync", "-NoBloom", "-NoMotionBlur",
              f"-ResX={args.res_x}", f"-ResY={args.res_y}", f"-fps={args.carla_fps}",
              f"-carla-rpc-port={args.rpc_port}"],
        cwd=carla_root,
        log_path=log_dir / "carla.log",
        probe=lambda: carla_rpc_probe("127.0.0.1", args.rpc_port),
        ready_grace_s=120.0,  # the software-rendered server is slow to come up
    )

    neural = Component(
        name="neural",
        argv=[str(carla_python), str(app_root / "app" / "neural_drive_agent.py"),
              "--carla-root", str(carla_root),
              "--policy", str(app_root / "nn_policy_colab.json"),
              "--port", str(args.rpc_port),
              "--map", "Town02_Opt",
              "--heartbeat-path", str(log_dir / "neural_heartbeat.json"),
              "--tick-timeout", str(args.tick_timeout),
              "--max-ticks", str(args.max_ticks),
              "--gesture-port", "0"],  # external intent input is opt-in; keep it off by default
        cwd=app_root,
        log_path=log_dir / "neural.log",
        probe=None,
        depends_on=("carla",),
        ready_grace_s=60.0,
    )
    neural.probe = lambda: input_heartbeat_ready(
        log_dir / "neural_heartbeat.json", neural.started_at)
    return [carla, neural]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--carla-root", default=str(DEFAULT_CARLA_ROOT))
    parser.add_argument("--log-dir", default=str(Path(__file__).resolve().parent.parent / "logs"))
    parser.add_argument("--rpc-port", type=int, default=2000)
    # Thermal budget: this is an Intel Arc 140V iGPU with no discrete card.
    # These defaults are lower than the pre-incident ones on purpose.
    parser.add_argument("--res-x", type=int, default=320)
    parser.add_argument("--res-y", type=int, default=180)
    parser.add_argument("--carla-fps", type=int, default=20)
    # Bare names, not "-opengl": argparse reads a value beginning with a dash as
    # the next option, so "--render-api -opengl" fails outright. The dash is
    # added back when the CARLA command line is built.
    parser.add_argument("--render-api", default="dx11",
                        choices=["dx12", "dx11", "opengl", "vulkan"],
                        help="Renderer; opengl usually runs cooler on an Arc iGPU")
    parser.add_argument("--tick-timeout", type=float, default=2.0)
    parser.add_argument("--max-ticks", type=int, default=2147483647)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--no-thermal-guard", action="store_true",
                        help="Start even if a thermal or hardware fault is still cooling down")
    parser.add_argument("--no-orphan-sweep", action="store_true",
                        help="Deprecated compatibility option; existing-session checks always run")
    parser.add_argument("--max-log-mb", type=float, default=50.0,
                        help="Roll a component log once it passes this size (0 disables)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    supervisor = Supervisor(
        build_components(args),
        log_dir=log_dir,
        poll_s=args.poll_interval,
        thermal_guard=not args.no_thermal_guard,
        status_path=log_dir / "stack_status.json",
        sweep_on_start=True,
        max_log_mb=args.max_log_mb,
    )
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, supervisor.request_stop)
            except (ValueError, OSError):
                pass
    from runtime.lease import runtime_lease
    with runtime_lease():
        return supervisor.run()


def _log_crash(exc: BaseException, argv) -> None:
    """Record a startup failure the detached task would otherwise swallow."""
    import traceback

    try:
        args = parse_args(argv)
        log_dir = Path(args.log_dir)
    except SystemExit:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "supervisor.log").open("a", encoding="utf-8") as handle:
            handle.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} [supervisor] CRASHED\n")
            handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except OSError:
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as error:  # detached: stderr goes nowhere, so persist it
        _log_crash(error, sys.argv[1:])
        raise
