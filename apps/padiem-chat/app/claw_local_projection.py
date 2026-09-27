"""#3094 — canonical server device state to Web lifecycle vocabulary (G4).

Why this module exists
----------------------
``static/claw-local-handoff.js`` (#3084) presents exactly five Web lifecycle
states (``PAIRING`` / ``CONNECTED`` / ``OFFLINE`` / ``REVOKED`` /
``ACTION_REQUIRED``), while the device lifecycle the server actually owns is
the six-valued ``kagent.local_agent_pairing.DeviceLifecycle`` (#3080 owns the
``ONLINE`` fact). Something has to translate between the two, and #3094 requires
that translation to live in exactly one place. That place is this module.

Authority boundary
------------------
* The canonical vocabulary is *imported, never re-declared*. The canonical
  state list is derived from ``DeviceLifecycle`` itself, so this module cannot
  become a second device-lifecycle authority.
* The Web vocabulary belongs to #3084. ``WEB_LIFECYCLE_STATES`` is a pinned
  mirror of it: a test compares the mirror against the real JS literal so a
  drift on either side fails the build instead of shipping a hidden label.
* Nothing here decides reachability, minting, admission, approval or execution.
  It is a pure rename over an already-decided server fact, and it fails closed:
  a state this translation does not recognise becomes ``ACTION_REQUIRED`` and
  is never reported usable.
* The server never sends a raw ``CONNECTED`` claim: ``usable`` is true only for
  the canonical ``online`` state, which #3080 projects from server-owned
  binding + broker session + heartbeat evidence
  (``kagent.local_agent_server_projection``). An offline, revoked, expired or
  unrecognised device can therefore never render as connected.

Contract markers
----------------
``NEW_LIFECYCLE_STATE_INTRODUCED = False``
``SECOND_DEVICE_LIFECYCLE_AUTHORITY = False``
``CANONICAL_VOCABULARY_IMPORTED_NOT_REDECLARED = True``
``UNRECOGNISED_CANONICAL_STATE_FAILS_CLOSED = True``
``OFFLINE_OR_EXPIRED_REPRESENTED_AS_CONNECTED = False``
``HANDOFF_VALUE_MINTED_OR_PARSED = False``
``PAIRING_AUTHORITY_IN_WEB_UI = "NO"``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from kagent.local_agent_pairing import DeviceLifecycle

__all__ = [
    "WEB_HANDOFF_CONTRACT_VERSION",
    "WEB_STATE_VOCABULARY_OWNER",
    "WEB_LIFECYCLE_STATES",
    "WEB_PRESENTATION_VARIANTS",
    "CANONICAL_DEVICE_STATES",
    "MAX_HANDOFF_VALUE_LENGTH",
    "canonical_device_states",
    "web_lifecycle_states",
    "web_state_for_canonical_state",
    "translate_device_lifecycle",
    "handoff_projection",
]

# The Web panel contract declared by #3084 and consumed by the presentation
# layer. It is echoed in the route response so the two sides can prove they
# still speak the same contract.
WEB_HANDOFF_CONTRACT_VERSION = "b62-claw-local-handoff/1"

# Single owner of the Web lifecycle vocabulary. This module mirrors it; it does
# not extend it.
WEB_STATE_VOCABULARY_OWNER = "apps/padiem-chat/static/claw-local-handoff.js"

WEB_STATE_PAIRING = "PAIRING"
WEB_STATE_CONNECTED = "CONNECTED"
WEB_STATE_OFFLINE = "OFFLINE"
WEB_STATE_REVOKED = "REVOKED"
WEB_STATE_ACTION_REQUIRED = "ACTION_REQUIRED"

# Declared in the same order as `CANONICAL_DEVICE_STATES` in the Web module.
WEB_LIFECYCLE_STATES: tuple[str, ...] = (
    WEB_STATE_PAIRING,
    WEB_STATE_CONNECTED,
    WEB_STATE_OFFLINE,
    WEB_STATE_REVOKED,
    WEB_STATE_ACTION_REQUIRED,
)

# Presentation-only variants the Web module may render. Kept as a mirror so the
# cross-contract test can prove this translation never invents one.
WEB_PRESENTATION_VARIANTS: tuple[str, ...] = ("UPDATE_REQUIRED",)

SAFE_FALLBACK_WEB_STATE = WEB_STATE_ACTION_REQUIRED

# Same bound the Web envelope applies to a handoff value. A longer value is not
# a handoff, so it is dropped rather than truncated.
MAX_HANDOFF_VALUE_LENGTH = 512


def canonical_device_states() -> tuple[str, ...]:
    """The canonical lifecycle vocabulary, read from its one owner."""

    return tuple(member.value for member in DeviceLifecycle)


# The complete canonical -> Web translation. Keyed by the canonical values
# themselves, not by strings typed in here, so a renamed canonical member is a
# build failure rather than a silent fallthrough.
_CANONICAL_TO_WEB_STATE: Mapping[str, str] = MappingProxyType(
    {
        DeviceLifecycle.UNPAIRED.value: WEB_STATE_PAIRING,
        DeviceLifecycle.PAIRED_OFFLINE.value: WEB_STATE_OFFLINE,
        DeviceLifecycle.ONLINE.value: WEB_STATE_CONNECTED,
        DeviceLifecycle.REVOKED.value: WEB_STATE_REVOKED,
        DeviceLifecycle.CREDENTIAL_EXPIRED.value: WEB_STATE_ACTION_REQUIRED,
        DeviceLifecycle.UPDATE_REQUIRED.value: WEB_STATE_ACTION_REQUIRED,
    }
)

# Canonical states that legitimately carry the "expired"/"revoked" flags the Web
# projection uses to keep a stale device from looking usable.
_EXPIRED_BEARING_CANONICAL_STATES = frozenset({DeviceLifecycle.CREDENTIAL_EXPIRED.value})
_REVOKED_BEARING_CANONICAL_STATES = frozenset({DeviceLifecycle.REVOKED.value})


def _assert_total_translation(translation: Mapping[str, str]) -> None:
    """Fail at import when the canonical enum and this table stop agreeing."""

    canonical = set(canonical_device_states())
    translated = set(translation)
    unmapped = sorted(canonical - translated)
    invented = sorted(translated - canonical)
    if unmapped or invented:
        raise RuntimeError(
            "#3094 device-state translation is out of step with "
            f"kagent.local_agent_pairing.DeviceLifecycle: unmapped={unmapped} "
            f"not_in_canonical_vocabulary={invented}"
        )
    for web_state in translation.values():
        if web_state not in WEB_LIFECYCLE_STATES:
            raise RuntimeError(f"#3094 maps to a Web state #3084 does not declare: {web_state}")


_assert_total_translation(_CANONICAL_TO_WEB_STATE)

CANONICAL_DEVICE_STATES: tuple[str, ...] = canonical_device_states()


def web_lifecycle_states() -> tuple[str, ...]:
    """The Web vocabulary this translation is allowed to emit (mirror of #3084)."""

    return WEB_LIFECYCLE_STATES


def _clean_label(value: object, maximum: int) -> str | None:
    """Bound a presentation label. Labels are truncated; handoff values never are."""

    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:maximum] if len(trimmed) > maximum else trimmed


