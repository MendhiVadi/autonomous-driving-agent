"""Thermal and hardware-fault guard for the heavy CARLA + gesture stack.

This machine has an Intel Arc integrated GPU with no discrete card, so CARLA's
renderer, MediaPipe inference, and the CPU all contend for one thermally limited
package. On 2026-09-09 that combination produced a WHEA fatal hardware error and
a critical-thermal hibernate within an hour of each other. Windows exposes no
live temperature source here (both ``MSAcpi_ThermalZoneTemperature`` and the
``ThermalZoneInformation`` perf counters return nothing), so the next best
signal is the event log: refuse to relaunch the stack straight back into a
thermal wall we only just fell off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import subprocess
import sys

# Windows event-log signatures worth treating as "the hardware just complained".
WATCHED_EVENTS = (
    # Kernel-Power 88: "The system was hibernated due to a critical thermal event."
    {"kind": "thermal", "log": "System", "provider": "Microsoft-Windows-Kernel-Power", "id": 88},
    # WHEA-Logger 1: "A fatal hardware error has occurred."
    {"kind": "hardware", "log": "System", "provider": "Microsoft-Windows-WHEA-Logger", "id": 1},
    # Kernel-Power 41: rebooted without cleanly shutting down first.
    {"kind": "hardware", "log": "System", "provider": "Microsoft-Windows-Kernel-Power", "id": 41},
    # Application Hang 1002: a process stopped interacting with Windows and was killed.
    {"kind": "hang", "log": "Application", "provider": "Application Hang", "id": 1002},
)

# How long to stay off the accelerator after each class of fault.
DEFAULT_COOLDOWNS = {
    "thermal": 1800.0,   # 30 min - the package needs real time to shed heat
    "hardware": 3600.0,  # 60 min - a fatal hardware error deserves more caution
    "hang": 0.0,         # informational only; the supervisor handles restarts
}


@dataclass(frozen=True)
class HealthEvent:
    kind: str
    age_s: float
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "age_s": round(self.age_s, 1), "detail": self.detail}


@dataclass(frozen=True)
class HealthVerdict:
    safe: bool
    reason: str
    cooldown_remaining_s: float = 0.0
    events: tuple = field(default=())

    def as_dict(self) -> dict:
        return {
            "safe": self.safe,
            "reason": self.reason,
            "cooldown_remaining_s": round(self.cooldown_remaining_s, 1),
            "events": [event.as_dict() for event in self.events],
        }


def evaluate_health(events, cooldowns=None) -> HealthVerdict:
    """Decide whether the stack may start, from already-collected fault events.

    Pure logic so it can be tested without Windows in the loop. ``events`` is an
    iterable of :class:`HealthEvent`; the newest blocking fault wins.
    """
    limits = dict(DEFAULT_COOLDOWNS)
    if cooldowns:
        limits.update(cooldowns)

    collected = tuple(events)
    worst_remaining = 0.0
    worst_reason = ""
    for event in collected:
        limit = float(limits.get(event.kind, 0.0))
        if limit <= 0.0:
            continue
        remaining = limit - float(event.age_s)
        if remaining > worst_remaining:
            worst_remaining = remaining
            minutes_ago = event.age_s / 60.0
            worst_reason = (
                f"{event.kind} fault {minutes_ago:.0f} min ago"
                f"{': ' + event.detail if event.detail else ''}"
                f"; cooling down for another {remaining / 60.0:.0f} min"
            )

    if worst_remaining > 0.0:
        return HealthVerdict(False, worst_reason, worst_remaining, collected)
    return HealthVerdict(True, "no recent thermal or hardware faults", 0.0, collected)


_POWERSHELL_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$now = Get-Date
$specs = @(
{specs}
)
$out = @()
foreach ($s in $specs) {{
  $e = Get-WinEvent -FilterHashtable @{{ LogName = $s.Log; ProviderName = $s.Provider; Id = $s.Id; StartTime = $now.AddSeconds(-{window}) }} -MaxEvents 5 -ErrorAction SilentlyContinue
  foreach ($item in $e) {{
    $out += [pscustomobject]@{{
      kind   = $s.Kind
      age_s  = [math]::Round(($now - $item.TimeCreated).TotalSeconds, 1)
      detail = (($item.Message -split "`r?`n" | Select-Object -First 1) -replace '\s+', ' ').Trim()
    }}
  }}
}}
if ($out.Count -eq 0) {{ '[]' }} else {{ ConvertTo-Json -InputObject @($out) -Compress -Depth 3 }}
"""


def collect_events(window_s: float = 7200.0, timeout_s: float = 30.0):
    """Read recent fault events from the Windows event log.

    Returns an empty list on any failure - a guard that cannot read the log must
    not become a second way for the stack to refuse to start.
    """
    if not sys.platform.startswith("win"):
        return []

    specs = ",\n".join(
        "  [pscustomobject]@{{ Kind = '{kind}'; Log = '{log}'; Provider = '{provider}'; Id = {id} }}".format(**spec)
        for spec in WATCHED_EVENTS
    )
    script = _POWERSHELL_QUERY.format(specs=specs, window=int(window_s))
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    raw = (completed.stdout or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    events = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        try:
            events.append(HealthEvent(str(item.get("kind", "")), float(item.get("age_s", 0.0)),
                                      str(item.get("detail", ""))[:200]))
        except (TypeError, ValueError):
            continue
    return events


def check_system_health(window_s: float = 7200.0, cooldowns=None) -> HealthVerdict:
    """Collect fault events and turn them into a go / no-go verdict."""
    return evaluate_health(collect_events(window_s=window_s), cooldowns=cooldowns)


def main(argv=None) -> int:
    """CLI preflight: exit 0 when it is safe to launch, 1 when cooling down."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-hours", type=float, default=2.0,
                        help="How far back to look for thermal/hardware faults")
    parser.add_argument("--thermal-cooldown-min", type=float, default=30.0)
    parser.add_argument("--hardware-cooldown-min", type=float, default=60.0)
    parser.add_argument("--json", action="store_true", help="Emit the verdict as JSON")
    parser.add_argument("--warn-only", action="store_true",
                        help="Always exit 0; report the verdict without blocking")
    args = parser.parse_args(argv)

    verdict = check_system_health(
        window_s=args.window_hours * 3600.0,
        cooldowns={"thermal": args.thermal_cooldown_min * 60.0,
                   "hardware": args.hardware_cooldown_min * 60.0},
    )
    if args.json:
        print(json.dumps(verdict.as_dict()), flush=True)
    elif verdict.safe:
        print(f"HEALTH OK: {verdict.reason}", flush=True)
    else:
        print(f"HEALTH BLOCK: {verdict.reason}", flush=True)
    return 0 if (verdict.safe or args.warn_only) else 1


if __name__ == "__main__":
    raise SystemExit(main())
