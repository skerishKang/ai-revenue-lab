#!/usr/bin/env python3
"""Content-blind diagnostic for the live Engine caller-authority composition.

The #2439 investigation proved the served Engine code is overlay-capable, the
custom domain reaches the Engine worker directly, and the overlay wiring and
credential source are consistent. The only surviving 401 explanations fail
inside ``identity_enforcement._build_registry_authority_from_env`` before any
caller selection: a malformed V1 base, or a base that already contains the
overlay caller id (``duplicate_service_caller``). Both map to the same
``service_authentication_failed`` response and are invisible to NAME/TYPE
read-only evidence.

This diagnostic consumes the two registry payloads in CI memory only (the
dispatched gate exports them as the same environment variables the Engine
reads) and emits exactly the approved closed facts:

    BASE_PARSE=OK|INVALID
    OVERLAY_PARSE=OK|INVALID
    BASE_CONTAINS_B54_KAGENT=YES|NO
    DUPLICATE_CALLER_ID=YES|NO
    BASE_CALLER_COUNT=<bounded integer>
    OVERLAY_CALLER_ID_MATCH=YES|NO

The parse verdicts reuse the production parsers verbatim, so they mirror the
wire behavior exactly. The positive-detection fields use a bounded structural
scan (fixed key paths, string equality against the known constant) so they
stay honest even when a strict parse fails. The scan never surfaces any
credential, credential hash, credential length, allowed app id, unrelated
caller id, raw JSON, or derived fingerprint: only the six fields and the
fixed safety markers are ever printed.

Exit codes: 0 when a classification was produced (INVALID/YES/NO results are
valid diagnostic findings), 2 on usage or internal faults. Errors are printed
as fixed strings only; exception text is never propagated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "padiem-ai-engine"))

from app.identity_enforcement import (  # noqa: E402
    CALLER_REGISTRY_V1_ENV,
    CALLER_REGISTRY_V1_OVERLAY_ENV,
    parse_caller_registry_v1,
    parse_caller_registry_v1_overlay,
)
from app.service_identity import MAX_ENGINE_CALLERS  # noqa: E402

# The single overlay caller this diagnostic exists to classify. This identifier
# is already public repository constant material (P01 contract, #2375/#2402).
EXPECTED_OVERLAY_CALLER_ID = "b54-kagent"

STATUS_MARKERS = (
    ("B54_ENGINE_AUTHORITY_CONTENTBLIND", ("PASS",)),
    ("SECRET_VALUE_OUTPUT", ("0",)),
    ("RAW_REGISTRY_JSON_OUTPUT", ("0",)),
    ("CLOUDFLARE_MUTATION", ("0",)),
    ("PRODUCTION_MUTATION", ("0",)),
)

CLOSED_FIELDS = (
    "BASE_PARSE",
    "OVERLAY_PARSE",
    "BASE_CONTAINS_B54_KAGENT",
    "DUPLICATE_CALLER_ID",
    "BASE_CALLER_COUNT",
    "OVERLAY_CALLER_ID_MATCH",
)


def _parse_verdict(raw: str | None, parser: object) -> str:
    """Mirror the production fail-closed parse: OK only if it fully validates."""
    if not isinstance(raw, str) or not raw.strip():
        return "INVALID"
    try:
        parser(raw)  # type: ignore[operator]
    except Exception:
        # ServiceIdentityError carries static messages, but no exception text
        # is ever allowed near the output channel, so it is dropped entirely.
        return "INVALID"
    return "OK"


def _structural_base_caller_ids(raw: str | None) -> list[str]:
    """Caller ids under the fixed V1 key path, without any validation.

    Returns an empty list on any structural deviation. Bounded work: at most
    ``2 * MAX_ENGINE_CALLERS`` entries are ever touched. Ids are used for
    equality checks in memory only and are never emitted.
    """
    ids = _structural_ids(raw, container_key="callers", many=True)
    return ids


def _structural_overlay_caller_id(raw: str | None) -> str:
    ids = _structural_ids(raw, container_key="caller", many=False)
    return ids[0] if ids else ""


def _structural_ids(raw: str | None, container_key: str, many: bool) -> list[str]:
    if not isinstance(raw, str):
        return []
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        return []
    if not isinstance(payload, dict):
        return []
    container = payload.get(container_key)
    entries = container if many else (container if isinstance(container, dict) else None)
    if entries is None:
        return []
    if many and not isinstance(entries, list):
        return []
    candidates = entries[: 2 * MAX_ENGINE_CALLERS] if many else [entries]
    ids: list[str] = []
    for entry in candidates:
        if isinstance(entry, dict):
            caller_id = entry.get("caller_id")
            if isinstance(caller_id, str):
                ids.append(caller_id)
    return ids


def diagnose(base_raw: str | None, overlay_raw: str | None) -> dict[str, str]:
    """Produce the closed six-field classification entirely in memory."""
    base_ids = _structural_base_caller_ids(base_raw)
    overlay_id = _structural_overlay_caller_id(overlay_raw)
    return {
        "BASE_PARSE": _parse_verdict(base_raw, parse_caller_registry_v1),
        "OVERLAY_PARSE": _parse_verdict(overlay_raw, parse_caller_registry_v1_overlay),
        "BASE_CONTAINS_B54_KAGENT": (
            "YES" if EXPECTED_OVERLAY_CALLER_ID in base_ids else "NO"
        ),
        "DUPLICATE_CALLER_ID": (
            "YES" if overlay_id and overlay_id in base_ids else "NO"
        ),
        "BASE_CALLER_COUNT": str(min(len(base_ids), MAX_ENGINE_CALLERS)),
        "OVERLAY_CALLER_ID_MATCH": (
            "YES" if overlay_id == EXPECTED_OVERLAY_CALLER_ID else "NO"
        ),
    }


def render(fields: dict[str, str]) -> str:
    """Render only the approved fields and fixed safety markers."""
    lines = [f"{name}={fields[name]}" for name in CLOSED_FIELDS]
    lines.append("B54_ENGINE_AUTHORITY_CONTENTBLIND=PASS")
    lines.extend(f"{name}={value}" for name, (value,) in STATUS_MARKERS[1:])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print(
            "usage: b54_engine_caller_authority_contentblind_diagnostic.py "
            "(reads registry payloads from the Engine environment variable names)",
            file=sys.stderr,
        )
        return 2
    base_raw = os.environ.get(CALLER_REGISTRY_V1_ENV)
    overlay_raw = os.environ.get(CALLER_REGISTRY_V1_OVERLAY_ENV)
    if base_raw is None and overlay_raw is None:
        print(
            "B54_ENGINE_AUTHORITY_CONTENTBLIND=FAIL "
            "REASON=no_registry_payloads_in_environment",
            file=sys.stderr,
        )
        return 2
    try:
        fields = diagnose(base_raw, overlay_raw)
    except Exception:
        print(
            "B54_ENGINE_AUTHORITY_CONTENTBLIND=FAIL REASON=internal_fault",
            file=sys.stderr,
        )
        return 2
    print(render(fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
