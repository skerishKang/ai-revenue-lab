"""One-way drain and readiness events shared with the SYSTEM updater.

An absent event means no update. The helper never modifies the protected
installation or starts a privileged process.
"""
from __future__ import annotations

import ctypes
import sys

_DRAIN = r"Global\PadiemHelperUpdateDrain"
_READY = r"Global\PadiemHelperUpdateReady"


def _event(name: str, access: int, *, signal: bool) -> bool:
    if sys.platform != "win32":
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenEventW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenEventW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.SetEvent.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenEventW(access, False, name)
    if not handle:
        return False
    try:
        return bool(kernel.SetEvent(handle)) if signal else kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


def update_requested() -> bool:
    return _event(_DRAIN, 0x00100000, signal=False)


def announce_ready() -> None:
    _event(_READY, 0x0002, signal=True)
