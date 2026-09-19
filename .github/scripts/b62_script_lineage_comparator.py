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

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class LineageError(RuntimeError):
    pass


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def require_uuid(value: str, label: str) -> str:
    if not _is_uuid(value):
        raise LineageError(f"{label} must be an exact lowercase version UUID")
    return value


def resolve_active_version(deployments_payload: object) -> str:
    """Extract the single 100%-traffic served version id, fail closed.

    The Cloudflare deployments endpoint returns deployment history and
    documents that the first entry is the latest deployment actively
    serving traffic (same semantics as b62_served_version_secret_guard),
    so later entries are previous deployments and are not ambiguity.
    """
    if not isinstance(deployments_payload, dict):
        raise LineageError("deployments payload must be a JSON object")
    if deployments_payload.get("success") is not True:
        raise LineageError("deployments response was not successful")
    result = deployments_payload.get("result")
    if not isinstance(result, dict):
        raise LineageError("deployments result is missing")
    deployments = result.get("deployments")
    if not isinstance(deployments, list) or len(deployments) == 0:
        raise LineageError("no deployment records returned")
    versions = deployments[0].get("versions") if isinstance(deployments[0], dict) else None
    if not isinstance(versions, list) or len(versions) != 1:
        raise LineageError("expected exactly one served version")
    entry = versions[0]
    if not isinstance(entry, dict):
        raise LineageError("served version entry is malformed")
    if entry.get("percentage") != 100:
        raise LineageError("served version traffic share is not exactly 100")
    version_id = entry.get("version_id")
    if not _is_uuid(version_id):
        raise LineageError("served version id is missing or malformed")
    return str(version_id)


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
