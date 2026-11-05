"""Bounded CARLA render/camera diagnostic. Owns and always kills its own server.

Usage: python render_probe.py --name A --cams front:320x180@10,left:240x135@2 \
         --res 960x540 --quality Epic --duration 40 [--sync] [--noborders]
"""
import argparse, json, os, subprocess, sys, threading, time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from runtime.paths import carla_root as _carla_root  # noqa: E402

CARLA_ROOT = _carla_root()  # CARLA_ROOT variable or config/runtime.json
sys.path.insert(0, str(CARLA_ROOT / "PythonAPI/carla"))
import carla  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--cams", default="front:320x180@10,left:240x135@2,right:240x135@2")
ap.add_argument("--res", default="960x540")
ap.add_argument("--quality", default="Epic")
ap.add_argument("--fps", type=int, default=15)
ap.add_argument("--duration", type=float, default=40.0)
ap.add_argument("--sync", action="store_true", help="client-driven synchronous ticks at 20 Hz")
ap.add_argument("--fixed-delta", type=float, default=0.05, help="0 = variable time step")
ap.add_argument("--tick-hz", type=float, default=15.0)
ap.add_argument("--api", default="dx11")
ap.add_argument("--nopost", action="store_true", help="camera enable_postprocess_effects=False")
ap.add_argument("--extra", default="", help="extra ExecCmds, comma separated")
ap.add_argument("--offscreen", type=int, default=1)
ap.add_argument("--map", default="Town02_Opt")
ap.add_argument("--layers", default="All")
ap.add_argument("--out", default=".")
args = ap.parse_args()

out = (Path(args.out) / args.name).resolve()
out.mkdir(parents=True, exist_ok=True)
resx, resy = args.res.split("x")
abslog = out / "ue.log"
cmd = [str(CARLA_ROOT / "CarlaUE4.exe")]
flags = []
if args.offscreen:
    flags.append("-RenderOffScreen")
else:
    flags += ["-windowed"]
flags += [f"-{args.api}", f"-quality-level={args.quality}", "-NoVSync", f"-ResX={resx}", f"-ResY={resy}",
          f"-fps={args.fps}", "-unattended", "-carla-rpc-port=2000", f'-ExecCmds="t.MaxFPS {args.fps}' + (("," + args.extra) if args.extra else "") + '"',
          f"-ABSLOG={abslog}", "-log"]
cmdline = subprocess.list2cmdline(cmd) + " " + " ".join(flags)
print("[probe] server:", cmdline, flush=True)
server = subprocess.Popen(cmdline, cwd=str(CARLA_ROOT), creationflags=0x08000000,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
result = {"name": args.name, "args": vars(args), "samples": [], "frames": {}}


def kill_server():
    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
    for _ in range(10):
        left = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CarlaUE4-Win64-Shipping.exe"],
                              capture_output=True, text=True).stdout
        if "CarlaUE4-Win64-Shipping.exe" not in left:
            return
        subprocess.run(["taskkill", "/IM", "CarlaUE4-Win64-Shipping.exe", "/F"], capture_output=True)
        time.sleep(1)


