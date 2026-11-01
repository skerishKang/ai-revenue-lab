"""Connector client-version compatibility judgment (connector 0.3.0-rc1 rollout prep).

The one question this module answers
------------------------------------
Given the ``client_version`` a PC reports and the server-configured version
thresholds, which ``DeviceCompatibility`` value (``kagent.connections_center``)
does that PC deserve? This is a *display* judgment only: nothing here blocks a
device, refuses a session, or changes any lifecycle authority. The single
producer of ``update_required`` lifecycle states is still out of scope, and
``PADIEM_CONNECTOR_MIN_VERSION`` is only enabled by an explicit owner decision.

Version grammar and ordering (the rules, stated once)
-----------------------------------------------------
1. Grammar: ``MAJOR.MINOR.PATCH`` with an optional ``-rc<N>`` pre-release
   suffix (``N`` is a decimal run of 1-9 digits). Anything else — empty text,
   ``"unknown"``, ``"dev"``, ``"v0.3.0"``, over-length input — parses as
   ``None``, i.e. "version unknown".
2. Triples compare numerically: ``0.2.0 < 0.3.0``.
3. A release outranks every pre-release of the same triple:
   ``0.3.0-rc1 < 0.3.0``.
4. Pre-releases of the same triple compare by their numeric run:
   ``0.3.0-rc1 < 0.3.0-rc2 < 0.3.0-rc11``.
5. Judgement (in order, first match wins):
   - the reported version does not parse → ``UNKNOWN`` (today's exact
     behaviour for every device: no notice, no blocking);
   - ``latest_version`` does not parse (e.g. a mistyped env override) →
     ``UNKNOWN`` — an unusable threshold must never invent a notice;
   - a parseable ``minimum_version`` is configured and the reported version is
     below it → ``UPDATE_REQUIRED``;
   - below ``latest_version`` → ``UPDATE_AVAILABLE``;
   - otherwise (equal to or above the latest) → ``CURRENT``.
   ``UPDATE_REQUIRED`` therefore wins over ``UPDATE_AVAILABLE`` when a device
   sits below both thresholds, and an empty/absent/unparseable minimum simply
   disables the hard-minimum lane (fail-open by design: a mistyped minimum
   must never label every PC "update required").

Environment
-----------
``PADIEM_CONNECTOR_LATEST_VERSION`` — defaults to
``DEFAULT_CONNECTOR_LATEST_VERSION`` (the release this deployment prepares,
0.3.0-rc1). ``PADIEM_CONNECTOR_MIN_VERSION`` — empty by default, which keeps
``UPDATE_REQUIRED`` unreachable until the owner turns it on.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

from .connections_center import DeviceCompatibility

__all__ = [
    "CONNECTOR_LATEST_VERSION_ENV",
    "CONNECTOR_MINIMUM_VERSION_ENV",
    "DEFAULT_CONNECTOR_LATEST_VERSION",
    "MAX_VERSION_LENGTH",
    "compare_connector_versions",
    "connector_version_thresholds",
    "derive_device_compatibility",
    "parse_connector_version",
]

CONNECTOR_LATEST_VERSION_ENV = "PADIEM_CONNECTOR_LATEST_VERSION"
CONNECTOR_MINIMUM_VERSION_ENV = "PADIEM_CONNECTOR_MIN_VERSION"

#: The release this deployment prepares (#6631). Only an explicit env override
#: moves it; the default must never silently track an unparsed value.
DEFAULT_CONNECTOR_LATEST_VERSION = "0.3.0-rc1"

#: Anything longer cannot be a version this product ships; reading it as
#: "unknown" beats truncating it into a different version.
MAX_VERSION_LENGTH = 64

_VERSION_RE = re.compile(r"^(\d{1,9})\.(\d{1,9})\.(\d{1,9})(?:-rc(\d{1,9}))?$")

# Sort key over the grammar: the fourth element ranks a release (1) above any
# pre-release (0) of the same triple, so 0.3.0-rc1 < 0.3.0 without special
# cases; the fifth element is the numeric rc run.
_PreReleaseRank = 0
_ReleaseRank = 1


def parse_connector_version(value: object) -> tuple[int, int, int, int, int] | None:
    """Parse one reported version into its sort key, or ``None`` when unknown.

    ``None`` is the single honest answer for every input this grammar does not
    declare; callers treat it as "version unknown" and never as a specific
    version.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_VERSION_LENGTH:
        return None
    match = _VERSION_RE.fullmatch(text)
    if match is None:
        return None
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    rc_text = match.group(4)
    if rc_text is None:
        return (major, minor, patch, _ReleaseRank, 0)
    return (major, minor, patch, _PreReleaseRank, int(rc_text))


def compare_connector_versions(left: object, right: object) -> int | None:
    """Compare two reported versions; ``None`` when either is unknown.

    Returns ``-1`` / ``0`` / ``1`` exactly when both inputs parse, so a caller
    can distinguish "unknown" from any ordering answer.
    """

    left_key = parse_connector_version(left)
    right_key = parse_connector_version(right)
    if left_key is None or right_key is None:
        return None
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


def connector_version_thresholds(
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Read the two threshold env values, with the deployment defaults.

    Returns ``(latest_version, minimum_version)``. An unset/blank latest falls
    back to ``DEFAULT_CONNECTOR_LATEST_VERSION``; an unset/blank minimum
    returns ``None``, which keeps the ``UPDATE_REQUIRED`` lane disabled.
    Whitespace is tolerated; nothing is ever validated here — the parse rules
    decide usability at judgement time, so a mistyped override fails open
    (no notice) instead of inventing one.
    """

    source: Mapping[str, str] = os.environ if env is None else env
    latest = str(source.get(CONNECTOR_LATEST_VERSION_ENV, "")).strip()
    minimum = str(source.get(CONNECTOR_MINIMUM_VERSION_ENV, "")).strip()
    return (latest or DEFAULT_CONNECTOR_LATEST_VERSION, minimum or None)


def derive_device_compatibility(
    client_version: object,
    *,
    latest_version: object,
    minimum_version: object | None = None,
) -> DeviceCompatibility:
    """The one judgement: a reported version against the two thresholds.

    The vocabulary is imported, never re-declared: the returned values are the
    ``DeviceCompatibility`` members ``kagent.connections_center`` already
    declares, so a connection-center card can carry this result as-is. An
    unknown reported version returns ``UNKNOWN`` — exactly the behaviour every
    device gets today — and never blocks anything.
    """

    parsed = parse_connector_version(client_version)
    if parsed is None:
        return DeviceCompatibility.UNKNOWN
    latest = parse_connector_version(latest_version)
    if latest is None:
        return DeviceCompatibility.UNKNOWN
    minimum = parse_connector_version(minimum_version) if minimum_version is not None else None
    if minimum is not None and parsed < minimum:
        return DeviceCompatibility.UPDATE_REQUIRED
    if parsed < latest:
        return DeviceCompatibility.UPDATE_AVAILABLE
    return DeviceCompatibility.CURRENT
