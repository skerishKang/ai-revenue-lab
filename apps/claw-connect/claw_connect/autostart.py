"""Opt-in "run at Windows logon" registration for Claw Connect (#4139 item 6).

Never enabled by default and never written to HKLM, so Connect never asks for
an administrator right. Only the current user's ``Run`` key is used, and the
value is removed on disconnect so a user who turns autostart off is not
re-registered at the next logon.

The registry is reached through a seam: ``WindowsRunKeyStore`` performs the
real HKCU read/write, ``MemoryRunKeyStore`` carries the same contract for the
offline tests and CI.
"""

from __future__ import annotations

import sys
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class RunKeyStore(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, command: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemoryRunKeyStore:
    """In-memory stand-in with the HKCU Run contract (tests / non-Windows)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, command: str) -> None:
        if not command.strip():
            raise ValueError("autostart command must not be empty")
        self.values[name] = command

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class WindowsRunKeyStore:
    """HKCU ``Run`` access. Administrator rights are never required."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsRunKeyStore requires a Windows host")

    def read(self, name: str) -> str | None:
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        return value if isinstance(value, str) else None

    def write(self, name: str, command: str) -> None:
        if not command.strip():
            raise ValueError("autostart command must not be empty")
        import winreg  # noqa: PLC0415

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def delete(self, name: str) -> None:
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


class Autostart:
    """User-chosen autostart. Off until the user explicitly enables it."""

    def __init__(self, name: str, store: RunKeyStore | None = None) -> None:
        self._name = name
        self._store = store

    @property
    def store(self) -> RunKeyStore:
        if self._store is None:
            self._store = (
                WindowsRunKeyStore() if sys.platform == "win32" else MemoryRunKeyStore()
            )
        return self._store

    def enable(self, command: str) -> None:
        self.store.write(self._name, command)

    def disable(self) -> None:
        self.store.delete(self._name)

    def is_enabled(self) -> bool:
        return self.store.read(self._name) is not None

    def current_command(self) -> str | None:
        return self.store.read(self._name)
