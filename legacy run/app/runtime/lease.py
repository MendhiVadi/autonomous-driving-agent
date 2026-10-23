"""One managed CARLA session at a time, shared with the PowerShell launcher."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import sys

MUTEX_NAME = r"Local\AutonomousDrivingAgent.Runtime"

@contextmanager
def runtime_lease():
    if sys.platform != 'win32':
        raise RuntimeError('Managed runtime ownership currently requires Windows')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    owned = False
    try:
        result = api.WaitForSingleObject(handle, 0)
        if result not in (0, 0x80):
            raise RuntimeError('Another managed CARLA session is already active')
        owned = True
        yield
    finally:
        if owned: api.ReleaseMutex(handle)
        api.CloseHandle(handle)
