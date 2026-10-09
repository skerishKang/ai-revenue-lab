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

SUPPORTED_TYPES = {"assets", "service", "d1", "r2_bucket", "plain_text", "secret_text"}


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
    if not isinstance(bindings, list):
        raise BindingStateError("Worker payload has no bindings array")

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


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingStateError(f"cannot read settings payload: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        assert_preserved(_load(args.before), _load(args.after))
    except BindingStateError as exc:
        print("B62_BINDING_AUTHORITY_PRESERVED=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    print("B62_BINDING_AUTHORITY_PRESERVED=PASS")
    print("SECRET_VALUES_READ=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
