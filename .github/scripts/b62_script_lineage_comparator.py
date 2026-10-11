#!/usr/bin/env python3
"""B62 served-version script identity lineage comparator (B62/B14 #2541).

READ-ONLY. Compares the Cloudflare version-detail script identity of the
currently active padiem-chat version against the last proven #2124-bearing
served version, without ever exposing the underlying etag/hash value.

This module performs zero network I/O: the dispatcher workflow writes
GET-only API responses to runner temp files and passes the paths here.

Closed output vocabulary (version UUIDs are non-secret operational ids;
script etags/hashes are never printed, logged, or artifacted):

    ACTIVE_VERSION=<uuid>
    EXPECTED_ACTIVE_VERSION_MATCH=PASS|FAIL
    ACTIVE_SCRIPT_IDENTITY_PRESENT=PASS|FAIL
    REFERENCE_SCRIPT_IDENTITY_PRESENT=PASS|FAIL
    SCRIPT_IDENTITY_EQUAL=YES|NO
    INTERMEDIATE_SCRIPT_IDENTITY_EQUAL=YES|NO|NOT_CHECKED
    B62_SCRIPT_LINEAGE=MATCH|MISMATCH
    RAW_SCRIPT_ETAG_OUTPUT=0
    RAW_VERSION_DETAIL_OUTPUT=0
    SECRET_VALUE_OUTPUT=0
    PRODUCTION_MUTATION=0

Structural violations (ambiguous deployment, non-100% traffic, active
version drift, missing script identity) fail closed with a non-zero exit
and a reason string that never contains any etag or payload value.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# The scripts directory is not a package, so make the canonical resolver
# importable whether this comparator runs directly or is loaded through
# importlib in a test.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cloudflare_served_version import (  # noqa: E402
    ServedVersionReason,
    ServedVersionResolutionError,
    resolve_served_version_id as _resolve_canonical_served_version_id,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class LineageError(RuntimeError):
    pass


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def require_uuid(value: str, label: str) -> str:
    if not _is_uuid(value):
        raise LineageError(f"{label} must be an exact lowercase version UUID")
    return value


# Canonical resolver failure codes published under this comparator's own
# wording. The deployments shape rules live in cloudflare_served_version.py.
_RESOLVER_REASONS = {
    ServedVersionReason.ENVELOPE: "deployments response was not successful",
    ServedVersionReason.RESULT_OBJECT: "deployments result is missing",
    ServedVersionReason.DEPLOYMENT_RECORDS: "no deployment records returned",
    ServedVersionReason.DEPLOYMENT_ENTRY: "expected exactly one served version",
    ServedVersionReason.VERSION_COUNT: "expected exactly one served version",
    ServedVersionReason.VERSION_ENTRY: "served version entry is malformed",
    ServedVersionReason.TRAFFIC: "served version traffic share is not exactly 100",
    ServedVersionReason.VERSION_ID: "served version id is missing or malformed",
}


def resolve_active_version(deployments_payload: object) -> str:
    """Extract the single 100%-traffic served version id, fail closed.

    The canonical deployments envelope contract is shared through
    cloudflare_served_version.py: the endpoint returns deployment history and
    documents the first entry as the latest deployment actively serving traffic
    (same semantics as b62_served_version_secret_guard), so later entries are
    previous deployments and are not ambiguity.

    This comparator then applies its own stricter precondition on the resolved
    id: lineage evidence is only meaningful for an exact lowercase version UUID,
    which is narrower than the canonical safe-charset rule.
    """
    try:
        version_id = _resolve_canonical_served_version_id(deployments_payload)
    except ServedVersionResolutionError as exc:
        raise LineageError(
            _RESOLVER_REASONS.get(
                exc.reason, "deployments payload is not a canonical envelope"
            )
        ) from exc
    if not _is_uuid(version_id):
        raise LineageError("served version id is missing or malformed")
    return version_id


def extract_script_identity(version_detail_payload: object, label: str) -> str:
    """Return the script etag for in-memory comparison only.

    The returned value must never be printed or persisted. Missing or
    malformed script identity fails closed with a value-free reason.
    """
    if not isinstance(version_detail_payload, dict):
        raise LineageError(f"{label} version detail must be a JSON object")
    if version_detail_payload.get("success") is not True:
        raise LineageError(f"{label} version detail response was not successful")
    result = version_detail_payload.get("result")
    if not isinstance(result, dict):
        raise LineageError(f"{label} version detail result is missing")
    resources = result.get("resources")
    if not isinstance(resources, dict):
        raise LineageError(f"{label} version detail resources are missing")
    script = resources.get("script")
    if not isinstance(script, dict):
        raise LineageError(f"{label} script resource identity is missing")
    etag = script.get("etag")
    if not isinstance(etag, str) or not etag.strip():
        raise LineageError(f"{label} script identity etag is missing or empty")
    return etag


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LineageError(f"{label} file could not be read") from exc
    except json.JSONDecodeError as exc:
        raise LineageError(f"{label} file is not valid JSON") from exc


def compare_lineage(
    *,
    deployments_payload: object,
    expected_active_version: str,
    active_detail_payload: object,
    reference_detail_payload: object,
    intermediate_detail_payload: object | None = None,
) -> dict[str, str]:
    """Compute the closed-vocabulary lineage verdict without emitting values."""
    require_uuid(expected_active_version, "expected active version")
    active = resolve_active_version(deployments_payload)
    if active != expected_active_version:
        raise LineageError("active version drifted from the expected active version")

    active_etag = extract_script_identity(active_detail_payload, "active")
    reference_etag = extract_script_identity(reference_detail_payload, "reference")
    equal = "YES" if active_etag == reference_etag else "NO"

    if intermediate_detail_payload is None:
        intermediate_equal = "NOT_CHECKED"
    else:
        intermediate_etag = extract_script_identity(
            intermediate_detail_payload, "intermediate"
        )
        intermediate_equal = "YES" if active_etag == intermediate_etag else "NO"

    return {
        "ACTIVE_VERSION": active,
        "EXPECTED_ACTIVE_VERSION_MATCH": "PASS",
        "ACTIVE_SCRIPT_IDENTITY_PRESENT": "PASS",
        "REFERENCE_SCRIPT_IDENTITY_PRESENT": "PASS",
        "SCRIPT_IDENTITY_EQUAL": equal,
        "INTERMEDIATE_SCRIPT_IDENTITY_EQUAL": intermediate_equal,
        "B62_SCRIPT_LINEAGE": "MATCH" if equal == "YES" else "MISMATCH",
    }


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployments", type=Path, required=True)
    parser.add_argument("--expected-active-version", required=True)
    parser.add_argument("--active-detail", type=Path, required=True)
    parser.add_argument("--reference-detail", type=Path, required=True)
    parser.add_argument("--intermediate-detail", type=Path)
    args = parser.parse_args(args_in)

    try:
        deployments_payload = _load_json(args.deployments, "deployments")
        active_detail = _load_json(args.active_detail, "active version detail")
        reference_detail = _load_json(args.reference_detail, "reference version detail")
        intermediate_detail = (
            _load_json(args.intermediate_detail, "intermediate version detail")
            if args.intermediate_detail is not None
            else None
        )
        verdict = compare_lineage(
            deployments_payload=deployments_payload,
            expected_active_version=args.expected_active_version,
            active_detail_payload=active_detail,
            reference_detail_payload=reference_detail,
            intermediate_detail_payload=intermediate_detail,
        )
    except LineageError as exc:
        print(f"B62_SCRIPT_LINEAGE=FAIL\nREASON={exc}", file=sys.stderr)
        print("RAW_SCRIPT_ETAG_OUTPUT=0", file=sys.stderr)
        print("PRODUCTION_MUTATION=0", file=sys.stderr)
        return 1

    for key in (
        "ACTIVE_VERSION",
        "EXPECTED_ACTIVE_VERSION_MATCH",
        "ACTIVE_SCRIPT_IDENTITY_PRESENT",
        "REFERENCE_SCRIPT_IDENTITY_PRESENT",
        "SCRIPT_IDENTITY_EQUAL",
        "INTERMEDIATE_SCRIPT_IDENTITY_EQUAL",
        "B62_SCRIPT_LINEAGE",
    ):
        print(f"{key}={verdict[key]}")
    print("RAW_SCRIPT_ETAG_OUTPUT=0")
    print("RAW_VERSION_DETAIL_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
