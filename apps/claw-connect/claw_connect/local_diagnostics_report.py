"""#3099 bounded local diagnostics the Connector hands to its Resident.

The Connector owns three local observations the server cannot see:

* whether the canonical Agent source files are present,
* whether the Windows autostart entry is enabled,
* whether the supervised Resident is running.

They are written to one small file inside the existing Connector state
directory, and the Resident picks it up for the heartbeat it already sends.
No new server channel, no new polling and no new Broker is involved.

The file carries **only** the three closed labels. It never carries a file
path, a credential, a token, a command output or a stack trace, and it never
carries a timestamp: the server owns freshness, so a client clock cannot make
a stale observation look current.

The ``revision`` is a monotonically increasing counter. It lets the server
tell a *fresh* observation from one that simply stopped advancing, without
trusting any client clock.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

#: The file the Connector writes and the Resident reads.
LOCAL_DIAGNOSTICS_FILENAME = "connector-diagnostics.json"

#: The version of the local file shape.
LOCAL_DIAGNOSTICS_VERSION = "padiem-connector-local-diagnostics.v1"

#: The three closed labels the local file carries.
LOCAL_CHECK_KEYS = ("agent_source", "autostart", "resident")

#: The local label vocabulary. ``unknown`` means the Connector could not
#: read the fact - never that the fact is confirmed negative.
LOCAL_AGENT_SOURCE_STATES = ("ready", "not_installed", "invalid", "unknown")
LOCAL_AUTOSTART_STATES = ("enabled", "disabled", "unknown")
LOCAL_RESIDENT_STATES = ("running", "stopped", "unknown")

_LOCAL_STATE_VOCABULARY: Mapping[str, tuple[str, ...]] = {
    "agent_source": LOCAL_AGENT_SOURCE_STATES,
    "autostart": LOCAL_AUTOSTART_STATES,
    "resident": LOCAL_RESIDENT_STATES,
}

#: The environment variable that names the file for the Resident. The
#: Connector already passes its pinned release values to the Resident this
#: way, so no new channel is opened.
LOCAL_DIAGNOSTICS_FILE_ENV = "PADIEM_AGENT_LOCAL_DIAGNOSTICS_FILE"

#: The revision the Connector uses when it has never written the file.
_INITIAL_REVISION = 0


def local_diagnostics_path(state_dir: str | os.PathLike[str]) -> Path:
    """The local diagnostics file inside the Connector state directory."""
    return Path(state_dir).expanduser() / LOCAL_DIAGNOSTICS_FILENAME


def _bounded_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return _INITIAL_REVISION
    if value < 0 or value > 2**31 - 1:
        return _INITIAL_REVISION
    return value


def normalize_local_checks(raw: Any) -> dict[str, str] | None:
    """Normalize the three labels, or ``None`` when the file is unusable.

    A partial file, an unknown label or a file with extra keys is refused
    rather than guessed. The Resident then reports nothing at all, and the
    server shows "확인 불가" instead of a fabricated state.
    """
    if not isinstance(raw, Mapping) or set(raw) != set(LOCAL_CHECK_KEYS):
        return None
    result: dict[str, str] = {}
    for key in LOCAL_CHECK_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or value not in _LOCAL_STATE_VOCABULARY[key]:
            return None
        result[key] = value
    return result


def write_local_diagnostics(
    state_dir: str | os.PathLike[str], *, checks: Mapping[str, str]
) -> Path | None:
    """Write the bounded local diagnostics file.

    The revision advances on every write, even when the labels did not
    change, so the server can tell "the observation is still being made"
    from "the observation stopped".
    """
    normalized = normalize_local_checks(checks)
    if normalized is None:
        return None
    path = local_diagnostics_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = read_local_diagnostics(state_dir)
        revision = _INITIAL_REVISION + 1
        if previous is not None:
            revision = _bounded_revision(previous.get("revision")) + 1
        payload = {
            "version": LOCAL_DIAGNOSTICS_VERSION,
            "revision": revision,
            "checks": normalized,
        }
        # Write through a temporary file so a reader never sees a half
        # written document.
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent),
            prefix=LOCAL_DIAGNOSTICS_FILENAME + ".", suffix=".tmp", delete=False,
        )
        try:
            with handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            os.replace(handle.name, path)
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
    except (OSError, TypeError, ValueError):
        return None
    return path


def read_local_diagnostics(
    state_dir: str | os.PathLike[str],
) -> dict[str, Any] | None:
    """Read the bounded local diagnostics file, or ``None``.

    A missing, unreadable, malformed or foreign file is ``None``. The caller
    then reports nothing, and the server shows "확인 불가".
    """
    path = local_diagnostics_path(state_dir)
    try:
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != LOCAL_DIAGNOSTICS_VERSION:
        return None
    checks = normalize_local_checks(raw.get("checks"))
    if checks is None:
        return None
    return {
        "version": LOCAL_DIAGNOSTICS_VERSION,
        "revision": _bounded_revision(raw.get("revision")),
        "checks": checks,
    }


def local_diagnostics_file_from_environ(
    environ: Mapping[str, str],
) -> Path | None:
    """The diagnostics file the Connector named for the Resident."""
    value = environ.get(LOCAL_DIAGNOSTICS_FILE_ENV)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return Path(value).expanduser()
    except (OSError, TypeError, ValueError):
        return None


__all__ = [
    "LOCAL_AGENT_SOURCE_STATES",
    "LOCAL_AUTOSTART_STATES",
    "LOCAL_CHECK_KEYS",
    "LOCAL_DIAGNOSTICS_FILE_ENV",
    "LOCAL_DIAGNOSTICS_FILENAME",
    "LOCAL_DIAGNOSTICS_VERSION",
    "LOCAL_RESIDENT_STATES",
    "local_diagnostics_file_from_environ",
    "local_diagnostics_path",
    "normalize_local_checks",
    "read_local_diagnostics",
    "write_local_diagnostics",
]
