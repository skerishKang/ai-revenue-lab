"""#3099 the Resident hands the Connector's local diagnostics to the Broker.

The Connector observes three local facts the server cannot see: the Agent
source files, the Windows autostart entry and the supervised Resident. It
writes them to one bounded local file; this module reads that file and puts
the result on the heartbeat the Resident already sends.

The hint is display only. It never becomes an execution permission, a
registration proof, a credential or an ONLINE claim, and it carries no path,
no secret and no log line. The vocabulary is the shared one in
``padiem_ai_core.pc_device_diagnostics`` so the server, the Broker and the
web surface cannot drift apart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from padiem_ai_core.pc_device_diagnostics import (
    DIAGNOSTIC_KEYS,
    PC_DEVICE_DIAGNOSTICS_VERSION,
    normalize_diagnostics,
)

#: The environment variable the Connector uses to name the local file.
LOCAL_DIAGNOSTICS_FILE_ENV = "PADIEM_AGENT_LOCAL_DIAGNOSTICS_FILE"

#: The local file version this module reads.
LOCAL_DIAGNOSTICS_VERSION = "padiem-connector-local-diagnostics.v1"

#: The local label vocabulary. It is deliberately the same shape as the
#: canonical one, so the mapping is a copy and not a translation.
_LOCAL_CHECK_KEYS = ("agent_source", "autostart", "resident")

_LOCAL_STATE_VOCABULARY: Mapping[str, tuple[str, ...]] = {
    "agent_source": ("ready", "not_installed", "invalid", "unknown"),
    "autostart": ("enabled", "disabled", "unknown"),
    "resident": ("running", "stopped", "unknown"),
}


def _bounded_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0 or value > 2**31 - 1:
        return 0
    return value


def normalize_local_checks(raw: Any) -> dict[str, str] | None:
    """Normalize the local labels, or ``None`` when the file is unusable."""
    if not isinstance(raw, Mapping) or set(raw) != set(_LOCAL_CHECK_KEYS):
        return None
    result: dict[str, str] = {}
    for key in _LOCAL_CHECK_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or value not in _LOCAL_STATE_VOCABULARY[key]:
            return None
        result[key] = value
    return result


def read_local_diagnostics(environ: Mapping[str, str]) -> dict[str, Any] | None:
    """Read the Connector's local diagnostics, or ``None``.

    A missing file, an unreadable file, a foreign version or an unusable
    label set is ``None``. The Resident then reports no hint at all, and the
    server shows "확인 불가" rather than a fabricated state.
    """
    value = environ.get(LOCAL_DIAGNOSTICS_FILE_ENV)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        path = Path(value).expanduser()
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
    canonical = normalize_diagnostics(checks)
    if canonical is None:
        return None
    return {
        "version": PC_DEVICE_DIAGNOSTICS_VERSION,
        "revision": _bounded_revision(raw.get("revision")),
        "checks": canonical,
    }


def diagnostics_hint(diagnostics: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The bounded hint the heartbeat carries, or ``None``.

    Only the three closed labels and the revision travel. Nothing else from
    the local file is ever put on the wire.
    """
    if not isinstance(diagnostics, Mapping):
        return None
    if diagnostics.get("version") != PC_DEVICE_DIAGNOSTICS_VERSION:
        return None
    revision = diagnostics.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        # A hint without a usable revision cannot be ordered against the
        # stored one, so it is not reported at all.
        return None
    checks = diagnostics.get("checks")
    canonical = normalize_diagnostics(checks)
    if canonical is None:
        return None
    return {
        "version": PC_DEVICE_DIAGNOSTICS_VERSION,
        "revision": _bounded_revision(revision),
        "checks": {key: canonical[key] for key in DIAGNOSTIC_KEYS},
    }


__all__ = [
    "LOCAL_DIAGNOSTICS_FILE_ENV",
    "LOCAL_DIAGNOSTICS_VERSION",
    "diagnostics_hint",
    "normalize_local_checks",
    "read_local_diagnostics",
]
