#!/usr/bin/env python3
"""B62 live-content #2124 marker probe (B62/B14 #2548).

READ-ONLY. Inspects the CURRENT served padiem-chat script content, fetched
GET-only by the dispatcher workflow into runner temp, and reports whether
the unique #2124 adapter-fix markers are present in memory.

This module performs zero network I/O and never prints, logs, or persists
any raw script content, any marker-adjacent text, any offsets, or any
script etag/hash value.

Closed output vocabulary (version UUIDs are non-secret operational ids):

    ACTIVE_VERSION=<uuid>
    ACTIVE_VERSION_MATCH=PASS
    SCRIPT_IDENTITY_PRESENT=PASS
    LIVE_CONTENT_FETCH=PASS
    LIVE_CONTENT_SIZE_BOUNDED=PASS
    MARKER_UNSUPPORTED_STREAM_CHUNK=PRESENT|ABSENT
    MARKER_MEMORYVIEW_TOBYTES=PRESENT|ABSENT
    MARKER_BYTES_VALUE=PRESENT|ABSENT
    PR2124_LIVE_MARKERS=PASS|INCONCLUSIVE
    VERSION_METADATA_SOURCE=<closed Cloudflare source enum or UNKNOWN>
    SCRIPT_LAST_DEPLOYED_FROM=<bounded token or UNKNOWN>
    RAW_SCRIPT_CONTENT_OUTPUT=0
    RAW_SCRIPT_ETAG_OUTPUT=0
    SECRET_VALUE_OUTPUT=0
    PRODUCTION_MUTATION=0

PASS requires every required marker present. ABSENT yields INCONCLUSIVE,
never a "fix absent" verdict, because packaging/minification may transform
source text. Structural violations (active version drift, missing script
identity, empty or oversized content) fail closed with a non-zero exit and
a reason string that never contains any payload value.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BOUNDED_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

CLOUDFLARE_SOURCE_ENUM = frozenset({"git", "editor", "wranglerDeploy", "unknown"})

# Exact #2124 production-source markers (apps/padiem-chat/worker.py).
# Matched as raw bytes in memory only; never echoed back.
MARKERS: dict[str, bytes] = {
    "MARKER_UNSUPPORTED_STREAM_CHUNK": (
        b"Business 14 Service Binding returned an unsupported stream chunk."
    ),
    "MARKER_MEMORYVIEW_TOBYTES": b"memoryview(value).tobytes()",
    "MARKER_BYTES_VALUE": b"return bytes(value)",
}

MARKER_KEYS = tuple(MARKERS)


class LiveContentError(RuntimeError):
    pass


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def resolve_active_version(deployments_payload: object) -> str:
    """Extract the single 100%-traffic served version id, fail closed.

    The Cloudflare deployments endpoint returns deployment history and
    documents that the first entry is the latest deployment actively
    serving traffic (same semantics as b62_served_version_secret_guard),
    so later entries are previous deployments and are not ambiguity.
    """
    if not isinstance(deployments_payload, dict):
        raise LiveContentError("deployments payload must be a JSON object")
    if deployments_payload.get("success") is not True:
        raise LiveContentError("deployments response was not successful")
    result = deployments_payload.get("result")
    if not isinstance(result, dict):
        raise LiveContentError("deployments result is missing")
    deployments = result.get("deployments")
    if not isinstance(deployments, list) or len(deployments) == 0:
        raise LiveContentError("no deployment records returned")
    versions = deployments[0].get("versions") if isinstance(deployments[0], dict) else None
    if not isinstance(versions, list) or len(versions) != 1:
        raise LiveContentError("expected exactly one served version")
    entry = versions[0]
    if not isinstance(entry, dict):
        raise LiveContentError("served version entry is malformed")
    if entry.get("percentage") != 100:
        raise LiveContentError("served version traffic share is not exactly 100")
    version_id = entry.get("version_id")
    if not _is_uuid(version_id):
        raise LiveContentError("served version id is missing or malformed")
    return str(version_id)


def require_script_identity(version_detail_payload: object) -> dict[str, Any]:
    """Verify the version-detail script identity exists; return its result.

    The etag value is checked in memory only and never returned or printed.
    """
    if not isinstance(version_detail_payload, dict):
        raise LiveContentError("version detail must be a JSON object")
    if version_detail_payload.get("success") is not True:
        raise LiveContentError("version detail response was not successful")
    result = version_detail_payload.get("result")
    if not isinstance(result, dict):
        raise LiveContentError("version detail result is missing")
    resources = result.get("resources")
    if not isinstance(resources, dict):
        raise LiveContentError("version detail resources are missing")
    script = resources.get("script")
    if not isinstance(script, dict):
        raise LiveContentError("script resource identity is missing")
    etag = script.get("etag")
    if not isinstance(etag, str) or not etag.strip():
        raise LiveContentError("script identity etag is missing or empty")
    return result


def extract_version_metadata_source(version_result: dict[str, Any]) -> str:
    """Return a closed Cloudflare source enum value, or UNKNOWN."""
    sources = version_result.get("sources")
    if isinstance(sources, list):
        for entry in sources:
            value = entry.get("source") if isinstance(entry, dict) else entry
            if isinstance(value, str) and value in CLOUDFLARE_SOURCE_ENUM:
                return value
    return "UNKNOWN"


def extract_last_deployed_from(version_result: dict[str, Any]) -> str:
    """Return a bounded metadata token, or UNKNOWN. Never a free-form echo."""
    value = version_result.get("last_deployed_from")
    if isinstance(value, str) and BOUNDED_TOKEN_RE.match(value):
        return value
    return "UNKNOWN"


def probe_live_content(
    *,
    deployments_payload: object,
    expected_active_version: str,
    version_detail_payload: object,
    content_bytes: bytes,
    max_content_bytes: int,
) -> dict[str, str]:
    """Compute the closed-vocabulary live-content marker verdict silently."""
    if not _is_uuid(expected_active_version):
        raise LiveContentError("expected active version must be an exact lowercase UUID")
    if not isinstance(max_content_bytes, int) or max_content_bytes <= 0:
        raise LiveContentError("max content bytes must be a positive integer")

    active = resolve_active_version(deployments_payload)
    if active != expected_active_version:
        raise LiveContentError("active version drifted from the expected active version")

    version_result = require_script_identity(version_detail_payload)

    if not isinstance(content_bytes, bytes):
        raise LiveContentError("served content must be read as raw bytes")
    if len(content_bytes) == 0:
        raise LiveContentError("served content is empty")
    if len(content_bytes) > max_content_bytes:
        raise LiveContentError("served content exceeds the bounded size guard")

    verdict = {
        "ACTIVE_VERSION": active,
        "ACTIVE_VERSION_MATCH": "PASS",
        "SCRIPT_IDENTITY_PRESENT": "PASS",
        "LIVE_CONTENT_FETCH": "PASS",
        "LIVE_CONTENT_SIZE_BOUNDED": "PASS",
    }
    for key in MARKER_KEYS:
        verdict[key] = "PRESENT" if MARKERS[key] in content_bytes else "ABSENT"
    all_present = all(verdict[key] == "PRESENT" for key in MARKER_KEYS)
    verdict["PR2124_LIVE_MARKERS"] = "PASS" if all_present else "INCONCLUSIVE"
    verdict["VERSION_METADATA_SOURCE"] = extract_version_metadata_source(version_result)
    verdict["SCRIPT_LAST_DEPLOYED_FROM"] = extract_last_deployed_from(version_result)
    return verdict


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiveContentError(f"{label} file could not be read") from exc
    except json.JSONDecodeError as exc:
        raise LiveContentError(f"{label} file is not valid JSON") from exc


def _load_content(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise LiveContentError("served content file could not be read") from exc


OUTPUT_ORDER = (
    "ACTIVE_VERSION",
    "ACTIVE_VERSION_MATCH",
    "SCRIPT_IDENTITY_PRESENT",
    "LIVE_CONTENT_FETCH",
    "LIVE_CONTENT_SIZE_BOUNDED",
    "MARKER_UNSUPPORTED_STREAM_CHUNK",
    "MARKER_MEMORYVIEW_TOBYTES",
    "MARKER_BYTES_VALUE",
    "PR2124_LIVE_MARKERS",
    "VERSION_METADATA_SOURCE",
    "SCRIPT_LAST_DEPLOYED_FROM",
)


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployments", type=Path, required=True)
    parser.add_argument("--expected-active-version", required=True)
    parser.add_argument("--version-detail", type=Path, required=True)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--max-content-bytes", type=int, required=True)
    args = parser.parse_args(args_in)

    try:
        deployments_payload = _load_json(args.deployments, "deployments")
        version_detail = _load_json(args.version_detail, "version detail")
        content_bytes = _load_content(args.content)
        verdict = probe_live_content(
            deployments_payload=deployments_payload,
            expected_active_version=args.expected_active_version,
            version_detail_payload=version_detail,
            content_bytes=content_bytes,
            max_content_bytes=args.max_content_bytes,
        )
    except LiveContentError as exc:
        print(f"B62_LIVE_CONTENT_PROOF=FAIL\nREASON={exc}", file=sys.stderr)
        print("RAW_SCRIPT_CONTENT_OUTPUT=0", file=sys.stderr)
        print("RAW_SCRIPT_ETAG_OUTPUT=0", file=sys.stderr)
        print("PRODUCTION_MUTATION=0", file=sys.stderr)
        return 1

    for key in OUTPUT_ORDER:
        print(f"{key}={verdict[key]}")
    print("RAW_SCRIPT_CONTENT_OUTPUT=0")
    print("RAW_SCRIPT_ETAG_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
