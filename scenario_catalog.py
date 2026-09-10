"""Scenario catalog for future CARLA traffic and robustness experiments."""
SCENARIOS = {
    "urban": {"maps": ["Town03", "Town04", "Town05", "Town10HD"], "traffic": 30},
    "highway": {"maps": ["Town05", "Town06", "Town07"], "traffic": 20},
    "rural": {"maps": ["Town01", "Town02"], "traffic": 12},
    "intersection": {"maps": ["Town03", "Town04"], "traffic": 40},
    "additional_maps": {"maps": ["Town11", "Town12", "Town13", "Town15"], "traffic": 30},
}

WEATHER_PRESETS = ["ClearNoon", "CloudyNoon", "WetNoon", "WetCloudyNoon",
                   "SoftRainNoon", "HardRainNoon", "ClearSunset", "FoggyNoon"]

POTHOLE_MODES = [
    "visual_only",       # texture/mesh cue for perception
    "physical_bump",     # collision geometry affects vehicle dynamics
    "avoidable_or_crossable",  # planner chooses based on risk and time
]
