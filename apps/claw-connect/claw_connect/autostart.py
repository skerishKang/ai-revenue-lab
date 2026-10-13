"""Logon autostart for Claw Connect (#4139 item 6).

Since the 2026-10-13 founder-led AX pilot contract the PC registers itself to
start at Windows logon **by default once the install succeeded**, and the owner
can turn it off. The previous version of this module was opt-in / default-OFF,
which is a source defect against that contract.

Two facts are kept apart, because conflating them is what made the old module
wrong:

* **effective registration** — the presence of a value under
  ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``. This is what
  Windows actually acts on at logon.
* **the owner's explicit choice** — ``on`` / ``off`` / never chosen, kept in a
  separate per-user key (``HKCU\\Software\\Padiem\\ClawConnect``). It has to
  survive restart and logon, so it can never live in the ``Run`` key itself:
  Windows executes *every* value it finds there, so a preference marker written
  beside the command would be launched as a command.

Precedence is deliberate:

* a successful install registers autostart **by default** — but only once the
  canonical credential is durably committed and valid, which in this codebase
  is exactly a record returned by ``ConnectorEnrollment.record()`` after its
  stage-then-publish commit. Nothing is written before that check passes, and
  the owner-facing CLI presents the same evidence, so ``autostart on`` is not a
  way around the gate;
* an explicit ``off`` always wins over the default, so an owner who turned
  autostart off is never silently re-enabled by a later reconnect, disconnect,
  in-process failure, restart or re-install. Because the ``off`` is recorded
  before the value is removed, a process killed in between leaves an orphaned
  entry that the next reconcile removes — but only if it is an entry this
  module recognises as its own;
* a transient offline/disconnect is a *connection* event and changes nothing
  here, so a flaky network can never erase the owner's decision;
* a revoke/unpair *suspends* the registration (the value is removed) without
  erasing the owner's recorded choice, so a later re-enrollment falls back to
  the contract default.

Nothing here is a device identity, a credential, a service or a scheduled task.
The registration is always the current user's ``Run`` key — never HKLM — so
Connect never asks for an administrator right, and a command carrying
secret-bearing material is refused rather than written.

The registry is reached through seams: ``WindowsRunKeyStore`` /
``WindowsPreferenceStore`` perform the real HKCU read/write, and the
``Memory*`` pairs carry the same contract for the offline tests and CI.
"""

from __future__ import annotations

import os
import base64
from pathlib import Path
import re
import sys
from enum import Enum
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
#: The owner's explicit choice lives in its own per-user key. It must not live
#: in ``RUN_KEY``: Windows executes every value found there.
PREFERENCE_KEY = r"Software\Padiem\ClawConnect"
PREFERENCE_VALUE_NAME = "Autostart"

#: Diagnostics/test overrides, mirroring ``CLAW_CONNECT_STATE_DIR``: they let a
#: test drive the real stores without touching a real user profile. Both stay
#: HKCU-only, so no override can ever require an administrator right.
RUN_KEY_ENV_VAR = "CLAW_CONNECT_AUTOSTART_RUN_KEY"
PREFERENCE_KEY_ENV_VAR = "CLAW_CONNECT_AUTOSTART_PREF_KEY"

PREFERENCE_ON = "on"
PREFERENCE_OFF = "off"

#: How an existing ``Run`` value is classified.
REGISTRATION_ABSENT = "absent"
REGISTRATION_REGISTERED = "registered"
#: A value this module refuses to own: empty, or carrying secret material.
REGISTRATION_CORRUPT = "corrupt"

#: Lifecycle events the connector may report. Closed set — an unknown event is
#: a programming error, never a silent no-op.
EVENT_TRANSIENT_OFFLINE = "transient_offline"
EVENT_USER_PAUSE = "user_pause"
EVENT_UNPAIR = "unpair"
EVENT_REVOKE = "revoke"

#: What ``apply_lifecycle`` decided to do.
ACTION_KEEP = "keep"
ACTION_SUSPEND = "suspend"

#: Secret-bearing material must never reach the registry command line, argv or
#: a log. Deliberately narrow: a parameter assignment whose *name* says secret.
_SECRET_IN_COMMAND = re.compile(
    r"(?:^|[\s\"'=:-])"
    r"(?:token|secret|password|passwd|credential|credentials|pairing_?code"
    r"|proof|api_?key|auth)"
    r"\s*[:=]",
    re.IGNORECASE,
)


