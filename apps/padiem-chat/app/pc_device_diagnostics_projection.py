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

The vocabulary below is the canonical one. The other packages that carry the
same contract keep a local copy, because the shared package is not
guaranteed to be present in every deployment of this lane; a parity test
proves the copies are identical.
"""
from __future__ import annotations

from typing import Any, Mapping

#: The three local observations the Connector can make.
DIAGNOSTIC_KEYS = ("agent_source", "autostart", "resident")

#: The observed values. ``unknown`` covers "not reported", "too old" and
#: "the read failed" - three different situations that must never be
#: reported as a confirmed negative.
AGENT_SOURCE_STATES = ("ready", "not_installed", "invalid", "unknown")
AUTOSTART_STATES = ("enabled", "disabled", "unknown")
RESIDENT_STATES = ("running", "stopped", "unknown")

#: The value every key uses when nothing was actually observed.
UNKNOWN = "unknown"

#: The three states the surface can show.
STATUS_REPORTED = "reported"
STATUS_STALE = "stale"
STATUS_UNAVAILABLE = "unavailable"

#: The user-facing fix for each observed state. A hint without a fix is not
#: worth showing, so every confirmed state has one.
FIX_FOR_STATE: Mapping[tuple[str, str], str] = {
    ("agent_source", "not_installed"): "install_agent",
    ("agent_source", "invalid"): "repair_agent_source",
    ("autostart", "disabled"): "enable_autostart",
    ("resident", "stopped"): "start_connector",
}

_STATE_VOCABULARY: Mapping[str, tuple[str, ...]] = {
    "agent_source": AGENT_SOURCE_STATES,
    "autostart": AUTOSTART_STATES,
    "resident": RESIDENT_STATES,
}

_STATUSES = (STATUS_REPORTED, STATUS_STALE, STATUS_UNAVAILABLE)


def normalize_diagnostics(raw: Any) -> dict[str, str] | None:
    """Normalize one reported hint, or ``None`` when it is unusable.

    A partial hint, an unknown label or a hint with extra keys is refused
    rather than guessed. A refused hint leaves the previous observation
    untouched, so a malformed report can never replace a good one.
    """
    if not isinstance(raw, Mapping):
        return None
    if set(raw) != set(DIAGNOSTIC_KEYS):
        return None
    result: dict[str, str] = {}
    for key in DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or value not in _STATE_VOCABULARY[key]:
            return None
        result[key] = value
    return result


def diagnostics_have_observation(hints: Mapping[str, str]) -> bool:
    """True when at least one key carries an actually observed state."""
    return any(hints.get(key) != UNKNOWN for key in DIAGNOSTIC_KEYS)


def diagnostic_fix(hints: Mapping[str, str], key: str) -> str | None:
    """The fix code for one observed key, or ``None`` when nothing is wrong."""
    state = hints.get(key)
    if not isinstance(state, str) or state == UNKNOWN:
        return None
    return FIX_FOR_STATE.get((key, state))


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
    "AGENT_SOURCE_STATES",
    "AUTOSTART_STATES",
    "DIAGNOSTIC_KEYS",
    "FIX_FOR_STATE",
    "RESIDENT_STATES",
    "STATUS_REPORTED",
    "STATUS_STALE",
    "STATUS_UNAVAILABLE",
    "UNKNOWN",
    "diagnostic_fix",
    "diagnostics_have_observation",
    "normalize_diagnostics",
    "project_device_diagnostic",
]