def _canonicalize(state: object) -> str | None:
    """Read one canonical state value, or ``None`` when it is not canonical."""

    if isinstance(state, DeviceLifecycle):
        return state.value
    if isinstance(state, str):
        candidate = state.strip().lower()
        if candidate in _CANONICAL_TO_WEB_STATE:
            return candidate
    return None


def web_state_for_canonical_state(state: object) -> str:
    """The Web label for one canonical state; anything unknown fails closed."""

    canonical = _canonicalize(state)
    return _CANONICAL_TO_WEB_STATE[canonical] if canonical else SAFE_FALLBACK_WEB_STATE


def translate_device_lifecycle(
    state: object,
    *,
    device_name: object = None,
    platform: object = None,
) -> dict[str, Any]:
    """Translate one canonical device state into the #3084 Web device shape.

    The returned shape is exactly what ``normalizeDeviceProjection`` reads, and
    it is re-validated by that function on the way in: this translation is a
    naming bridge, never a way to bypass the Web module's own fail-closed rules.

    ``usable`` is true only for canonical ``online``, which #3080 projects from
    server-owned binding, broker session and heartbeat evidence. ``variant`` is
    deliberately never claimed: an ``update_required`` device is not a usable
    connected device, so it presents as ``ACTION_REQUIRED`` rather than dressing
    a not-usable device up as merely needing an update.
    """

    canonical = _canonicalize(state)
    web_state = _CANONICAL_TO_WEB_STATE[canonical] if canonical else SAFE_FALLBACK_WEB_STATE
    return {
        "state": web_state,
        "usable": canonical == DeviceLifecycle.ONLINE.value,
        "expired": canonical in _EXPIRED_BEARING_CANONICAL_STATES,
        "revoked": canonical in _REVOKED_BEARING_CANONICAL_STATES,
        "variant": None,
        "deviceName": _clean_label(device_name, 80),
        "platform": _clean_label(platform, 40),
        # Evidence-only fields. They exist so the cross-contract test and support
        # can see what the server actually knew; they are never user-facing copy.
        "canonicalState": canonical,
        "unrecognised": canonical is None,
        "reason": f"canonical_{canonical}" if canonical else "unrecognised_canonical_state",
    }


