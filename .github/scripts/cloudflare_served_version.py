#!/usr/bin/env python3
"""Canonical Cloudflare served-version resolver primitive.

One shape contract, shared by every repository guard that must answer "which
Worker version is actually serving traffic right now?" (#2451 P1, child #2737).

Before this module the same rules were implemented four times independently
(``b54_engine_served_version_guard``, ``b62_served_version_secret_guard``,
``b62_script_lineage_comparator``, ``b62_live_content_marker_probe``) at three
different ``version_id`` strictness levels. That divergence is what the #2419
audit counted and what #2452 converged one lane at a time; this module removes
the duplication instead of converging it lane by lane.

Canonical rules, fail-closed, with no ordering fallback:

- the input is a successful Cloudflare API envelope whose ``result`` is an
  object;
- the active deployment is ``result.deployments[0]`` -- the deployments endpoint
  returns deployment history and documents the first entry as the latest
  deployment actively serving traffic, so later entries are previous
  deployments and are not ambiguity;
- that deployment serves exactly one version, at 100 percent traffic;
- the id comes from the ``version_id`` field only, and must carry a safe
  charset.

Refused outright: a raw top-level list (the wrangler CLI shape, whose entry
order is not a documented served-version authority), a list-shaped ``result``,
and a ``result.versions`` shortcut. Each of those can resolve a stale version as
served -- a descending (newest-first) raw list makes any last-entry rule pick the
oldest deployment. A caller holding wrangler raw-list output must convert it
behind an explicitly named adapter with its own ordering contract before it
reaches this resolver; no repository caller does today.

This module owns the *rules*, not the *wording*: a failure carries a closed
``reason`` code so each guard keeps publishing its own error vocabulary, which
its own regressions and the ``b62-production-code-deploy-gate`` source contract
assert against. Consumers that need a stricter id shape than the canonical
safe-charset rule (for example "exact lowercase UUID") layer that precondition
locally on top of the returned id.

Reads nothing but the payload it is handed, emits nothing, mutates nothing.
"""

from __future__ import annotations

import re

# Served version ids are echoed into CI logs and GITHUB_ENV by the guards, so
# an id that carries whitespace, shell metacharacters or control tokens is
# refused rather than sanitized.
SERVED_VERSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# A single-version deployment that owns all traffic. Compared against the exact
# integer the deployments endpoint reports for that shape.
FULL_TRAFFIC_PERCENTAGE = 100


class ServedVersionReason:
    """Closed vocabulary of canonical served-version resolution failures.

    Stable identifiers, not prose: a guard maps each code onto the message it
    has already published to operators and to its own contract tests.
    """

    ENVELOPE = "envelope"
    RESULT_OBJECT = "result-object"
    DEPLOYMENT_RECORDS = "deployment-records"
    DEPLOYMENT_ENTRY = "deployment-entry"
    VERSION_COUNT = "version-count"
    VERSION_ENTRY = "version-entry"
    TRAFFIC = "traffic"
    VERSION_ID = "version-id"


class ServedVersionResolutionError(RuntimeError):
    """The payload does not prove exactly one canonical served version."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_safe_version_id(value: object) -> bool:
    """Return whether ``value`` is a version id safe to echo into CI output."""
    return isinstance(value, str) and bool(SERVED_VERSION_ID_RE.match(value))


def resolve_served_version_id(payload: object) -> str:
    """Return the served version id, or raise ``ServedVersionResolutionError``.

    Raises with a ``ServedVersionReason`` code for the first canonical rule the
    payload breaks. Never guesses an entry by position and never falls back to a
    looser shape.
    """
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ServedVersionResolutionError(ServedVersionReason.ENVELOPE)
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ServedVersionResolutionError(ServedVersionReason.RESULT_OBJECT)
    deployments = result.get("deployments")
    if not isinstance(deployments, list) or not deployments:
        raise ServedVersionResolutionError(ServedVersionReason.DEPLOYMENT_RECORDS)
    first = deployments[0]
    if not isinstance(first, dict):
        raise ServedVersionResolutionError(ServedVersionReason.DEPLOYMENT_ENTRY)
    versions = first.get("versions")
    if not isinstance(versions, list) or len(versions) != 1:
        raise ServedVersionResolutionError(ServedVersionReason.VERSION_COUNT)
    entry = versions[0]
    if not isinstance(entry, dict):
        raise ServedVersionResolutionError(ServedVersionReason.VERSION_ENTRY)
    if entry.get("percentage") != FULL_TRAFFIC_PERCENTAGE:
        raise ServedVersionResolutionError(ServedVersionReason.TRAFFIC)
    version_id = entry.get("version_id")
    if not is_safe_version_id(version_id):
        raise ServedVersionResolutionError(ServedVersionReason.VERSION_ID)
    return version_id
