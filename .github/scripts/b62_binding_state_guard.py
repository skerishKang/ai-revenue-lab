#!/usr/bin/env python3
"""Compare B62 Cloudflare Worker binding structure before and after deployment.

Secret values are never read. For each supported binding type, compare only the
fields that define its deployment authority. Accept either Worker settings or
immutable served-version payloads; D1 uses `id` in settings and `database_id`
in version details. The guard fails closed on unknown
binding types, malformed entries, duplicate names, additions, removals, or
field drift.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from b62_web_secrets_store_contract import expected_web_secret_bindings
from uuid import UUID

SUPPORTED_TYPES = {"assets", "service", "d1", "r2_bucket", "plain_text", "secret_text", "secrets_store_secret"}
OWNER_P01_D1_BINDING = "BROWSER_CONTROL_OWNER_P01_D1"


class BindingStateError(RuntimeError):
    pass


def _optional_text(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise BindingStateError(f"binding field {field!r} must be a non-empty string when present")
    return value


def _required_text(raw: dict[str, Any], field: str) -> str:
    value = _optional_text(raw, field)
    if value is None:
        raise BindingStateError(f"binding field {field!r} is required")
    return value


def canonical_binding(raw: object) -> tuple[object, ...]:
    if not isinstance(raw, dict):
        raise BindingStateError("binding entry is not an object")
    kind = raw.get("type")
    name = raw.get("name")
    if kind not in SUPPORTED_TYPES:
        raise BindingStateError(f"unsupported binding type {kind!r}")
    if not isinstance(name, str) or not name:
        raise BindingStateError("binding name must be a non-empty string")

    if kind == "assets":
        return (kind, name)
    if kind == "service":
        return (
            kind,
            name,
            _required_text(raw, "service"),
            _optional_text(raw, "environment"),
            _optional_text(raw, "entrypoint"),
        )
    if kind == "d1":
        # GET /settings uses "id"; GET /versions/{version} uses "database_id".
        # Refuse conflicting aliases instead of silently picking one.
        settings_id = _optional_text(raw, "id")
        version_id = _optional_text(raw, "database_id")
        if settings_id is not None and version_id is not None and settings_id != version_id:
            raise BindingStateError("conflicting D1 database identities")
        db_id = settings_id or version_id
        if db_id is None:
            raise BindingStateError("D1 database identity missing")
        return (kind, name, db_id)
    if kind == "r2_bucket":
        return (
            kind,
            name,
            _required_text(raw, "bucket_name"),
            _optional_text(raw, "jurisdiction"),
        )
    if kind == "secrets_store_secret":
        return (
            kind, name,
            _required_text(raw, "store_id"),
            _required_text(raw, "secret_name"),
        )
    if kind == "plain_text":
        text = raw.get("text")
        if not isinstance(text, str):
            raise BindingStateError(f"plain_text binding {name!r} has no string text")
        return (kind, name, text)
    # Secret values are not available from Worker settings and must never be read.
    return (kind, name)


def canonical_state(payload: object) -> tuple[tuple[object, ...], ...]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise BindingStateError("settings payload is not a successful Cloudflare response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise BindingStateError("settings payload has no result object")
    if "bindings" in result:
        bindings = result["bindings"]  # GET /settings
    else:
        # GET /versions/{id}: verify the immutable version identity before use.
        identity = result.get("id")
        resources = result.get("resources")
        if not isinstance(identity, str) or not identity or not isinstance(resources, dict):
            raise BindingStateError("version payload identity or resources missing")
        bindings = resources.get("bindings")
    if isinstance(bindings, dict):
        # Version resources may be keyed by binding name. Match the canonical
        # Engine served-version guard: an embedded name must agree with its key.
        entries = []
        for key, value in bindings.items():
            if not isinstance(key, str) or not key or not isinstance(value, dict):
                raise BindingStateError("malformed keyed version binding")
            if "name" in value and value["name"] != key:
                raise BindingStateError("version binding key/name disagreement")
            entries.append({**value, "name": key})
        bindings = entries
    if not isinstance(bindings, list):
        raise BindingStateError("Worker payload has no bindings collection")

    canonical = [canonical_binding(binding) for binding in bindings]
    names = [entry[1] for entry in canonical]
    if len(names) != len(set(names)):
        raise BindingStateError("duplicate binding names")
    return tuple(sorted(canonical, key=lambda entry: (str(entry[0]), str(entry[1]))))


def assert_preserved(before: object, after: object) -> None:
    before_state = canonical_state(before)
    after_state = canonical_state(after)
    if before_state != after_state:
        before_set = set(before_state)
        after_set = set(after_state)
        removed = sorted(before_set - after_set, key=repr)
        added = sorted(after_set - before_set, key=repr)
        raise BindingStateError(
            "binding authority drift detected; "
            f"removed_count={len(removed)} added_count={len(added)}"
        )


def assert_web_secret_additions_only(before: object, after: object) -> None:
    """Only missing Owner-approved same-account Secret Store entries may appear."""
    original = canonical_state(before)
    final = canonical_state(after)
    existing_names = {entry[1] for entry in original}
    expected = {
        name: canonical_binding(item)
        for name, item in expected_web_secret_bindings().items()
    }
    # If already installed, require existing identity exactly; never overwrite.
    for name, target in expected.items():
        original_match = [entry for entry in original if entry[1] == name]
        if original_match and original_match != [target]:
            raise BindingStateError("web Secrets Store binding alias collision")
    additions = tuple(target for name, target in expected.items() if name not in existing_names)
    required = tuple(sorted((*original, *additions), key=lambda e: (str(e[0]), str(e[1]))))
    if final != required:
        raise BindingStateError("binding authority drift; expected only exact web Secrets Store additions")


def validate_owner_d1_id(value: str) -> str:
    """Accept one canonical UUID, never reveal it in failure diagnostics."""
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise BindingStateError("approved Owner D1 ID is not a UUID") from exc
    if str(parsed) != value or parsed.int == 0:
        raise BindingStateError("approved Owner D1 ID must be a nonzero canonical UUID")
    return value


def assert_one_owner_d1_added(before: object, after: object, owner_database_id: str) -> None:
    """Allow exactly one approved Owner D1 addition, preserving all other authority."""
    db_id = validate_owner_d1_id(owner_database_id)
    before_state = canonical_state(before)
    after_state = canonical_state(after)
    if any(entry[1] == OWNER_P01_D1_BINDING for entry in before_state):
        raise BindingStateError("Owner D1 binding already exists before additive install")
    # Never accidentally bind the Owner click database to the Engine or Chat D1.
    if any(entry[0] == "d1" and entry[2] == db_id for entry in before_state):
        raise BindingStateError("Owner D1 aliases an existing Worker D1")
    expected = tuple(sorted(
        (*before_state, ("d1", OWNER_P01_D1_BINDING, db_id)),
        key=lambda entry: (str(entry[0]), str(entry[1])),
    ))
    if after_state != expected:
        raise BindingStateError("binding authority drift detected; expected only approved Owner D1 addition")


def assert_owner_version_integrity(before: object, after: object, owner_database_id: str) -> None:
    """Require immutable served-version code/runtime parity alongside one D1 addition.

    A binding-only equality check cannot prove that a PATCH or deployment
    preserved Python Worker code, assets, compatibility flags or runtime config.
    Compare the exact original and candidate immutable version resources, never
    mutable Worker settings. Fail closed on missing version/resource evidence.
    """

    def version_resources(payload: object) -> tuple[str, dict[str, object]]:
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise BindingStateError("immutable Worker version evidence missing")
        result = payload.get("result")
        if not isinstance(result, dict) or "bindings" in result:
            raise BindingStateError("immutable Worker version result required")
        version_id = result.get("id")
        resources = result.get("resources")
        if not isinstance(version_id, str) or not version_id:
            raise BindingStateError("Worker version identity missing")
        if not isinstance(resources, dict):
            raise BindingStateError("Worker version resources missing")
        script = resources.get("script")
        runtime = resources.get("script_runtime")
        if not isinstance(script, dict) or not isinstance(script.get("etag"), str) or not script["etag"]:
            raise BindingStateError("Worker script content identity missing")
        if not isinstance(runtime, dict):
            raise BindingStateError("Worker runtime identity missing")
        if not isinstance(runtime.get("compatibility_date"), str) or not runtime["compatibility_date"]:
            raise BindingStateError("Worker runtime compatibility identity missing")
        if "bindings" not in resources:
            raise BindingStateError("Worker immutable binding resources missing")
        return version_id, resources

    before_id, old = version_resources(before)
    after_id, new = version_resources(after)
    if before_id == after_id:
        raise BindingStateError("Worker served version did not change")
    # Compare every non-binding resource, including opaque assets descriptors;
    # no raw script, settings, secrets, or fingerprints reach diagnostics.
    if old.keys() != new.keys():
        raise BindingStateError("Worker non-binding resource structure drift")
    if any(old[key] != new[key] for key in old if key != "bindings"):
        raise BindingStateError("Worker script, assets, or runtime authority drift")
    assert_one_owner_d1_added(before, after, owner_database_id)


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingStateError(f"cannot read settings payload: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--expected-add-owner-d1", action="store_true")
    parser.add_argument("--expected-add-web-secrets-store", action="store_true")
    parser.add_argument("--owner-d1-database-id")
    parser.add_argument("--require-served-resource-integrity", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.expected_add_owner_d1 and args.expected_add_web_secrets_store:
            raise BindingStateError("multiple additive authority modes prohibited")
        if args.expected_add_web_secrets_store:
            assert_web_secret_additions_only(_load(args.before), _load(args.after))
        elif args.expected_add_owner_d1:
            if args.owner_d1_database_id is None:
                raise BindingStateError("additive mode requires explicit Owner D1 ID")
            before_payload = _load(args.before)
            after_payload = _load(args.after)
            # Never allow real immutable Worker versions through a binding-only
            # guard just because the caller forgot a CLI safety flag.
            version_evidence = any(
                isinstance(p, dict)
                and isinstance(p.get("result"), dict)
                and "resources" in p["result"]
                for p in (before_payload, after_payload)
            )
            if args.require_served_resource_integrity or version_evidence:
                assert_owner_version_integrity(
                    before_payload, after_payload, args.owner_d1_database_id
                )
            else:
                assert_one_owner_d1_added(
                    before_payload, after_payload, args.owner_d1_database_id
                )
        else:
            if args.require_served_resource_integrity:
                raise BindingStateError("served resource verification requires additive mode")
            if args.owner_d1_database_id is not None:
                raise BindingStateError("Owner D1 ID is not accepted in standard equality mode")
            assert_preserved(_load(args.before), _load(args.after))
    except BindingStateError as exc:
        print("B62_BINDING_AUTHORITY_PRESERVED=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    if args.expected_add_owner_d1:
        print("OWNER_P01_D1_EXACTLY_ONE_ADDITION=PASS")
        print("EXISTING_WORKER_BINDINGS_PRESERVED=PASS")
        if args.require_served_resource_integrity or version_evidence:
            print("OWNER_P01_D1_SERVED_RESOURCE_INTEGRITY=PASS")
    else:
        print("B62_BINDING_AUTHORITY_PRESERVED=PASS")
    print("SECRET_VALUES_READ=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