def _absent_handoff(reason: str) -> dict[str, Any]:
    """A handoff that is honestly not offered.

    The ``value`` key is omitted rather than set to ``None`` because the Web
    envelope distinguishes "no handoff was offered" (``absent``) from "a
    malformed handoff arrived" (``malformed``); inventing a value would be worse
    than offering none.
    """

    return {"kind": "deep_link", "unavailableReason": reason}


def handoff_projection(*, value: object, conversation_id: object = None) -> dict[str, Any]:
    """Shape the opaque handoff value for the Web envelope without inspecting it.

    The value is produced upstream (#3080 pairs through
    ``kagent.local_agent_pairing``; the desktop shell validates the resulting
    ``padiem://`` link in ``apps/padiem-desktop-shell/src/contract/pairing-deeplink.ts``).
    This module never mints, decodes, re-encodes, truncates, splits or parses
    one: an over-length or non-string value is dropped whole, and a valid one is
    forwarded byte-for-byte.
    """

    if not isinstance(value, str):
        return _absent_handoff("absent")
    if not value.strip():
        return _absent_handoff("empty")
    if len(value) > MAX_HANDOFF_VALUE_LENGTH:
        return _absent_handoff("too_long")

    projection: dict[str, Any] = {"kind": "deep_link", "value": value}
    correlated = _clean_label(conversation_id, 128)
    if correlated:
        projection["conversationId"] = correlated
    return projection


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

CANONICAL_STATE_COUNT = len(CANONICAL_DEVICE_STATES)
NEW_LIFECYCLE_STATE_INTRODUCED = False
SECOND_DEVICE_LIFECYCLE_AUTHORITY = False
CANONICAL_VOCABULARY_IMPORTED_NOT_REDECLARED = True
UNRECOGNISED_CANONICAL_STATE_FAILS_CLOSED = True
OFFLINE_OR_EXPIRED_REPRESENTED_AS_CONNECTED = False
HANDOFF_VALUE_MINTED_OR_PARSED = False
HANDOFF_VALUE_FORWARDED_VERBATIM_OR_DROPPED = True
PAIRING_AUTHORITY_IN_WEB_UI = "NO"
PRODUCTION_MUTATION = False

