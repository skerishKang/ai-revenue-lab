#!/usr/bin/env python3
"""#3782 GET-only Owner D1 release preflight; no settings PATCH, deploy or D1 writes.

Consumes immutable Worker versions, canonical deployments before AND after,
settings-plane snapshots and D1 inventory GET responses. Produces ONLY a
bounded non-secret release baseline artifact; candidate PATCH bindings remain
in memory. This is preparation evidence, NOT a pre-mutation release anchor.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from b62_binding_state_guard import (
    BindingStateError,
    assert_owner_version_integrity,
    canonical_state,
)
from cloudflare_served_version import (
    ServedVersionResolutionError,
    is_safe_version_id,
    resolve_served_version_id,
)

OWNER_NAME = "padiem-browser-owner-p01"
OWNER_BINDING = "BROWSER_CONTROL_OWNER_P01_D1"
DATABASE_NAMES = (OWNER_NAME, "padiem-chat-db", "padiem-engine")
EXPECTED_WORKERS = (
    ("padiem-ai-engine", 18),
    ("padiem-chat", 27),
)
WRITABLE_ANNOTATIONS = {"workers/message", "workers/tag"}
OBSERVED_ANNOTATIONS = WRITABLE_ANNOTATIONS | {"workers/triggered_by"}


class ReleasePreflightError(RuntimeError):
    """Public diagnostics must use bounded codes, never payload contents."""


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleasePreflightError("INPUT_UNREADABLE") from exc


def _object_result(payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ReleasePreflightError("REMOTE_ENVELOPE_INVALID")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ReleasePreflightError("REMOTE_RESULT_INVALID")
    return result


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ReleasePreflightError("D1_ID_INVALID")
    try:
        u = UUID(value)
    except ValueError as exc:
        raise ReleasePreflightError("D1_ID_INVALID") from exc
    if str(u) != value or not u.int:
        raise ReleasePreflightError("D1_ID_INVALID")
    return value


def _database_ids(inventories: dict[str, object]) -> dict[str, str]:
    ids = {}
    for name in DATABASE_NAMES:
        payload = inventories[name]
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ReleasePreflightError("D1_READ_FAILED")
        result = payload.get("result")
        if not isinstance(result, list):
            raise ReleasePreflightError("D1_LIST_SHAPE")
        exact = [row for row in result if isinstance(row, dict) and row.get("name") == name]
        if len(exact) != 1:
            raise ReleasePreflightError("D1_NOT_UNIQUE")
        ids[name] = _canonical_uuid(exact[0].get("uuid"))
    if len(set(ids.values())) != len(DATABASE_NAMES):
        raise ReleasePreflightError("D1_ALIASED")
    return ids


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_candidate(
    bindings: list[dict], version_id: str, owner_id: str, annotations: dict
) -> dict:
    """Construct and validate the immutable-version-pinned candidate in memory."""
    if not is_safe_version_id(version_id) or version_id == "latest":
        raise ReleasePreflightError("PINNED_VERSION_INVALID")
    owner_id = _canonical_uuid(owner_id)
    names = [b["name"] for b in bindings]
    if OWNER_BINDING in names or len(names) != len(set(names)):
        raise ReleasePreflightError("BINDING_COLLISION")
    inheritance = [
        {"type": "inherit", "name": name, "version_id": version_id}
        for name in names
    ]
    candidate = {"bindings": inheritance + [
        {"type": "d1", "name": OWNER_BINDING, "database_id": owner_id}
    ], "annotations": dict(annotations)}
    if (
        len(candidate["bindings"]) != len(bindings) + 1
        or any(set(x) != {"type", "name", "version_id"} or x["version_id"] != version_id
               or x["type"] != "inherit" for x in inheritance)
        or candidate["bindings"][-1]["type"] != "d1"
        or candidate["bindings"][-1]["name"] != OWNER_BINDING
        or candidate["bindings"][-1]["database_id"] != owner_id
    ):
        raise ReleasePreflightError("CANDIDATE_NOT_PINNED")
    return candidate


def _snapshot(
    worker: str,
    expected_count: int,
    deployments_before: object,
    deployments_after: object,
    version_payload: object,
    settings_payload: object,
    owner_id: str,
    existing_database_id: str,
) -> dict:
    try:
        before_id = resolve_served_version_id(deployments_before)
        after_id = resolve_served_version_id(deployments_after)
    except ServedVersionResolutionError as exc:
        raise ReleasePreflightError("SERVED_VERSION_UNPROVEN") from exc
    if before_id != after_id:
        raise ReleasePreflightError("LIVE_VERSION_DRIFT")

    version = _object_result(version_payload)
    if version.get("id") != before_id:
        raise ReleasePreflightError("VERSION_DETAIL_MISMATCH")
    resources = version.get("resources")
    if not isinstance(resources, dict):
        raise ReleasePreflightError("RESOURCE_EVIDENCE_MISSING")
    script = resources.get("script")
    runtime = resources.get("script_runtime")
    if not isinstance(script, dict) or not isinstance(script.get("etag"), str) or not script["etag"]:
        raise ReleasePreflightError("SCRIPT_EVIDENCE_MISSING")
    if not isinstance(runtime, dict) or not isinstance(runtime.get("compatibility_date"), str):
        raise ReleasePreflightError("RUNTIME_EVIDENCE_MISSING")
    bindings = resources.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != expected_count:
        raise ReleasePreflightError("BINDING_COUNT_UNEXPECTED")
    names = [b.get("name") if isinstance(b, dict) else None for b in bindings]
    if len(set(names)) != expected_count or not all(isinstance(n, str) and n for n in names):
        raise ReleasePreflightError("BINDING_NAMES_INVALID")
    if OWNER_BINDING in names:
        raise ReleasePreflightError("OWNER_D1_ALREADY_INSTALLED")
    try:
        current = canonical_state(version_payload)
        if canonical_state(settings_payload) != current:
            raise ReleasePreflightError("SETTINGS_SERVED_DRIFT")
    except BindingStateError as exc:
        raise ReleasePreflightError("BINDING_AUTHORITY_INVALID") from exc
    services = {b["name"]: b.get("service") for b in bindings if b.get("type") == "service"}
    needed = (
        {"P01_ENGINE_SERVICE": "padiem-ai-engine",
         "IDENTITY_AUTHORITY_SERVICE": "padiem-control-plane-identity"}
        if worker == "padiem-chat"
        else {"CONTROL_PLANE_IDENTITY": "padiem-control-plane-identity"}
    )
    if any(services.get(name) != target for name, target in needed.items()):
        raise ReleasePreflightError("TRUSTED_SERVICE_AUTHORITY_DRIFT")
    secrets = {b["name"] for b in bindings if b.get("type") == "secret_text"}
    essential_secret = (
        "P01_ENGINE_CREDENTIAL" if worker == "padiem-chat"
        else "PADIEM_ENGINE_CALLER_REGISTRY_V1"
    )
    if essential_secret not in secrets:
        raise ReleasePreflightError("P01_CALLER_SECRET_MISSING")
    existing_d1s = {
        b["name"]: b.get("database_id") or b.get("id")
        for b in bindings if b.get("type") == "d1"
    }
    if worker == "padiem-chat":
        if existing_d1s != {"PADIEM_CHAT_DB": existing_database_id}:
            raise ReleasePreflightError("PRIMARY_D1_AUTHORITY_DRIFT")
    elif (
        existing_d1s.get("ENGINE_CONTINUATION") != existing_database_id
        or len(existing_d1s) != 6
        or set(existing_d1s.values()) != {existing_database_id}
    ):
        raise ReleasePreflightError("ENGINE_CONTINUATION_D1_AUTHORITY_DRIFT")

    annotations = version.get("annotations")
    if not isinstance(annotations, dict) or set(annotations) - OBSERVED_ANNOTATIONS:
        raise ReleasePreflightError("VERSION_ANNOTATIONS_UNEXPECTED")
    writable = {k: v for k, v in annotations.items() if k in WRITABLE_ANNOTATIONS}
    if any(not isinstance(v, str) for v in writable.values()):
        raise ReleasePreflightError("VERSION_ANNOTATIONS_INVALID")

    # Cloudflare PATCH /settings supports a named binding inherited from an
    # explicit immutable version. No POST/PATCH request is assembled or sent here.
    candidate = build_candidate(bindings, before_id, owner_id, writable)
    if len(candidate["bindings"]) != expected_count + 1:
        raise ReleasePreflightError("CANDIDATE_NOT_PINNED")

    future = copy.deepcopy(version_payload)
    future["result"]["id"] = "offline-only-future-version"
    future["result"]["resources"]["bindings"].append(
        {"type": "d1", "name": OWNER_BINDING, "database_id": owner_id}
    )
    try:
        assert_owner_version_integrity(version_payload, future, owner_id)
    except BindingStateError as exc:
        raise ReleasePreflightError("CANDIDATE_RESOURCE_DRIFT") from exc

    # The artifact contains no full settings, source text, database UUIDs,
    # secret names, credential values, or binding text values.
    return {
        "worker": worker,
        "base_version": before_id,
        "existing_bindings": expected_count,
        "planned_bindings": expected_count + 1,
        "pinned_inherit_count": len(candidate["bindings"]) - 1,
        "candidate_additions": 1,
        "script_metadata_digest": _digest(script),
        "runtime_metadata_digest": _digest(runtime),
        "binding_name_type_digest": _digest(
            sorted((b["name"], b["type"]) for b in bindings)
        ),
        "annotations_carried": sorted(writable),
        "served_version_stable": True,
        "settings_match_served": True,
        "candidate_only": True,
    }


def prepare_release(
    inventories: dict[str, object],
    workers: dict[str, tuple[object, object, object, object]],
    main_sha: str,
) -> dict:
    if not is_safe_version_id(main_sha) or len(main_sha) != 40:
        raise ReleasePreflightError("SOURCE_SHA_INVALID")
    ids = _database_ids(inventories)
    output = []
    for worker, count in EXPECTED_WORKERS:
        before, after, detail, settings = workers[worker]
        expected_primary = ids["padiem-chat-db" if worker == "padiem-chat" else "padiem-engine"]
        output.append(_snapshot(
            worker, count, before, after, detail, settings, ids[OWNER_NAME],
            expected_primary,
        ))
    return {
        "mode": "OWNER_D1_GET_ONLY_PREPARATION",
        "source_main": main_sha,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "owner_d1_unique_and_distinct": True,
        "workers": output,
        "pre_mutation_release_anchor": False,
        "production_mutation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--d1-owner", type=Path, required=True)
    parser.add_argument("--d1-chat", type=Path, required=True)
    parser.add_argument("--d1-engine", type=Path, required=True)
    for label in ("engine", "chat"):
        for part in ("before", "after", "version", "settings"):
            parser.add_argument(f"--{label}-{part}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = vars(args)
    try:
        if args.output.exists():
            raise ReleasePreflightError("OUTPUT_ALREADY_EXISTS")
        baseline = prepare_release(
            {OWNER_NAME: _read(args.d1_owner),
             "padiem-chat-db": _read(args.d1_chat),
             "padiem-engine": _read(args.d1_engine)},
            {worker: tuple(_read(inputs[f"{label}_{part}"]) for part in
                 ("before", "after", "version", "settings"))
             for label, worker in (("engine", "padiem-ai-engine"), ("chat", "padiem-chat"))},
            args.main_sha,
        )
        args.output.write_text(json.dumps(baseline, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except ReleasePreflightError as exc:
        print(f"OWNER_D1_PREFLIGHT=BLOCKED;REASON={exc}", file=sys.stderr)
        return 2
    print("OWNER_D1_PREFLIGHT=PASS")
    print("ENGINE_INHERITS=18;CHAT_INHERITS=27")
    print("CANDIDATE_RESOURCE_PARITY=PASS")
    print("READONLY_BASELINE_CREATED=YES")
    print("DURABLE_PREMUTATION_RELEASE_ANCHOR=NO")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
