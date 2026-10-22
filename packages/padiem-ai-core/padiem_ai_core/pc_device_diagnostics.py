"""#3099 canonical PC device diagnostic hints (display only).

A PC can be unreachable for reasons the server cannot see: the Agent source
is not installed, Windows autostart is off, or the supervised Resident is not
running. The Connector observes all three locally. This module is the single
vocabulary for carrying that observation to the web surface.

The contract is deliberately narrow, because a client-reported value must
never become an authority:

* **Display only.** A hint is a bounded label plus the fix the user can
  apply. It is never an execution permission, a registration proof, a
  credential or an ONLINE claim.
* **Closed vocabulary.** Only the keys and values below exist. A client
  cannot smuggle an arbitrary string into the surface.
* **No secrets, no paths, no logs.** A hint carries one of a fixed set of
  labels. It never carries a file path, a credential, a token, a command
  output or a stack trace.
* **Absence is a first-class value.** A hint that was never reported, that
  is too old, or whose read failed is ``unknown`` - never "not installed" and
  never "stopped". Only an observation that actually saw the state may say
  so.
* **Freshness is the server's clock.** The server decides staleness from
  the moment it accepted the report, so a client cannot make a stale
  observation look fresh.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

#: The wire and storage version of the hint shape.
PC_DEVICE_DIAGNOSTICS_VERSION = "padiem-pc-device-diagnostics.v1"

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

_STATE_VOCABULARY: Mapping[str, tuple[str, ...]] = {
    "agent_source": AGENT_SOURCE_STATES,
    "autostart": AUTOSTART_STATES,
    "resident": RESIDENT_STATES,
}

#: The user-facing fix for each observed state. A hint without a fix is not
#: worth showing, so every confirmed state has one.
FIX_FOR_STATE: Mapping[tuple[str, str], str] = {
    ("agent_source", "not_installed"): "install_agent",
    ("agent_source", "invalid"): "repair_agent_source",
    ("autostart", "disabled"): "enable_autostart",
    ("resident", "stopped"): "start_connector",
}

#: The key that carries the fix code. The web renders the localized text; the
#: server never sends a localized string.
FIX_KEY = "fix"


def unknown_diagnostics() -> dict[str, str]:
    """The hint set for a device that reported nothing usable."""
    return {key: UNKNOWN for key in DIAGNOSTIC_KEYS}


def normalize_diagnostics(raw: Any) -> dict[str, str] | None:
    """Normalize one reported hint set, or ``None`` when it is unusable.

    A reported set is usable only when it carries every key and every value
    is in the closed vocabulary. A partial or unknown-valued set is refused
    rather than guessed, so a hint can never claim more than it observed.
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


def is_stale(reported_at: Any, *, now: float, max_age_seconds: float) -> bool:
    """True when a report is older than the accepted bound.

    ``now`` is the server's own clock. A client cannot make a stale report
    look fresh by stamping its own time.
    """
    if not isinstance(reported_at, (int, float)) or isinstance(reported_at, bool):
        return True
    if reported_at > now:
        # A report from the future is not a fresh report; it is an unusable
        # one.
        return True
    return (now - reported_at) > max_age_seconds


def sanitize_diagnostics_text(value: Any) -> str | None:
    """Accept only a short, printable, single-line label.

    This is the last line of defence for anything a device might have put in
    a label: no control characters, no newlines, no long strings, and
    nothing that could be a path.
    """
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    if "/" in value or "\\" in value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:+ -]+", value):
        return None
    return value


__all__ = [
    "AGENT_SOURCE_STATES",
    "AUTOSTART_STATES",
    "DIAGNOSTIC_KEYS",
    "FIX_FOR_STATE",
    "FIX_KEY",
    "PC_DEVICE_DIAGNOSTICS_VERSION",
    "RESIDENT_STATES",
    "UNKNOWN",
    "diagnostic_fix",
    "diagnostics_have_observation",
    "is_stale",
    "normalize_diagnostics",
    "sanitize_diagnostics_text",
    "unknown_diagnostics",
]
