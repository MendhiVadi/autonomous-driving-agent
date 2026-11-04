"""Focused, process-owned CARLA viewport keyboard input for Windows."""
import ctypes
from ctypes import wintypes


class FocusedDrivingKeys:
    """Read cockpit key events or held driving keys from an owned CARLA window.

    Raw input is deliberately limited to driving controls and only while a
    process started by this launcher owns the foreground window.
    """

    _VK_BY_PYGAME_NAME = {
        "K_w": 0x57, "K_UP": 0x26, "K_s": 0x53, "K_DOWN": 0x28,
        "K_a": 0x41, "K_LEFT": 0x25, "K_d": 0x44, "K_RIGHT": 0x27,
        "K_SPACE": 0x20, "K_LSHIFT": 0xA0, "K_LCTRL": 0xA2,
    }

    def __init__(self, pygame, event_keys, carla_window_pids):
        self.pygame = pygame
        self.event_keys = event_keys
        self.carla_window_pids = {int(pid) for pid in carla_window_pids if int(pid) > 0}
        self.user32 = ctypes.WinDLL("user32", use_last_error=True) if hasattr(ctypes, "WinDLL") else None
        if self.user32 is not None:
            self.user32.GetForegroundWindow.restype = wintypes.HWND
            self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            self.user32.GetAsyncKeyState.restype = ctypes.c_short

    def viewport_focused(self):
        if self.user32 is None or not self.carla_window_pids:
            return False
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return False
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return process_id.value in self.carla_window_pids

    def focused(self):
        return bool(self.pygame.key.get_focused() or self.viewport_focused())

    def __getitem__(self, key):
        if self.pygame.key.get_focused():
            return self.event_keys[key]
        if not self.viewport_focused() or self.user32 is None:
            return False
        for name, virtual_key in self._VK_BY_PYGAME_NAME.items():
            if getattr(self.pygame, name, None) == key:
                return bool(self.user32.GetAsyncKeyState(virtual_key) & 0x8000)
        return False


def parse_key_schedule(text):
    """Parse ``[[start_s, end_s, ["w", "d"]], ...]`` into validated intervals."""
    import json
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("key schedule must be a list of [start, end, [keys]] items")
    schedule = []
    for item in data:
        if not (isinstance(item, (list, tuple)) and len(item) == 3):
            raise ValueError("each key schedule item needs start, end and keys")
        start, end, names = item
        if isinstance(start, bool) or isinstance(end, bool) or not all(
                isinstance(v, (int, float)) and v == v and abs(v) != float("inf") for v in (start, end)):
            raise ValueError("key schedule times must be finite numbers")
        if start < 0 or end <= start:
            raise ValueError("key schedule needs 0 <= start < end")
        if not isinstance(names, (list, tuple)) or not names or not all(isinstance(n, str) for n in names):
            raise ValueError("key schedule keys must be a non-empty list of names")
        schedule.append((float(start), float(end), tuple(n.lower() for n in names)))
    return schedule


class ScriptedDrivingKeys:
    """Diagnostic stand-in for keyboard input: replays a key schedule in-process.

    Used only with ``--scripted-keys``. It exercises the real key-to-control chain
    (build_vehicle_control, limiters, CARLA response) without sending any input to
    the desktop. It does not test window focus or SDL keyboard events.
    """

    def __init__(self, pygame, schedule, clock):
        self.pygame = pygame
        self.schedule = list(schedule)
        self.clock = clock
        self.started_at = None

    def start(self):
        for _start, _end, names in self.schedule:
            for name in names:
                self._key_code(name)
        self.started_at = self.clock()

    def elapsed(self):
        return 0.0 if self.started_at is None else self.clock() - self.started_at

    def focused(self):
        return True

    def pressed_names(self):
        now = self.elapsed()
        return {name for start, end, names in self.schedule if start <= now < end for name in names}

    def _key_code(self, name):
        # pygame spells letters K_w but named keys K_UP / K_SPACE.
        for candidate in ("K_" + name, "K_" + name.upper()):
            code = getattr(self.pygame, candidate, None)
            if code is not None:
                return code
        raise ValueError(f"unknown key name in schedule: {name!r}")

    def __getitem__(self, key):
        return any(self._key_code(name) == key for name in self.pressed_names())
