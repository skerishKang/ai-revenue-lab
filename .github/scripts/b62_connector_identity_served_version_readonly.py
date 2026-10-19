#!/usr/bin/env python3
"""#4139 Canonical Identity served Worker revision lineage, GET only.

This is a negative release evidence gate. Resolve one 100% served version,
read precisely that version's metadata, then re-read the active deployment to
reject a concurrent rollout. A version identifier, script ETag, worker label,
or upload-client metadata is NOT a reproducible build/commit attestation, and
does not prove private RPC callability or authorize Connector enrollment.

No production requests to private RPC methods, raw script content, secret
values, device identifiers, binding values or Cloudflare account identifiers
are emitted. No mutation, endpoint, Worker deployment or token issuance.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from b62_cloudflare_connector_binding_readonly import API, get_json
from b62_connector_broker_served_version_readonly import (
    parse_served_version,
    compare_served_runtime_config,
    compare_served_worker_exports,
    validate_served_version_detail,
)

VERSION = "padiem.connector-identity-served-version.readonly.v1"
IDENTITY_WORKER = "padiem-control-plane-identity"
_ACCOUNT = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
_SUPPORTED_UPLOAD_SOURCES = frozenset((
    "api", "wrangler", "terraform", "dash", "cf_cli",
    "dash_template", "integration", "quick_editor", "playground",
    "workersci", "unknown",
))


def inspect_identity_version_detail(payload: object, active_id: str) -> dict[str, Any]:
    evidence = validate_served_version_detail(payload, active_id)
    # Upload provenance is indicative metadata, not proof that repository
    # files (or their SHA) equal deployed bundled Python modules.
    result = payload["result"]
    metadata = result.get("metadata")
    source = metadata.get("source") if type(metadata) is dict else None
    upload_origin_recognized = (
        type(source) is str and source in _SUPPORTED_UPLOAD_SOURCES
    )
    runtime = compare_served_runtime_config(payload, IDENTITY_WORKER)
    exports = compare_served_worker_exports(payload, IDENTITY_WORKER)
    return {
        **runtime,
        **exports,
        "served_version_detail_readable": evidence["served_version_detail_readable"],
        "served_script_etag_present": evidence["served_script_etag_present"],
        "upload_origin_recognized": upload_origin_recognized,
        "exact_git_commit_or_bundle_digest_attested": False,
        "deployed_identity_consent_rpc_proven": False,
        "identity_enrollment_authorized": False,
    }


def audit(*, account_id: str, token: str,
          requester: Callable[..., tuple[int, object]] = get_json) -> dict[str, Any]:
    if type(account_id) is not str or _ACCOUNT.fullmatch(account_id) is None:
        raise ValueError("Cloudflare audit account id invalid")
    if type(token) is not str or not token:
        raise ValueError("Cloudflare audit token unavailable")

    endpoint = f"{API}/accounts/{account_id}/workers/scripts/{IDENTITY_WORKER}"
    status, deployments = requester(endpoint + "/deployments", token=token)
    if status != 200:
        raise ValueError("Identity active deployment unavailable")
    version = parse_served_version(deployments)
    status, response = requester(endpoint + "/versions/" + version, token=token)
    if status != 200:
        raise ValueError("Identity served version unavailable")
    result = inspect_identity_version_detail(response, version)
    status, refreshed = requester(endpoint + "/deployments", token=token)
    if status != 200 or parse_served_version(refreshed) != version:
        raise ValueError("Identity deployment changed during audit")
    return {
        "contract": VERSION,
        "worker": IDENTITY_WORKER,
        **result,
        "served_version_stable_during_readback": True,
        "production_mutation": 0,
    }


def main() -> int:
    try:
        evidence = audit(
            account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
            token=os.getenv("CLOUDFLARE_API_TOKEN", ""),
        )
    except (ValueError, TypeError, OSError):
        print(json.dumps({
            "contract": VERSION,
            "status": "HOLD",
            "identity_enrollment_authorized": False,
            "production_mutation": 0,
        }, sort_keys=True))
        print("IDENTITY_SERVED_VERSION_READBACK=HOLD")
        print("PRODUCTION_MUTATION=0")
        # No green status may be mistaken for real source parity.
        return 1
    print(json.dumps(evidence, sort_keys=True))
    print("IDENTITY_SERVED_VERSION_READBACK=PASS_READONLY")
    print("IDENTITY_SOURCE_PARITY_ATTESTED=NO")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