def start_command() -> str:
    """Bound to the installed package root even at logon with a foreign cwd."""
    root = Path(__file__).resolve().parent.parent
    encoded = base64.b64encode(str(root).encode("utf-8")).decode("ascii")
    code = (
        "import base64,sys,runpy;"
        f"sys.path.insert(0,base64.b64decode('{encoded}').decode('utf-8'));"
        "sys.argv=['claw-connect','start'];"
        "runpy.run_module('claw_connect',run_name='__main__')"
    )
    return f'"{sys.executable}" -c "{code}"'


# The value name alone does not establish ownership of a Windows Run command.
_LEGACY_MODULE_START = re.compile(
    r'^"[^"]*[\\/](?:python(?:[0-9]+(?:\\.[0-9]+)?)?|py)(?:\\.exe)?"'
    r' -m claw_connect start$', re.IGNORECASE,
)


def _owned_start_command(command: str) -> bool:
    return (
        command == start_command()
        or _LEGACY_MODULE_START.fullmatch(command) is not None
    )


class AutostartRefused(RuntimeError):
    """Raised when autostart must not be (re)registered. Always fails closed."""


class AutostartOutcome(str, Enum):
    """The closed set of results a gated registration path may return."""

    REGISTERED = "registered"
    ALREADY_REGISTERED = "already_registered"
    #: The owner opted out and there was nothing left to remove.
    SUPPRESSED_BY_OWNER = "suppressed_by_owner"
    #: The owner opted out and an orphaned owned entry was removed. This is the
    #: crash-in-the-middle recovery: ``disable()`` records ``off`` before it
    #: removes the value, so a process killed in between leaves a registration
    #: Windows would still execute at the next logon.
    OPT_OUT_RECONCILED = "opt_out_reconciled"


class DurableEnrollment(Protocol):
    """The two facts autostart needs from a *committed* enrollment record.

    Only a record that the stage-then-publish commit already published can
    answer these; autostart never mints one and never treats a claim it cannot
    read as evidence.
    """

    def is_enrolled(self) -> bool: ...
    def lifecycle(self) -> str | None: ...


class RunKeyStore(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, command: str) -> None: ...
    def delete(self, name: str) -> None: ...


class PreferenceStore(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemoryRunKeyStore:
    """In-memory stand-in with the HKCU Run contract (tests / non-Windows)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        #: Every ``write`` in order, so a test can prove "registered once".
        self.writes: list[tuple[str, str]] = []

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, command: str) -> None:
        if not command.strip():
            raise ValueError("autostart command must not be empty")
        self.values[name] = command
        self.writes.append((name, command))

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class MemoryPreferenceStore:
    """In-memory stand-in with the per-user preference contract."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class WindowsRunKeyStore:
    """HKCU ``Run`` access. Administrator rights are never required."""

    def __init__(self, key: str | None = None) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsRunKeyStore requires a Windows host")
        self._key = key or os.environ.get(RUN_KEY_ENV_VAR) or RUN_KEY

    def read(self, name: str) -> str | None:
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        # Windows only launches string values, so anything else is reported as
        # absent rather than as a registration this module owns.
        return value if isinstance(value, str) else None

    def write(self, name: str, command: str) -> None:
        if not command.strip():
            raise ValueError("autostart command must not be empty")
        import winreg  # noqa: PLC0415

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._key) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def delete(self, name: str) -> None:
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._key, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return


class WindowsPreferenceStore:
    """HKCU per-user autostart preference. Never HKLM, never a service."""

    def __init__(
        self,
        key: str | None = None,
        value_name: str = PREFERENCE_VALUE_NAME,
    ) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsPreferenceStore requires a Windows host")
        self._key = key or os.environ.get(PREFERENCE_KEY_ENV_VAR) or PREFERENCE_KEY
        self._value_name = value_name

    def read(self, name: str) -> str | None:  # noqa: ARG002 — single-value store
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key) as key:
                value, _ = winreg.QueryValueEx(key, self._value_name)
        except FileNotFoundError:
            return None
        return value if isinstance(value, str) else None

    def write(self, name: str, value: str) -> None:  # noqa: ARG002
        import winreg  # noqa: PLC0415

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._key) as key:
            winreg.SetValueEx(key, self._value_name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:  # noqa: ARG002
        import winreg  # noqa: PLC0415

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._key, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, self._value_name)
        except FileNotFoundError:
            return


