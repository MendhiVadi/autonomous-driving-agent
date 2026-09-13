"""Generate a responsive, dependency-free evaluation dashboard from episode logs."""
import argparse
import html
import json
from pathlib import Path


def summarize(path):
    path = Path(path)
    records = collisions = lane_departures = safety_events = 0
    distance_m = elapsed_s = speed_total = max_speed_kmh = 0.0
    min_obstacle_m = None

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            telemetry = row.get("telemetry") or {}
            records += 1
            collisions += bool(telemetry.get("collision", False))
            lane_departures += bool(telemetry.get("lane_departure", False))
            safety_events += bool(row.get("event"))
            distance_m = max(distance_m, float(telemetry.get("distance_m", 0.0)))
            elapsed_s = max(elapsed_s, float(telemetry.get("elapsed_s", 0.0)))
            speed = float(telemetry.get("speed_kmh", 0.0))
            speed_total += speed
            max_speed_kmh = max(max_speed_kmh, speed)
            obstacle = telemetry.get("obstacle_distance_m")
            if obstacle is not None:
                obstacle = float(obstacle)
                min_obstacle_m = obstacle if min_obstacle_m is None else min(min_obstacle_m, obstacle)

    return {
        "episode": str(path), "records": records, "collisions": collisions,
        "lane_departures": lane_departures, "safety_events": safety_events,
        "distance_m": distance_m, "elapsed_s": elapsed_s,
        "average_speed_kmh": speed_total / records if records else 0.0,
        "max_speed_kmh": max_speed_kmh, "min_obstacle_m": min_obstacle_m,
        "success": records > 0 and collisions == 0 and lane_departures == 0,
    }


def _metric(label, value):
    return f"<div class='metric'><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"


def write_dashboard(inputs, output):
    summaries = [summarize(path) for path in inputs]
    passed = sum(item["success"] for item in summaries)
    rows = []
    for item in summaries:
        status = "PASS" if item["success"] else "REVIEW"
        status_class = "pass" if item["success"] else "review"
        obstacle = "-" if item["min_obstacle_m"] is None else f'{item["min_obstacle_m"]:.1f} m'
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(Path(item['episode']).stem)}</strong><small>{html.escape(item['episode'])}</small></td>"
            f"<td><span class='badge {status_class}'>{status}</span></td>"
            f"<td>{item['distance_m']:.1f} m</td><td>{item['elapsed_s']:.1f} s</td>"
            f"<td>{item['average_speed_kmh']:.1f} / {item['max_speed_kmh']:.1f}</td>"
            f"<td>{obstacle}</td><td>{item['collisions']}</td>"
            f"<td>{item['lane_departures']}</td><td>{item['safety_events']}</td></tr>"
        )

    metrics = "".join((
        _metric("Episodes passed", f"{passed} / {len(summaries)}"),
        _metric("Total distance", f"{sum(item['distance_m'] for item in summaries):.1f} m"),
        _metric("Collisions", sum(item["collisions"] for item in summaries)),
        _metric("Records analyzed", sum(item["records"] for item in summaries)),
    ))
    table_body = "".join(rows) or "<tr><td colspan='9'>No episode records found.</td></tr>"
    document = f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>CARLA driving evaluation</title>
<style>
:root{{--bg:#071018;--panel:#101d29;--line:#263848;--text:#eef6fb;--muted:#9db0bf;--green:#4bd49b;--amber:#ffc766}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#071018,#0c1721);color:var(--text);font:15px system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:40px 24px}}h1{{margin:0;font-size:clamp(28px,5vw,48px)}}.intro{{color:var(--muted);margin:8px 0 28px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-bottom:24px}}.metric{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px}}
.metric span,small{{display:block;color:var(--muted);font-size:12px}}.metric strong{{display:block;font-size:25px;margin-top:7px}}
.table-wrap{{overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}}table{{border-collapse:collapse;width:100%;min-width:1000px}}
th,td{{padding:14px 16px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}}th{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}}tbody tr:hover{{background:#142533}}
.badge{{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800}}.pass{{color:var(--green);background:#12372d}}.review{{color:var(--amber);background:#3b2e15}}
footer{{color:var(--muted);font-size:12px;margin-top:16px}}@media(max-width:720px){{main{{padding:24px 14px}}.metrics{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main><h1>Driving evaluation</h1>
<p class='intro'>Safety and feasibility summary from replayable CARLA episode logs. No training is performed.</p>
<section class='metrics'>{metrics}</section><div class='table-wrap'><table><thead><tr><th>Episode</th><th>Status</th><th>Distance</th><th>Time</th><th>Avg / max km/h</th><th>Closest object</th><th>Collisions</th><th>Lane exits</th><th>Safety events</th></tr></thead><tbody>{table_body}</tbody></table></div>
<footer>PASS requires at least one record, zero collisions, and zero lane departures.</footer></main></body></html>"""
    Path(output).write_text(document, encoding="utf-8")
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", default="evaluation_dashboard.html")
    args = parser.parse_args()
    print(json.dumps(write_dashboard(args.inputs, args.output), indent=2))
