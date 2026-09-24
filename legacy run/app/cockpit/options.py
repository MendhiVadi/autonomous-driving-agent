"""Cockpit command-line options and validation, without simulator startup."""
import argparse
import math


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--map", default=None, help="Optional map, e.g. Town05")
    parser.add_argument("--spawn-index", type=int, default=None,
                        help="Use a specific map spawn point for repeatable diagnostics")
    parser.add_argument("--window-width", type=int, default=1280)
    parser.add_argument("--window-height", type=int, default=720)
    parser.add_argument("--target-fps", type=int, default=60,
                        help="Cockpit render/input rate (default: 60 FPS)")
    parser.add_argument("--camera-fps", type=int, default=30,
                        help="Front-camera capture target (default: 30 FPS)")
    parser.add_argument("--mirror-camera-fps", type=int, default=12,
                        help="Rear/side capture target (default: 12 FPS)")
    parser.add_argument("--input-latch-ms", type=float, default=35.0,
                        help="Short key-tap retention window (default: 35 ms)")
    parser.add_argument("--agent-timeout", type=float, default=0.25,
                        help="Seconds to retain the latest agent action before fail-safe braking")
    parser.add_argument("--max-runtime-seconds", type=float, default=0.0,
                        help="Exit cleanly after this many seconds; 0 keeps running")
    parser.add_argument("--agent-stdin", action="store_true",
                        help="Read JSON actions from stdin while showing the driving window")
    parser.add_argument("--screenshot-path", default=None,
                        help="Save one fully rendered cockpit frame for visual verification")
    parser.add_argument("--camera-profile", choices=("parking", "safe", "map"), default="parking",
                        help="map=no scene rendering; parking=four cameras; safe=front camera")
    parser.add_argument("--low-scenery", action="store_true",
                        help="Keep a clear, dry daytime scene and omit optional optimized-map effects")
    parser.add_argument("--presentation", action="store_true",
                        help="Full scenery with a larger forward camera and paced simulation")
    parser.add_argument("--runtime-rpc-timeout", type=float, default=2.0,
                        help="Fail quickly if the CARLA server disappears")
    parser.add_argument("--graphics-throttle-start-kmh", type=float, default=135.0,
                        help="Begin narrowing throttle to protect camera smoothness")
    parser.add_argument("--graphics-speed-cap-kmh", type=float, default=160.0,
                        help="Speed where cockpit throttle reaches zero")
    parser.add_argument("--visual-austerity-start-kmh", type=float, default=45.0,
                        help="Disable animated weather effects above this speed")
    parser.add_argument("--visual-austerity-resume-kmh", type=float, default=38.0,
                        help="Restore selected weather below this speed")
    parser.add_argument("--route-speed-kmh", type=float, default=45.0,
                        help="Target speed for click-to-drive navigation")
    parser.add_argument("--neural-visual", action="store_true",
                        help="Open live neural activity in the browser; F8 reopens it")
    parser.add_argument("--neural-lane-assist", action="store_true",
                        help="Bounded, labelled steering correction and reduced speed off centre")
    parser.add_argument("--route-destination", nargs=2, type=float, metavar=("X", "Y"),
                        help="Start a neural route to map coordinates without a mouse click")
    parser.add_argument("--route-policy", default="nn_policy_colab.json",
                        help="Deployable contract-v2 neural policy for map routes")
    parser.add_argument("--preload-route-policy", action="store_true",
                        help="Load the network and road planner before accepting destinations")
    parser.add_argument("--map-open-on-start", action="store_true",
                        help="Open the destination map immediately (visual testing)")
    parser.add_argument("--human-demo", action="store_true",
                        help="Record completed manual map routes as training demonstrations")
    parser.add_argument("--human-output-dir", default="episodes/expert",
                        help="Training folder for completed human demonstrations")
    parser.add_argument("--human-target-episodes", type=int, default=12,
                        help="Number of completed human routes requested for this dataset")
    args = parser.parse_args(argv)
    for name, value in vars(args).items():
        if isinstance(value, float) and not math.isfinite(value):
            parser.error(f"--{name.replace(chr(95), chr(45))} must be finite")
    if args.presentation and (args.low_scenery or args.camera_profile == "map"):
        parser.error("presentation requires camera rendering without low-scenery mode")
    if args.camera_profile == "map" or args.low_scenery or args.presentation:
        args.target_fps = min(args.target_fps, 20)
    if args.window_width < 800 or args.window_height < 450:
        parser.error("the cockpit requires at least an 800x450 window")
    if args.target_fps <= 0 or args.camera_fps <= 0 or args.mirror_camera_fps <= 0:
        parser.error("display and camera FPS values must be positive")
    if not 0.0 <= args.input_latch_ms <= 250.0:
        parser.error("--input-latch-ms must be between 0 and 250")
    if args.agent_timeout <= 0:
        parser.error("--agent-timeout must be positive")
    if args.runtime_rpc_timeout <= 0:
        parser.error("--runtime-rpc-timeout must be positive")
    if args.max_runtime_seconds < 0:
        parser.error("--max-runtime-seconds cannot be negative")
    if (args.graphics_throttle_start_kmh < 0 or
            args.graphics_speed_cap_kmh <= args.graphics_throttle_start_kmh):
        parser.error("graphics speed cap must be above the non-negative throttle start")
    if (args.visual_austerity_resume_kmh < 0 or
            args.visual_austerity_start_kmh <= args.visual_austerity_resume_kmh):
        parser.error("visual austerity start must be above its non-negative resume speed")
    if args.route_speed_kmh <= 0 or args.route_speed_kmh > args.graphics_speed_cap_kmh:
        parser.error("--route-speed-kmh must be positive and no higher than the speed cap")
    if args.human_target_episodes <= 0:
        parser.error("--human-target-episodes must be positive")
    return args
