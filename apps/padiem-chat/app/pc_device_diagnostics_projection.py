"""#3099 the PC device diagnostic hint the web surface shows.

The Broker stores a bounded, display-only hint per device: the Agent source
files, the Windows autostart entry and the supervised Resident, as the
device itself observed them.

The projection here is deliberately narrow. It is **display only**:

* it never changes the canonical device state, the online projection, the
  executable flag or the selectable flag;
* it never becomes a permission, a registration proof or a credential;
* it never carries a path, a secret or a log line;
* a hint that belongs to another device is dropped, so a mixed-in device can
  never borrow another device's observation;
* a hint that was never reported, that stopped advancing, or whose read
  failed is reported as "확인 불가" - never as a confirmed negative.

The web renders the localized text; the server only ever sends the closed
state code and the fix code.
"""
from __future__ import annotations

from typing import Any, Mapping

from padiem_ai_core.pc_device_diagnostics import (
    DIAGNOSTIC_KEYS,
    diagnostic_fix,
    diagnostics_have_observation,
    normalize_diagnostics,
)

#: The three states the surface can show.
STATUS_REPORTED = "reported"
STATUS_STALE = "stale"
STATUS_UNAVAILABLE = "unavailable"

_STATUSES = (STATUS_REPORTED, STATUS_STALE, STATUS_UNAVAILABLE)


def project_device_diagnostic(
    raw: Any, *, device_id: str
) -> dict[str, Any] | None:
    """Project one stored hint for one device, or ``None``.

    ``None`` means the hint is unusable and the surface must show no
    diagnostic at all. A hint whose device id does not match the row it
    arrived with is dropped, so one device can never display another
    device's observation.
    """
    if not isinstance(raw, Mapping):
        return None
    status = raw.get("status")
    if not isinstance(status, str) or status not in _STATUSES:
        return None
    if raw.get("device_id") != device_id:
        # A hint that belongs to another device is refused outright.
        return None
    if status == STATUS_UNAVAILABLE:
        return {"status": STATUS_UNAVAILABLE, "checks": {}, "fixes": {}}
    checks = normalize_diagnostics(raw.get("checks"))
    if checks is None:
        return None
    if status == STATUS_STALE:
        # The observation stopped advancing. The values are kept out of the
        # surface: an old observation must not be shown as current.
        return {"status": STATUS_STALE, "checks": {}, "fixes": {}}
    fixes = {
        key: fix
        for key in DIAGNOSTIC_KEYS
        if (fix := diagnostic_fix(checks, key)) is not None
    }
    return {
        "status": STATUS_REPORTED,
        "checks": {key: checks[key] for key in DIAGNOSTIC_KEYS},
        "fixes": fixes,
        "observed": diagnostics_have_observation(checks),
    }


__all__ = [
    "STATUS_REPORTED",
    "STATUS_STALE",
    "STATUS_UNAVAILABLE",
    "project_device_diagnostic",
]
