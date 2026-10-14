"""Single-executable-per-PC guarantee for Claw Connect (#4139 item 7).

The tray must not appear twice on one PC regardless of how it was started:
Start Menu, autostart at Windows logon, a second double click or ``npx``.

Two backends behind one seam:

* ``WindowsMutexBackend`` — a real Win32 named mutex, so the guarantee holds
  across the whole interactive session (and is observable by the operator).
* ``FileLockBackend`` — a portable advisory lock used by the offline tests and
  by any non-Windows developer host. It is never selected automatically on
  Windows.

A second ``acquire`` returns ``False``; the caller then reports the existing
instance and exits without opening a tray icon.
"""

from __future__ import annotations

import os
import sys
from typing import Protocol

ERROR_ALREADY_EXISTS = 183


class SingleInstanceBackend(Protocol):
    def acquire(self) -> bool: ...
    def release(self) -> None: ...


class WindowsMutexBackend:
    """Win32 named mutex. Windows interactive session only."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._handle = None

    def acquire(self) -> bool:
        import win32api  # noqa: PLC0415 — optional dependency, imported late
        import win32event  # noqa: PLC0415

        handle = win32event.CreateMutex(None, False, self._name)
        # CreateMutex sets the thread's last-error when the mutex already
        # exists; it must be read before any other Win32 call.
        already = win32api.GetLastError() == ERROR_ALREADY_EXISTS
        if already:
            win32api.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            import win32api  # noqa: PLC0415

            win32api.CloseHandle(handle)
        except Exception:
            pass


class FileLockBackend:
    """Portable exclusive lock used for offline tests and non-Windows hosts."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt  # noqa: PLC0415

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)


class SingleInstance:
    """Context manager enforcing "exactly one Connect process on this PC"."""

    def __init__(self, name: str, backend: SingleInstanceBackend | None = None) -> None:
        self._name = name
        self._backend = backend or default_backend(name)
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        if self._backend.acquire():
            self._held = True
            return True
        self._held = False
        return False

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        self._backend.release()

    def __enter__(self) -> "SingleInstance":
        if not self.acquire():
            raise AlreadyRunning(self._name)
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


class AlreadyRunning(RuntimeError):
    """Raised when a second Connect process tries to start."""


def default_backend(name: str) -> SingleInstanceBackend:
    if sys.platform == "win32":
        try:
            import win32event  # noqa: F401,PLC0415

            return WindowsMutexBackend(name)
        except Exception:
            pass
    # Fallback path only: tests, CI and non-Windows developer hosts.
    import tempfile  # noqa: PLC0415

    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return FileLockBackend(os.path.join(tempfile.gettempdir(), f"{safe}.lock"))
