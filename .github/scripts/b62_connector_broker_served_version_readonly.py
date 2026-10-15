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
from pathlib import Path
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


_RUNTIME_CONFIGS = {
    "padiem-control-plane-identity": "wrangler.identity-authority.jsonc",
    "padiem-local-agent-broker-state": "wrangler.local-agent-broker.jsonc",
    "padiem-local-agent-broker-edge": "wrangler.local-agent-broker-edge.jsonc",
}


def compare_served_runtime_config(
    payload: object, worker: str, *,
    config_dir: Path | None = None,
) -> dict[str, bool]:
    """Compare *served* version runtime metadata with reviewed wrangler config.

    This establishes at most compatibility-date/flags agreement. It DOES NOT
    establish deployed Python module identity, RPC callability, consent or a
    trustworthy Git commit. Absent/incomplete version metadata returns UNKNOWN
    (all false); mismatched metadata can never become a release authorization.
    """
    filename = _RUNTIME_CONFIGS.get(worker)
    if filename is None:
        raise ValueError("Unknown canonical Connector authority Worker")
    root = config_dir if config_dir is not None else (
        Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"
    )
    try:
        source = json.loads((root / filename).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError("Reviewed runtime source config unavailable") from exc
    if (type(source) is not dict or source.get("name") != worker
        or type(source.get("compatibility_date")) is not str
        or type(source.get("compatibility_flags")) is not list
        or not all(type(flag) is str for flag in source["compatibility_flags"])):
        raise ValueError("Reviewed runtime config structurally invalid")
    result = payload.get("result") if type(payload) is dict else None
    resources = result.get("resources") if type(result) is dict else None
    runtime = resources.get("script_runtime") if type(resources) is dict else None
    empty = {
        "served_runtime_metadata_complete": False,
        "served_runtime_configuration_matches_reviewed_source": False,
    }
    if type(runtime) is not dict:
        return empty
    date = runtime.get("compatibility_date")
    flags = runtime.get("compatibility_flags")
    if (type(date) is not str or type(flags) is not list
        or not all(type(flag) is str for flag in flags)):
        return empty
    expected_flags = source["compatibility_flags"]
    exact = (
        date == source["compatibility_date"]
        and len(flags) == len(set(flags))
        and len(expected_flags) == len(set(expected_flags))
        and set(flags) == set(expected_flags)
    )
    return {
        "served_runtime_metadata_complete": True,
        "served_runtime_configuration_matches_reviewed_source": exact,
    }


def compare_served_worker_exports(
    payload: object, worker: str, *,
    config_dir: Path | None = None,
) -> dict[str, bool]:
    """Compare explicit canonical Durable Object export declarations.

    Metadata establishes class names, export kinds and SQLite storage ONLY.
    It does not attest to source bytes, Python RPC methods, customer consent,
    authenticated callability, or permission to deploy.
    """
    filename = _RUNTIME_CONFIGS.get(worker)
    if filename is None:
        raise ValueError("Unknown canonical Connector Worker")
    root = config_dir if config_dir is not None else (
        Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"
    )
    try:
        source = json.loads((root / filename).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError("Reviewed canonical Worker export source unavailable") from exc
    expected = source.get("exports", {}) if type(source) is dict else None
    if (
        type(source) is not dict or source.get("name") != worker
        or type(expected) is not dict or not all(
            type(name) is str and type(spec) is dict
            and spec.get("type") == "durable-object"
            and spec.get("storage") == "sqlite"
            for name, spec in expected.items()
        )
    ):
        raise ValueError("Reviewed canonical Worker export source invalid")
    result = payload.get("result") if type(payload) is dict else None
    resources = result.get("resources") if type(result) is dict else None
    runtime = resources.get("script_runtime") if type(resources) is dict else None
    exports = runtime.get("exports") if type(runtime) is dict else None
    if type(exports) is not dict:
        return {
            "served_export_metadata_complete": False,
            "served_export_types_match_reviewed_source": False,
            "served_default_entrypoint_shape": "unavailable",
            "served_capitalized_entrypoint_shape": "unavailable",
            "served_canonical_do_shape": "unavailable",
            "served_do_export_count": 0,
        }

    def _entry_shape(name: str) -> str:
        item = exports.get(name)
        if type(item) is not dict:
            return "absent"
        return "worker" if item.get("type") == "worker" else "other"

    expected_classes = tuple(expected)
    if not expected_classes:
        do_shape = "not_applicable"
    else:
        # The reviewed Identity/State configs each have exactly one SQLite DO.
        # Never report unreviewed export class names or arbitrary metadata.
        if len(expected_classes) != 1:
            raise ValueError("Unexpected canonical Worker durable export cardinality")
        candidate = exports.get(expected_classes[0])
        if type(candidate) is not dict:
            do_shape = "absent"
        elif candidate.get("type") != "durable-object":
            do_shape = "other_type"
        elif candidate.get("storage") != "sqlite":
            do_shape = "other_storage"
        else:
            do_shape = "sqlite"
    do_count = sum(
        type(item) is dict and item.get("type") == "durable-object"
        for item in exports.values()
    )
    # Cloudflare does not necessarily list Python's implicit Default
    # WorkerEntrypoint in script_runtime.exports. The Wrangler 'exports'
    # config explicitly declares Durable Object classes only; compare just
    # those and keep default entrypoint observations as non-gating diagnostics.
    matched = (
        all(
            type(exports.get(name)) is dict
            and exports[name].get("type") == "durable-object"
            and exports[name].get("storage") == "sqlite"
            and exports[name].get("state", "created") == "created"
            for name in expected
        )
        and {
            name for name, spec in exports.items()
            if type(spec) is dict and spec.get("type") == "durable-object"
        } == set(expected)
        and all(
            type(spec) is dict and spec.get("state", "created") == "created"
            for spec in exports.values()
        )
    )
    return {
        "served_export_metadata_complete": True,
        "served_export_types_match_reviewed_source": bool(matched),
        "served_default_entrypoint_shape": _entry_shape("default"),
        "served_capitalized_entrypoint_shape": _entry_shape("Default"),
        "served_canonical_do_shape": do_shape,
        "served_do_export_count": do_count,
    }


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
        runtime = compare_served_runtime_config(detail, worker)
        exports = compare_served_worker_exports(detail, worker)
        # Deployment may advance between separate GET requests. Refuse a
        # point-in-time claim until the same served id survives a second GET.
        # This does not prove source parity or guarantee future immutability.
        confirm_code, confirm_deployments = requester(base + "/deployments", token=token)
        if confirm_code != 200 or parse_served_version(confirm_deployments) != pinned_id:
            raise ValueError("Broker served deployment drifted during readback")
        results.append({
            "worker": worker, **evidence, **runtime, **exports,
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
