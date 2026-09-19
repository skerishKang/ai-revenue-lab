#!/usr/bin/env python3
"""B62 live-content #2124 and #2544 marker probe (B62/B14 #2548, #2553).

READ-ONLY. Inspects the CURRENT served padiem-chat script content, fetched
GET-only by the dispatcher workflow into runner temp, and reports whether
the unique #2124 adapter-fix markers and the #2544 completed-timeout contract
markers are present in memory.

TOCTOU closure (CENTRAL blocker 2, review 5676011767): /content/v2 serves
the CURRENT script and is not version-id-pinned, so the workflow reads
deployments BEFORE and IMMEDIATELY AFTER the content fetch and passes both
payloads here. A marker verdict is computed only when both reads resolve to
exactly one 100%-served version equal to the expected active version AND the
two payloads are deep-equal (no drift, no shape change). The optional
post-content version detail must still carry a script identity.

This module performs zero network I/O and never prints, logs, or persists
any raw script content, any marker-adjacent text, any offsets, any script
etag/hash value, or any author_email/author_id metadata.

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
    MARKER_COMPLETED_TIMEOUT_DEFAULT_50=PRESENT|ABSENT
    MARKER_COMPLETED_TIMEOUT_BINDING_FALLBACK_50=PRESENT|ABSENT
    MARKER_SHARED_TIMEOUT_DEFAULT_20=PRESENT|ABSENT
    MARKER_COMPLETION_CONFIG_WIRING=PRESENT|ABSENT
    MARKER_COMPLETION_TRANSPORT_WIRING=PRESENT|ABSENT
    MARKER_STREAMING_CLIENT_PRESENT=PRESENT|ABSENT
    MARKER_STREAMING_USES_DEFAULT_CONFIG=PRESENT|ABSENT
    COMPLETED_TIMEOUT_LIVE_MARKERS=PASS|INCONCLUSIVE
    VERSION_METADATA_SOURCE=<closed Cloudflare VersionGetResponse enum or UNKNOWN>
    SCRIPT_LAST_DEPLOYED_FROM=<bounded token or UNKNOWN>
    RAW_SCRIPT_CONTENT_OUTPUT=0
    RAW_SCRIPT_ETAG_OUTPUT=0
    SECRET_VALUE_OUTPUT=0
    PRODUCTION_MUTATION=0

PASS requires every required marker present. ABSENT yields INCONCLUSIVE,
never a "fix absent" verdict, because packaging/minification may transform
source text. PR2124_LIVE_MARKERS and COMPLETED_TIMEOUT_LIVE_MARKERS are
independent verdicts: each is PASS only when its own full marker family is
present and INCONCLUSIVE otherwise. Structural violations (active version
drift, pre/post mismatch, missing script identity, empty or oversized
content) fail closed with a non-zero exit and a reason string that never
contains any payload value.
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

# Closed documented Cloudflare VersionGetResponse metadata.source enum.
CLOUDFLARE_SOURCE_ENUM = frozenset({
    "unknown",
    "api",
    "wrangler",
    "terraform",
    "dash",
    "cf_cli",
    "dash_template",
    "integration",
    "quick_editor",
    "playground",
    "workersci",
})

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

# Exact #2544 completed-timeout production-source markers. Together they prove
# the separated 50s completed / 20s shared-stream contract and the completed-
# path wiring are present in the served script, while the streaming path still
# uses the ordinary default config. Matched as raw bytes in memory only; never
# echoed back.
COMPLETED_TIMEOUT_MARKERS: dict[str, bytes] = {
    "MARKER_COMPLETED_TIMEOUT_DEFAULT_50": b"completed_timeout_seconds: float = 50.0",
    "MARKER_COMPLETED_TIMEOUT_BINDING_FALLBACK_50": (
        b'binding_value(env, "PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS") or "50"'
    ),
    "MARKER_SHARED_TIMEOUT_DEFAULT_20": b"timeout_seconds: float = 20.0",
    "MARKER_COMPLETION_CONFIG_WIRING": (
        b"return self._config(self.settings.completed_timeout_seconds)"
    ),
    "MARKER_COMPLETION_TRANSPORT_WIRING": (
        b"timeout_seconds=self.settings.completed_timeout_seconds"
    ),
    "MARKER_STREAMING_CLIENT_PRESENT": b"B14StreamingClient(",
    "MARKER_STREAMING_USES_DEFAULT_CONFIG": b"self._config(),",
}

COMPLETED_TIMEOUT_MARKER_KEYS = tuple(COMPLETED_TIMEOUT_MARKERS)


class LiveContentError(RuntimeError):
    pass


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


def resolve_active_version(deployments_payload: object, label: str) -> str:
    """Extract the single 100%-traffic served version id, fail closed.

    The Cloudflare deployments endpoint returns deployment history and
    documents that the first entry is the latest deployment actively
    serving traffic (same semantics as b62_served_version_secret_guard),
    so later entries are previous deployments and are not ambiguity.
    """
    if not isinstance(deployments_payload, dict):
        raise LiveContentError(f"{label} deployments payload must be a JSON object")
    if deployments_payload.get("success") is not True:
        raise LiveContentError(f"{label} deployments response was not successful")
    result = deployments_payload.get("result")
    if not isinstance(result, dict):
        raise LiveContentError(f"{label} deployments result is missing")
    deployments = result.get("deployments")
    if not isinstance(deployments, list) or len(deployments) == 0:
        raise LiveContentError(f"{label} deployments returned no records")
    versions = deployments[0].get("versions") if isinstance(deployments[0], dict) else None
    if not isinstance(versions, list) or len(versions) != 1:
        raise LiveContentError(f"{label} expected exactly one served version")
    entry = versions[0]
    if not isinstance(entry, dict):
        raise LiveContentError(f"{label} served version entry is malformed")
    if entry.get("percentage") != 100:
        raise LiveContentError(f"{label} served version traffic share is not exactly 100")
    version_id = entry.get("version_id")
    if not _is_uuid(version_id):
        raise LiveContentError(f"{label} served version id is missing or malformed")
    return str(version_id)


def require_script_identity(version_detail_payload: object, label: str) -> dict[str, Any]:
    """Verify the version-detail script identity exists; return its result.

    The etag value is checked in memory only and never returned or printed.
    """
    if not isinstance(version_detail_payload, dict):
        raise LiveContentError(f"{label} version detail must be a JSON object")
    if version_detail_payload.get("success") is not True:
        raise LiveContentError(f"{label} version detail response was not successful")
    result = version_detail_payload.get("result")
    if not isinstance(result, dict):
        raise LiveContentError(f"{label} version detail result is missing")
    resources = result.get("resources")
    if not isinstance(resources, dict):
        raise LiveContentError(f"{label} version detail resources are missing")
    script = resources.get("script")
    if not isinstance(script, dict):
        raise LiveContentError(f"{label} script resource identity is missing")
    etag = script.get("etag")
    if not isinstance(etag, str) or not etag.strip():
        raise LiveContentError(f"{label} script identity etag is missing or empty")
    return result


def extract_version_metadata_source(version_result: dict[str, Any]) -> str:
    """Return result.metadata.source when it is a closed enum value, else UNKNOWN."""
    metadata = version_result.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("source")
        if isinstance(value, str) and value in CLOUDFLARE_SOURCE_ENUM:
            return value
    return "UNKNOWN"


def extract_last_deployed_from(version_result: dict[str, Any]) -> str:
    """Return bounded resources.script.last_deployed_from, else UNKNOWN.

    Only this whitelisted path is read; author_email/author_id metadata is
    never accessed and never emitted.
    """
    resources = version_result.get("resources")
    script = resources.get("script") if isinstance(resources, dict) else None
    value = script.get("last_deployed_from") if isinstance(script, dict) else None
    if isinstance(value, str) and BOUNDED_TOKEN_RE.match(value):
        return value
    return "UNKNOWN"


def probe_live_content(
    *,
    deployments_pre_payload: object,
    deployments_post_payload: object,
    expected_active_version: str,
    version_detail_payload: object,
    content_bytes: bytes,
    max_content_bytes: int,
    version_detail_post_payload: object | None = None,
) -> dict[str, str]:
    """Compute the closed-vocabulary live-content marker verdict silently."""
    if not _is_uuid(expected_active_version):
        raise LiveContentError("expected active version must be an exact lowercase UUID")
    if not isinstance(max_content_bytes, int) or max_content_bytes <= 0:
        raise LiveContentError("max content bytes must be a positive integer")

    active_pre = resolve_active_version(deployments_pre_payload, "pre-content")
    if active_pre != expected_active_version:
        raise LiveContentError("pre-content active version drifted from the expected active version")
    active_post = resolve_active_version(deployments_post_payload, "post-content")
    if active_post != expected_active_version:
        raise LiveContentError("post-content active version drifted from the expected active version")
    if deployments_pre_payload != deployments_post_payload:
        raise LiveContentError("deployments drifted or changed shape around the content fetch")

    version_result = require_script_identity(version_detail_payload, "pre-content")
    if version_detail_post_payload is not None:
        require_script_identity(version_detail_post_payload, "post-content")

    if not isinstance(content_bytes, bytes):
        raise LiveContentError("served content must be read as raw bytes")
    if len(content_bytes) == 0:
        raise LiveContentError("served content is empty")
    if len(content_bytes) > max_content_bytes:
        raise LiveContentError("served content exceeds the bounded size guard")

    verdict = {
        "ACTIVE_VERSION": active_pre,
        "ACTIVE_VERSION_MATCH": "PASS",
        "SCRIPT_IDENTITY_PRESENT": "PASS",
        "LIVE_CONTENT_FETCH": "PASS",
        "LIVE_CONTENT_SIZE_BOUNDED": "PASS",
    }
    for key in MARKER_KEYS:
        verdict[key] = "PRESENT" if MARKERS[key] in content_bytes else "ABSENT"
    all_present = all(verdict[key] == "PRESENT" for key in MARKER_KEYS)
    verdict["PR2124_LIVE_MARKERS"] = "PASS" if all_present else "INCONCLUSIVE"
    for key in COMPLETED_TIMEOUT_MARKER_KEYS:
        verdict[key] = (
            "PRESENT" if COMPLETED_TIMEOUT_MARKERS[key] in content_bytes else "ABSENT"
        )
    completed_all_present = all(
        verdict[key] == "PRESENT" for key in COMPLETED_TIMEOUT_MARKER_KEYS
    )
    verdict["COMPLETED_TIMEOUT_LIVE_MARKERS"] = (
        "PASS" if completed_all_present else "INCONCLUSIVE"
    )
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
    "MARKER_COMPLETED_TIMEOUT_DEFAULT_50",
    "MARKER_COMPLETED_TIMEOUT_BINDING_FALLBACK_50",
    "MARKER_SHARED_TIMEOUT_DEFAULT_20",
    "MARKER_COMPLETION_CONFIG_WIRING",
    "MARKER_COMPLETION_TRANSPORT_WIRING",
    "MARKER_STREAMING_CLIENT_PRESENT",
    "MARKER_STREAMING_USES_DEFAULT_CONFIG",
    "COMPLETED_TIMEOUT_LIVE_MARKERS",
    "VERSION_METADATA_SOURCE",
    "SCRIPT_LAST_DEPLOYED_FROM",
)


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployments-pre", type=Path, required=True)
    parser.add_argument("--deployments-post", type=Path, required=True)
    parser.add_argument("--expected-active-version", required=True)
    parser.add_argument("--version-detail", type=Path, required=True)
    parser.add_argument("--version-detail-post", type=Path)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--max-content-bytes", type=int, required=True)
    args = parser.parse_args(args_in)

    try:
        deployments_pre = _load_json(args.deployments_pre, "pre-content deployments")
        deployments_post = _load_json(args.deployments_post, "post-content deployments")
        version_detail = _load_json(args.version_detail, "pre-content version detail")
        version_detail_post = (
            _load_json(args.version_detail_post, "post-content version detail")
            if args.version_detail_post is not None
            else None
        )
        content_bytes = _load_content(args.content)
        verdict = probe_live_content(
            deployments_pre_payload=deployments_pre,
            deployments_post_payload=deployments_post,
            expected_active_version=args.expected_active_version,
            version_detail_payload=version_detail,
            version_detail_post_payload=version_detail_post,
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
