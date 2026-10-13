#!/usr/bin/env python3
"""#4139 Cloudflare GET-only Broker State/Edge served version evidence.

No Worker code/content is fetched, no secret or binding value is logged,
no production mutation, no deploy and no inference that deployed code
matches the reviewed Python source. The version API is a *lineage locator*,
not source parity or an authorized runtime RPC test. Any incomplete
response is an explicit HOLD and cannot authorize Connector activation.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import UUID

from b62_cloudflare_connector_binding_readonly import API, get_json
from cloudflare_served_version import (
    ServedVersionResolutionError, resolve_served_version_id,
)

VERSION = "padiem.connector-broker-served-version.readonly.v1"
WORKERS = ("padiem-local-agent-broker-state", "padiem-local-agent-broker-edge")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


def _uuid(value: Any) -> bool:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def parse_served_version(payload: object) -> str:
    """Reuse the single canonical active-deployment resolver; require UUID.

    Never add a second, weaker interpretation of Cloudflare deployments.
    """
    try:
        candidate = resolve_served_version_id(payload)
    except ServedVersionResolutionError as exc:
        raise ValueError("Canonical Broker served-version resolution unavailable") from exc
    if not _uuid(candidate):
        raise ValueError("Broker served-version identifier invalid")
    return candidate


def validate_served_version_detail(payload: object, pinned_id: str) -> dict[str, bool]:
    if (not _uuid(pinned_id) or type(payload) is not dict
        or payload.get("success") is not True
        or type(payload.get("result")) is not dict
        or payload["result"].get("id") != pinned_id):
        raise ValueError("Broker served version detail is unavailable or drifted")
    result = payload["result"]
    resources = result.get("resources")
    script = resources.get("script") if type(resources) is dict else None
    # A content ETag identifies stored script bytes but cannot attest those
    # bytes are equal to the reviewed repository source or callable RPC.
    etag_present = type(script) is dict and (
        type(script.get("etag")) is str and bool(script["etag"])
    )
    return {
        "served_version_detail_readable": True,
        "served_script_etag_present": etag_present,
        "reviewed_source_parity_attested": False,
        "authenticated_broker_rpc_proven": False,
    }


def audit(*, account_id: str, token: str, requester=get_json) -> dict[str, object]:
    if (not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", account_id)
        or type(token) is not str or not token):
        raise ValueError("Cloudflare audit credentials unavailable")
    results = []
    for worker in WORKERS:
        base = f"{API}/accounts/{account_id}/workers/scripts/{worker}"
        code, deployments = requester(base + "/deployments", token=token)
        if code != 200:
            raise ValueError("Canonical Broker deployment not readable")
        pinned_id = parse_served_version(deployments)
        code, detail = requester(base + "/versions/" + pinned_id, token=token)
        if code != 200:
            raise ValueError("Canonical Broker version not readable")
        evidence = validate_served_version_detail(detail, pinned_id)
        # Deployment may advance between separate GET requests. Refuse a
        # point-in-time claim until the same served id survives a second GET.
        # This does not prove source parity or guarantee future immutability.
        confirm_code, confirm_deployments = requester(base + "/deployments", token=token)
        if confirm_code != 200 or parse_served_version(confirm_deployments) != pinned_id:
            raise ValueError("Broker served deployment drifted during readback")
        results.append({
            "worker": worker, **evidence,
            "served_version_stable_during_readback": True,
        })
    return {
        "contract": VERSION,
        "served_worker_count": len(results),
        "workers": results,
        "deployed_source_parity_proven": False,
        "tls_peer_proven": False,
        "production_rpc_release_authorized": False,
        "production_mutation": 0,
    }


def main() -> int:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    try:
        info = audit(account_id=account_id, token=token)
    except (ValueError, TypeError, OSError):
        # This optional read-only audit MUST NOT disable unrelated live B62.
        # HOLD never becomes an authorization for PADIEM Connector.
        print(json.dumps({"contract": VERSION, "status": "HOLD",
                          "deployed_source_parity_proven": False,
                          "production_rpc_release_authorized": False,
                          "production_mutation": 0}, sort_keys=True))
        print("BROKER_SERVED_VERSION_READBACK=HOLD")
        return 0
    print(json.dumps(info, sort_keys=True))
    print("BROKER_SERVED_VERSION_READBACK=PASS_READONLY")
    print("BROKER_RPC_RELEASE_AUTHORIZED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