actors = []
client = None
world = None
try:
    t0 = time.monotonic()
    ready = False
    while time.monotonic() - t0 < 180:
        try:
            c = carla.Client("127.0.0.1", 2000)
            c.set_timeout(3.0)
            c.get_world().get_weather()
            ready = True
            break
        except Exception:
            time.sleep(2)
    if not ready:
        raise RuntimeError("server never answered RPC")
    client = c
    client.set_timeout(60.0)
    layers = getattr(carla.MapLayer, args.layers)
    world = client.load_world(args.map, map_layers=layers)
    world.set_weather(carla.WeatherParameters(cloudiness=20, wind_intensity=65, sun_altitude_angle=45))
    bp = world.get_blueprint_library().find("vehicle.ford.mustang")
    vehicle = None
    for sp in world.get_map().get_spawn_points():
        vehicle = world.try_spawn_actor(bp, sp)
        if vehicle:
            break
    actors.append(vehicle)
    settings = world.get_settings()
    settings.fixed_delta_seconds = (args.fixed_delta if args.fixed_delta > 0 else None)
    if args.fixed_delta > 0:
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
    elif True:
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 10
    settings.synchronous_mode = bool(args.sync)
    world.apply_settings(settings)
    print("[probe] world ready; sync =", args.sync, flush=True)

    views = {
        "front": carla.Transform(carla.Location(x=0.65, z=1.62), carla.Rotation(pitch=-3)),
        "left": carla.Transform(carla.Location(x=0.65, y=-1.35, z=1.25), carla.Rotation(yaw=165, pitch=-20, roll=-3)),
        "right": carla.Transform(carla.Location(x=0.65, y=1.35, z=1.25), carla.Rotation(yaw=-165, pitch=-20, roll=3)),
    }
    counts, first, last, lengths = {}, {}, {}, {}
    lock = threading.Lock()
    cam_bp = world.get_blueprint_library().find("sensor.camera.rgb")
    for spec in [s for s in args.cams.split(",") if s]:
        name, rest = spec.split(":")
        size, rate = rest.split("@")
        w, h = (int(v) for v in size.split("x"))
        cam_bp.set_attribute("image_size_x", str(w))
        cam_bp.set_attribute("image_size_y", str(h))
        cam_bp.set_attribute("fov", "92")
        if args.nopost and cam_bp.has_attribute("enable_postprocess_effects"):
            cam_bp.set_attribute("enable_postprocess_effects", "False")
        cam_bp.set_attribute("sensor_tick", str(1.0 / float(rate)))
        sensor = world.spawn_actor(cam_bp, views[name.split("_")[0]], attach_to=vehicle,
                                   attachment_type=carla.AttachmentType.Rigid)
        actors.append(sensor)
        counts[name] = 0

        def cb(img, name=name):
            raw = bytes(img.raw_data)
            with lock:
                counts[name] += 1
                lengths[name] = (img.width, img.height, len(raw))
                last[name] = (img.width, img.height, raw)
                first.setdefault(name, (img.width, img.height, raw))
        sensor.listen(cb)
        print(f"[probe] camera {name} {w}x{h}@{rate}", flush=True)

    client.set_timeout(2.5)
    start = time.monotonic()
    prev = dict(counts)
    fails = 0
    last_frame = None
    while time.monotonic() - start < args.duration:
        t1 = time.monotonic()
        if args.sync:
            try:
                world.tick(4.0)
            except Exception as exc:
                print("[probe] tick failed:", str(exc)[:60], flush=True)
        try:
            tr = time.monotonic()
            world.get_weather()
            rpc_ms = round(1000 * (time.monotonic() - tr))
            fails = 0
        except Exception as exc:
            rpc_ms = None
            fails += 1
        if int(t1 - start) != int(prev.get("_t", -1)):
            with lock:
                cur = dict(counts)
            rate = {k: cur[k] - prev.get(k, 0) for k in cur}
            prev = dict(cur)
            prev["_t"] = t1 - start
            try:
                frame_now = world.get_snapshot().frame
            except Exception:
                frame_now = None
            server_fps = None if (frame_now is None or last_frame is None) else frame_now - last_frame
            last_frame = frame_now
            sample = {"t": round(t1 - start, 1), "rpc_ms": rpc_ms, "server_frames": server_fps, "frames_last_s": rate}
            result["samples"].append(sample)
            print("[probe]", json.dumps(sample), flush=True)
        if fails >= 5:
            print("[probe] RPC dead for 5 consecutive checks; stopping early", flush=True)
            break
        time.sleep(max(0.0, (1.0 / args.tick_hz if args.sync else 0.2) - (time.monotonic() - t1)))
    result["total_frames"] = dict(counts)
    result["lengths"] = lengths
    result["rpc_dead"] = fails >= 5

    # analyse frames
    import cv2
    for tag, store in (("first", first), ("last", last)):
        for name, (w, h, raw) in store.items():
            arr = np.frombuffer(raw, dtype=np.uint8)
            expect = w * h * 4
            img = arr[:expect].reshape(h, w, 4)[:, :, :3] if arr.size >= expect else None
            if img is not None:
                cv2.imwrite(str(out / f"{tag}-{name}.png"), img)
                g = img.astype(np.int16).mean(axis=2)
                v = np.abs(np.diff(g, axis=0)).mean()
                hz = np.abs(np.diff(g, axis=1)).mean()
                best = None
                if tag == "last":
                    flat = arr.reshape(-1, 4)[:, :3].astype(np.int16).mean(axis=1)
                    scores = {}
                    for stride in range(max(64, w - 40), w + 200):
                        rows = flat.size // stride
                        if rows < 20:
                            break
                        m = flat[: rows * stride].reshape(rows, stride)
                        scores[stride] = float(np.abs(np.diff(m, axis=0)).mean())
                    best = min(scores, key=scores.get)
                    result["frames"][name] = {"w": w, "h": h, "bytes": int(arr.size), "expected": expect,
                                              "vert_over_horiz": round(float(v / max(hz, 1e-6)), 2),
                                              "best_stride_px": best,
                                              "score_at_width": round(scores.get(w, -1), 2),
                                              "score_at_best": round(scores[best], 2)}
    print("[probe] frames:", json.dumps(result["frames"]), flush=True)
except Exception as exc:
    result["error"] = repr(exc)
    print("[probe] ERROR", repr(exc), flush=True)
finally:
    # try polite destroy briefly, never block long
    try:
        if client:
            client.set_timeout(3.0)
        destroy_ok = True
        for a in reversed(actors):
            try:
                if hasattr(a, "stop"):
                    a.stop()
                a.destroy()
            except Exception:
                destroy_ok = False
                break
        result["destroy_ok"] = destroy_ok
        print("[probe] destroy_ok =", destroy_ok, flush=True)
    except Exception:
        pass
    kill_server()
    (out / "result.json").write_text(json.dumps(result, indent=1))
    print("[probe] done", flush=True)
