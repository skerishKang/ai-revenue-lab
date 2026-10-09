#!/usr/bin/env python3
"""#3782: protected Owner P01 D1 Worker binding release transaction checks.

Offline/local JSON verifier, reusing the canonical served-version resolver,
B62 Owner D1 preflight, and full immutable resource-integrity guard.
No Cloudflare client/network access. Never prints payloads, secrets or DB ids.
Mutation is owned ONLY by the separate, manually approved GitHub Actions workflow.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from b62_binding_state_guard import (
    BindingStateError,
    assert_one_owner_d1_added,
    assert_owner_version_integrity,
    canonical_state,
    validate_owner_d1_id,
)
from b62_owner_d1_release_preflight import (
    OWNER_BINDING,
    OWNER_NAME,
    ReleasePreflightError,
    _database_ids,
    _digest,
    _object_result,
    _read,
    _snapshot,
    build_candidate,
)
from cloudflare_served_version import (
    ServedVersionResolutionError,
    is_safe_version_id,
    resolve_served_version_id,
)

WORKERS = {"engine": ("padiem-ai-engine", 18), "chat": ("padiem-chat", 27)}
PRIMARY_DATABASE = {"engine": "padiem-engine", "chat": "padiem-chat-db"}
ANNOTATIONS = {"workers/message", "workers/tag"}


class TransactionError(RuntimeError):
    pass


def _active(payload: object) -> str:
    try:
        return resolve_served_version_id(payload)
    except ServedVersionResolutionError as exc:
        raise TransactionError("ACTIVE_VERSION_UNPROVEN") from exc


def _latest(payload: object) -> str:
    result = _object_result(payload)
    items = result.get("items")
    if not isinstance(items, list) or not items:
        raise TransactionError("LATEST_VERSION_UNPROVEN")
    entry = items[0]
    version = entry.get("id") if isinstance(entry, dict) else None
    if not is_safe_version_id(version):
        raise TransactionError("LATEST_VERSION_UNPROVEN")
    return version


def _binding_identity(version_payload: object, binding: str) -> list[tuple]:
    return [x for x in canonical_state(version_payload) if x[1] == binding]


def _current_peer(
    peer_deployment: object, peer_version: object,
    expected_owner_id: str, *, engine_first: bool
) -> str:
    live = _active(peer_deployment)
    peer = _object_result(peer_version)
    if peer.get("id") != live:
        raise TransactionError("PEER_VERSION_NOT_ACTIVE")
    try:
        state = canonical_state(peer_version)
    except BindingStateError as exc:
        raise TransactionError("PEER_BINDING_INVALID") from exc
    owner = [x for x in state if x[1] == OWNER_BINDING]
    if engine_first:
        # Prevent ambiguous partial release or accidental repeated connection.
        if owner:
            raise TransactionError("ORDER_ENGINE_FIRST_REQUIRED")
    elif owner != [("d1", OWNER_BINDING, expected_owner_id)]:
        raise TransactionError("ENGINE_OWNER_D1_NOT_READY")
    return live


def prepare(
    worker: str,
    source_sha: str,
    databases: dict[str, object],
    before: object,
    after: object,
    version: object,
    settings: object,
    latest: object,
    peer_deployments: object,
    peer_version: object,
) -> tuple[dict, dict]:
    if worker not in WORKERS:
        raise TransactionError("TARGET_NOT_ALLOWLISTED")
    if not (isinstance(source_sha, str) and len(source_sha) == 40
            and all(c in "0123456789abcdef" for c in source_sha)):
        raise TransactionError("SOURCE_SHA_UNSAFE")
    try:
        ids = _database_ids(databases)
        name, count = WORKERS[worker]
        baseline = _snapshot(
            name, count, before, after, version, settings,
            ids[OWNER_NAME], ids[PRIMARY_DATABASE[worker]]
        )
        peer_id = _current_peer(
            peer_deployments, peer_version, ids[OWNER_NAME],
            engine_first=(worker == "engine"),
        )
    except (ReleasePreflightError, BindingStateError) as exc:
        raise TransactionError("PREMUTATION_AUTHORITY_INVALID") from exc

    if _latest(latest) != baseline["base_version"]:
        # Cloudflare PATCH /settings can reject when latest != served (10214).
        raise TransactionError("LATEST_AND_SERVED_DIFFER")
    original = _object_result(version)
    writable_annotations = {
        k: v for k, v in original.get("annotations", {}).items() if k in ANNOTATIONS
    }
    candidate = build_candidate(
        original["resources"]["bindings"], baseline["base_version"],
        ids[OWNER_NAME], writable_annotations
    )
    anchor = {
        "kind": "OWNER_P01_D1_FRESH_PREMUTATION_ROLLBACK_ANCHOR",
        "source_main_sha": source_sha,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "worker": name,
        "worker_alias": worker,
        "rollback_version_id": baseline["base_version"],
        "peer_active_version_id": peer_id,
        "original_binding_count": count,
        "target_binding_count": count + 1,
        "script_metadata_digest": baseline["script_metadata_digest"],
        "runtime_metadata_digest": baseline["runtime_metadata_digest"],
        "binding_name_type_digest": baseline["binding_name_type_digest"],
        "annotations_carried": baseline["annotations_carried"],
        "single_served_version": True,
        "latest_matches_served": True,
        "first_mutation_not_yet_attempted": True,
        "prepared_for_publication_before_mutation": True,
    }
    return candidate, anchor


def verify(
    pre: object, post: object, deployments: object, post_settings: object,
    owner_id: str, anchor: dict
) -> str:
    current = _active(deployments)
    original_id = anchor.get("rollback_version_id")
    if current == original_id:
        raise TransactionError("NEW_VERSION_NOT_SERVING")
    if _object_result(post).get("id") != current:
        raise TransactionError("POST_VERSION_NOT_ACTIVE")
    if _object_result(pre).get("id") != original_id:
        raise TransactionError("ROLLBACK_ANCHOR_VERSION_MISMATCH")
    try:
        assert_owner_version_integrity(pre, post, owner_id)
        if canonical_state(post_settings) != canonical_state(post):
            raise TransactionError("POST_SETTINGS_NOT_SERVED")
    except BindingStateError as exc:
        raise TransactionError("POST_WORKER_RESOURCE_DRIFT") from exc
    old_ann = {
        k: v for k, v in _object_result(pre).get("annotations", {}).items() if k in ANNOTATIONS
    }
    new_ann = {
        k: v for k, v in _object_result(post).get("annotations", {}).items() if k in ANNOTATIONS
    }
    if old_ann != new_ann:
        raise TransactionError("ANNOTATIONS_NOT_PRESERVED")
    if anchor.get("worker") not in [x[0] for x in WORKERS.values()]:
        raise TransactionError("ANCHOR_WORKER_INVALID")
    return current


def verify_rollback_target(anchor: dict, version: object, expected_worker: str) -> str:
    if anchor.get("kind") != "OWNER_P01_D1_FRESH_PREMUTATION_ROLLBACK_ANCHOR":
        raise TransactionError("ANCHOR_NOT_TRUSTED")
    if anchor.get("worker") != expected_worker:
        raise TransactionError("ANCHOR_WORKER_MISMATCH")
    if not anchor.get("prepared_for_publication_before_mutation"):
        raise TransactionError("ANCHOR_NOT_PREPARED")
    result = _object_result(version)
    if result.get("id") != anchor.get("rollback_version_id"):
        raise TransactionError("ROLLBACK_TARGET_ID_MISMATCH")
    resources = result.get("resources")
    if not isinstance(resources, dict):
        raise TransactionError("ROLLBACK_TARGET_RESOURCE_MISSING")
    for field, candidate in (
        ("script_metadata_digest", resources.get("script")),
        ("runtime_metadata_digest", resources.get("script_runtime")),
    ):
        if anchor.get(field) != _digest(candidate):
            raise TransactionError("ROLLBACK_TARGET_RESOURCE_DRIFT")
    state = canonical_state(version)
    if len(state) != anchor.get("original_binding_count"):
        raise TransactionError("ROLLBACK_TARGET_BINDINGS_DRIFT")
    digest = _digest(sorted((entry[1], entry[0]) for entry in state))
    if digest != anchor.get("binding_name_type_digest"):
        raise TransactionError("ROLLBACK_TARGET_BINDINGS_DRIFT")
    return result["id"]


def validate_patch_settings(candidate: object, original_version: object) -> str:
    """Require the EXACT JSON object accepted by Cloudflare multipart 'settings'.

    Cloudflare form field name supplies the only outer 'settings' wrapper.
    This guard validates the final on-disk file, not just build_candidate().
    """
    if not isinstance(candidate, dict) or set(candidate) != {"bindings", "annotations"}:
        raise TransactionError("PATCH_SETTINGS_TOP_LEVEL_INVALID")
    current = _object_result(original_version)
    current_id = current.get("id")
    resources = current.get("resources")
    if not is_safe_version_id(current_id) or not isinstance(resources, dict):
        raise TransactionError("PATCH_SETTINGS_BASE_INVALID")
    originals = resources.get("bindings")
    if not isinstance(originals, list) or not originals:
        raise TransactionError("PATCH_SETTINGS_BASE_BINDINGS_INVALID")
    entries = candidate["bindings"]
    if not isinstance(entries, list) or len(entries) != len(originals) + 1:
        raise TransactionError("PATCH_SETTINGS_BINDING_COUNT_INVALID")
    expected_inherited = [
        {"type": "inherit", "name": b["name"], "version_id": current_id}
        for b in originals
    ]
    if entries[:-1] != expected_inherited:
        raise TransactionError("PATCH_SETTINGS_INHERIT_DRIFT")
    added = entries[-1]
    if not isinstance(added, dict) or set(added) != {"type", "name", "database_id"}:
        raise TransactionError("PATCH_SETTINGS_D1_INVALID")
    if added["type"] != "d1" or added["name"] != OWNER_BINDING:
        raise TransactionError("PATCH_SETTINGS_D1_INVALID")
    try:
        owner_id = validate_owner_d1_id(added["database_id"])
    except BindingStateError as exc:
        raise TransactionError("PATCH_SETTINGS_D1_INVALID") from exc
    if not isinstance(candidate["annotations"], dict):
        raise TransactionError("PATCH_SETTINGS_ANNOTATIONS_INVALID")
    original_annotations = current.get("annotations") or {}
    writable = {k: v for k, v in original_annotations.items() if k in ANNOTATIONS}
    if candidate["annotations"] != writable:
        raise TransactionError("PATCH_SETTINGS_ANNOTATIONS_DRIFT")
    return owner_id


def verify_patch_response(
    original_version: object, patch_response: object, candidate: object
) -> None:
    """HTTP 200/success is insufficient: one Owner D1 MUST appear in PATCH result."""
    owner_id = validate_patch_settings(candidate, original_version)
    try:
        assert_one_owner_d1_added(original_version, patch_response, owner_id)
    except BindingStateError as exc:
        raise TransactionError("PATCH_RESPONSE_D1_NOT_APPLIED") from exc


def build_rollback_deployment(version_id: str) -> dict:
    """Cloudflare POST /deployments body, pinned to one known Worker Version."""
    if not isinstance(version_id, str) or not is_safe_version_id(version_id):
        raise TransactionError("ROLLBACK_DEPLOYMENT_VERSION_INVALID")
    try:
        parsed = UUID(version_id)
    except (ValueError, TypeError) as exc:
        raise TransactionError("ROLLBACK_DEPLOYMENT_VERSION_INVALID") from exc
    if str(parsed) != version_id or parsed.int == 0:
        raise TransactionError("ROLLBACK_DEPLOYMENT_VERSION_INVALID")
    return {
        "strategy": "percentage",
        "versions": [{"version_id": version_id, "percentage": 100}],
    }


def _write_new(path: Path, payload: object) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--worker", choices=tuple(WORKERS), required=True)
    p.add_argument("--main-sha", required=True)
    for label in ("d1-owner", "d1-chat", "d1-engine", "before", "after", "version",
                  "settings", "latest", "peer-deployments", "peer-version"):
        p.add_argument("--" + label, required=True, type=Path)
    p.add_argument("--candidate", required=True, type=Path)
    p.add_argument("--anchor", required=True, type=Path)
    v = sub.add_parser("verify")
    for label in ("pre", "post", "deployments", "settings", "d1-owner", "d1-chat", "d1-engine", "anchor"):
        v.add_argument("--" + label, required=True, type=Path)
    v.add_argument("--worker", choices=tuple(WORKERS), required=True)
    patch_response = sub.add_parser("verify-patch-response")
    patch_response.add_argument("--before", required=True, type=Path)
    patch_response.add_argument("--candidate", required=True, type=Path)
    patch_response.add_argument("--response", required=True, type=Path)
    r = sub.add_parser("verify-rollback-target")
    r.add_argument("--anchor", required=True, type=Path)
    r.add_argument("--version", required=True, type=Path)
    r.add_argument("--worker", choices=tuple(WORKERS), required=True)
    deployment = sub.add_parser("build-rollback-deployment")
    deployment.add_argument("--version-id", required=True)
    deployment.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            candidate, anchor = prepare(
                args.worker, args.main_sha,
                {OWNER_NAME: _read(args.d1_owner),
                 "padiem-chat-db": _read(args.d1_chat),
                 "padiem-engine": _read(args.d1_engine)},
                _read(args.before), _read(args.after), _read(args.version),
                _read(args.settings), _read(args.latest),
                _read(args.peer_deployments), _read(args.peer_version)
            )
            if args.candidate.resolve() == args.anchor.resolve():
                raise TransactionError("OUTPUT_PATH_ALIAS")
            if args.candidate.exists() or args.anchor.exists():
                raise TransactionError("OUTPUT_EXISTS")
            validate_patch_settings(candidate, _read(args.version))
            _write_new(args.candidate, candidate)
            _write_new(args.anchor, anchor)
            print("OWNER_D1_PREMUTATION_CHECK=PASS")
            print("FRESH_ROLLBACK_ANCHOR_READY_FOR_UPLOAD=YES")
            print("OWNER_D1_PATCH_CANDIDATE_IN_RUNNER_ONLY=YES")
        elif args.mode == "verify":
            inventory = _read(args.d1_owner)
            ids = _database_ids({
                OWNER_NAME: inventory,
                "padiem-chat-db": _read(args.d1_chat),
                "padiem-engine": _read(args.d1_engine),
            })
            anchor = _read(args.anchor)
            if anchor.get("worker") != WORKERS[args.worker][0]:
                raise TransactionError("ANCHOR_WORKER_MISMATCH")
            verify(_read(args.pre), _read(args.post), _read(args.deployments),
                   _read(args.settings), ids[OWNER_NAME], anchor)
            print("OWNER_D1_POST_SERVED_RESOURCES=PASS")
        elif args.mode == "verify-patch-response":
            verify_patch_response(
                _read(args.before), _read(args.response), _read(args.candidate)
            )
            print("OWNER_D1_PATCH_RESPONSE_D1_AUTHORITY=PASS")
        elif args.mode == "verify-rollback-target":
            verify_rollback_target(
                _read(args.anchor), _read(args.version), WORKERS[args.worker][0]
            )
            print("OWNER_D1_ROLLBACK_TARGET_ANCHORED=PASS")
        else:
            _write_new(args.output, build_rollback_deployment(args.version_id))
            print("OWNER_D1_ROLLBACK_DEPLOYMENT_PAYLOAD=OFFICIAL_SCHEMA_PASS")
    except (TransactionError, ReleasePreflightError, BindingStateError, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, TransactionError) else "INVALID_RELEASE_EVIDENCE"
        print("OWNER_D1_RELEASE_GUARD=FAIL;REASON=" + reason, file=sys.stderr)
        return 2
    print("SECRET_VALUES_PRINTED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
