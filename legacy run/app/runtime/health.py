"""Windows event-log preflight for thermal and hardware faults.

Applies cooldowns after recent critical thermal events and hardware errors.
Event logs provide a fallback when live temperature telemetry is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import subprocess
import sys

# Windows event IDs used by the startup health check.
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

# Cooldown durations in seconds.
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
$ErrorActionPreference = 'Stop'
$now = Get-Date
$specs = @(
{specs}
)
$out = @()
foreach ($s in $specs) {{
  $e = @()
  try {{
    $e = @(Get-WinEvent -FilterHashtable @{{ LogName = $s.Log; ProviderName = $s.Provider; Id = $s.Id; StartTime = $now.AddSeconds(-{window}) }} -MaxEvents 5 -ErrorAction Stop)
  }} catch {{
    if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') {{ throw }}
  }}
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

    An unavailable or malformed event log is a blocked preflight, not an all-clear.
    """
    if not sys.platform.startswith("win"):
        raise RuntimeError("Windows hardware event log is unavailable")

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
        raise RuntimeError("Windows hardware event log is unavailable")

    if completed.returncode != 0:
        raise RuntimeError("Windows hardware event log query failed")
    raw = (completed.stdout or "").strip()
    if not raw:
        raise RuntimeError("Windows hardware event log is unavailable")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("Windows hardware event log is unavailable")
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("Windows hardware event log is unavailable")

    events = []
    for item in parsed:
        if not isinstance(item, dict):
            raise RuntimeError("Malformed hardware event log record")
        try:
            age = float(item["age_s"])
            if not math.isfinite(age) or age < 0 or item.get("kind") not in DEFAULT_COOLDOWNS:
                raise ValueError("Invalid hardware event age or kind")
            events.append(HealthEvent(item["kind"], age, str(item.get("detail", ""))[:200]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Malformed hardware event log record") from exc
    return events


def check_system_health(window_s: float = 7200.0, cooldowns=None) -> HealthVerdict:
    """Collect fault events and turn them into a go / no-go verdict."""
    limits = dict(DEFAULT_COOLDOWNS)
    if cooldowns:
        limits.update(cooldowns)
    try:
        if not math.isfinite(window_s) or window_s <= 0:
            raise ValueError("Health window must be finite and positive")
        if any(not math.isfinite(v) or v < 0 for v in limits.values()):
            raise ValueError("Health cooldowns must be finite and non-negative")
        return evaluate_health(collect_events(window_s=max(window_s, max(limits.values()))), cooldowns=limits)
    except (RuntimeError, ValueError, TypeError) as exc:
        return HealthVerdict(False, f"Cannot verify hardware health: {exc}", 60.0)


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