class Autostart:
    """Logon autostart: default-ON after a successful install, owner-reversible.

    ``store`` and ``preference_store`` are both seams. On Windows they default
    to the real HKCU implementations; tests must inject the memory pair so no
    test ever writes the developer's registry.
    """

    def __init__(
        self,
        name: str,
        store: RunKeyStore | None = None,
        *,
        preference_store: PreferenceStore | None = None,
    ) -> None:
        self._name = name
        self._store = store
        self._preference_store = preference_store

    @property
    def store(self) -> RunKeyStore:
        if self._store is None:
            self._store = (
                WindowsRunKeyStore() if sys.platform == "win32" else MemoryRunKeyStore()
            )
        return self._store

    @property
    def preference_store(self) -> PreferenceStore:
        if self._preference_store is None:
            self._preference_store = (
                WindowsPreferenceStore()
                if sys.platform == "win32"
                else MemoryPreferenceStore()
            )
        return self._preference_store

    # -- effective registration --------------------------------------------
    def classify(self) -> str:
        """``absent`` / ``registered`` / ``corrupt`` — never guesses."""
        try:
            value = self.store.read(self._name)
        except Exception:
            return REGISTRATION_CORRUPT
        if value is None:
            return REGISTRATION_ABSENT
        if (
            not value.strip() or _SECRET_IN_COMMAND.search(value)
            or not _owned_start_command(value)
        ):
            return REGISTRATION_CORRUPT
        return REGISTRATION_REGISTERED

    def is_enabled(self) -> bool:
        """True only for a registration this module recognises as its own."""
        return self.classify() == REGISTRATION_REGISTERED

    def current_command(self) -> str | None:
        return self.store.read(self._name)

    # -- the owner's explicit choice ---------------------------------------
    def preference(self) -> str | None:
        """``on`` / ``off`` / ``None`` when the owner never chose.

        An unreadable or unrecognised marker fails closed as ``off``: it is
        never allowed to re-enable a registration the owner may have turned off.
        """
        value = self.preference_store.read(PREFERENCE_VALUE_NAME)
        if value == PREFERENCE_ON:
            return PREFERENCE_ON
        if value is None:
            return None
        return PREFERENCE_OFF

    def set_preference(self, value: str | None) -> None:
        if value is None:
            self.preference_store.delete(PREFERENCE_VALUE_NAME)
        elif value in (PREFERENCE_ON, PREFERENCE_OFF):
            self.preference_store.write(PREFERENCE_VALUE_NAME, value)
        else:
            raise ValueError("autostart preference must be 'on', 'off' or None")

    # -- owner actions ------------------------------------------------------
    def enable(self, command: str, enrollment: DurableEnrollment) -> AutostartOutcome:
        """The owner explicitly turned autostart on.

        Gated on a durable, valid credential exactly like the install default:
        the owner-facing CLI is **not** a bypass around ``register_after_install``.
        The caller must present the real committed record — this module never
        mints one and never trusts a flag.

        Records the choice, then registers. A recognised existing value is
        replaced with the current command; a corrupt one is never silently
        overwritten.
        """
        self._gate(command, enrollment)
        self.set_preference(PREFERENCE_ON)
        return self._register(command)

    def disable(self) -> None:
        """The owner turned autostart off. Durable across restart and logon.

        The choice is recorded *before* the value is removed: if the process
        dies in between, the recorded opt-out is already durable and the next
        reconcile removes the value again (see
        ``AutostartOutcome.OPT_OUT_RECONCILED``). The opposite order could leave
        no record of the opt-out and let a later install silently re-enable it.
        """
        # Persist explicit OFF even when foreign/corrupt Run data cannot be
        # safely removed: a matching Run *name* is not an ownership proof.
        state = self.classify()
        self.set_preference(PREFERENCE_OFF)
        if state == REGISTRATION_CORRUPT:
            raise AutostartRefused("existing autostart registration is corrupt")
        self.store.delete(self._name)

    # -- contract default, after a successful install -----------------------
    def register_after_install(
        self, command: str, enrollment: DurableEnrollment
    ) -> AutostartOutcome:
        """Default-ON: reconcile the logon registration with the contract.

        Refuses unless ``enrollment`` is a committed, enrolled, live record — so
        no ``Run`` value is ever written before the canonical credential is
        durable (the LOCAL2 D1 stage-then-publish invariant), and a redeem
        receipt alone can never register the PC. Idempotent: a second call for
        the same command reports ``ALREADY_REGISTERED`` and writes nothing.

        It is also the recovery path for an interrupted ``disable()``. The
        owner's ``off`` is durable, so it is honoured here without needing a
        credential; if a recognised owned entry survived the interruption it is
        removed (``OPT_OUT_RECONCILED``). Only an entry this module recognises
        as its own is ever removed — a corrupt or foreign value is refused and
        left untouched.
        """
        self._validate_command(command)
        state = self.classify()
        if state == REGISTRATION_CORRUPT:
            raise AutostartRefused("existing autostart registration is corrupt")
        if self.preference() == PREFERENCE_OFF:
            if state == REGISTRATION_REGISTERED:
                self.store.delete(self._name)
                return AutostartOutcome.OPT_OUT_RECONCILED
            return AutostartOutcome.SUPPRESSED_BY_OWNER
        if not _is_live_enrollment(enrollment):
            raise AutostartRefused(
                "no durable, valid canonical credential for this PC"
            )
        return self._register(command)

    # -- lifecycle ----------------------------------------------------------
    def apply_lifecycle(self, event: str) -> str:
        """One decision point for the connection/device lifecycle.

        * ``transient_offline`` / ``user_pause`` — a connection event, not a
          logon-startup decision. The registration and the owner's choice are
          left exactly as they are.
        * ``unpair`` / ``revoke`` — the binding is gone, so the logon
          registration is *suspended*. The owner's recorded choice is kept, so
          a later re-enrollment falls back to the contract default rather than
          to a stale "on".

        ``user_pause`` is deliberately non-durable: it stops reconnecting in
        this session, while the PC still comes up at the next logon. Making it
        durable is the ``disable()`` action, which the owner can also choose.
        """
        if event in (EVENT_TRANSIENT_OFFLINE, EVENT_USER_PAUSE):
            return ACTION_KEEP
        if event in (EVENT_UNPAIR, EVENT_REVOKE):
            if self.classify() == REGISTRATION_CORRUPT:
                raise AutostartRefused("existing autostart registration is corrupt")
            self.store.delete(self._name)
            return ACTION_SUSPEND
        raise ValueError(f"unknown autostart lifecycle event: {event!r}")

    # -- internals ----------------------------------------------------------
    def _gate(self, command: str, enrollment: object) -> None:
        """The fail-closed precondition shared by every registration path.

        Both the install default and the owner CLI come through here, so the
        credential invariant cannot hold on one entrypoint and not the other.
        """
        self._validate_command(command)
        if self.classify() == REGISTRATION_CORRUPT:
            raise AutostartRefused("existing autostart registration is corrupt")
        if not _is_live_enrollment(enrollment):
            raise AutostartRefused(
                "no durable, valid canonical credential for this PC"
            )

    def _register(self, command: str) -> AutostartOutcome:
        if self.store.read(self._name) == command:
            return AutostartOutcome.ALREADY_REGISTERED
        self.store.write(self._name, command)
        return AutostartOutcome.REGISTERED

    def _validate_command(self, command: str) -> None:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("autostart command must not be empty")
        if _SECRET_IN_COMMAND.search(command):
            raise AutostartRefused(
                "autostart command must not carry credential material"
            )
        if not _owned_start_command(command):
            raise AutostartRefused("autostart command is not an owned Connector start")


def _is_live_enrollment(enrollment: object) -> bool:
    """True only for a committed, enrolled, non-revoked, non-expired record.

    The blocked lifecycle set is imported from the enrollment contract rather
    than copied, so a new blocked lifecycle cannot drift out of this gate. The
    import is lazy so the thin tray module does not pull in the enrollment
    stack at import time.
    """
    is_enrolled = getattr(enrollment, "is_enrolled", None)
    lifecycle_of = getattr(enrollment, "lifecycle", None)
    if not callable(is_enrolled) or not callable(lifecycle_of):
        return False
    try:
        if not is_enrolled():
            return False
        lifecycle = lifecycle_of()
    except Exception:
        return False
    from .enrollment import (  # noqa: PLC0415
        LIFECYCLE_CREDENTIAL_EXPIRED,
        LIFECYCLE_REVOKED,
    )

    return lifecycle is not None and lifecycle not in (
        LIFECYCLE_REVOKED,
        LIFECYCLE_CREDENTIAL_EXPIRED,
    )
