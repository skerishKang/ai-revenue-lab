#!/usr/bin/env python3
"""Compare immutable Engine Worker binding *names/types* without secrets (#4383)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from cloudflare_served_version import resolve_served_version_id  # noqa: E402

GOOD_VERSION = "4d90cf39-ca1b-48b4-977e-dce1ca576d7a"
BAD_VERSION = "87ae6263-724e-479a-868a-598fe9bf0d01"
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class AuditError(ValueError):
    pass


def inventory(payload: object, expected_version: str) -> dict[str, str]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise AuditError("immutable version API success missing")
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("id") != expected_version:
        raise AuditError("immutable version identity mismatch")
    resources = result.get("resources")
    bindings = resources.get("bindings") if isinstance(resources, dict) else None
    if isinstance(bindings, dict):
        values = [{**entry, "name": name} for name, entry in bindings.items() if isinstance(entry, dict)]
        if len(values) != len(bindings):
            raise AuditError("malformed binding map")
    elif isinstance(bindings, list):
        values = bindings
    else:
        raise AuditError("immutable resources.bindings not available")
    found: dict[str, str] = {}
    for entry in values:
        if not isinstance(entry, dict):
            raise AuditError("malformed binding entry")
        name, kind = entry.get("name"), entry.get("type")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise AuditError("invalid binding name syntax")
        if not isinstance(kind, str) or not TYPE_RE.fullmatch(kind):
            raise AuditError("invalid binding type syntax")
        if name in found:
            raise AuditError("duplicate binding name")
        found[name] = kind
    if not found:
        raise AuditError("empty binding inventory")
    return found


def compare(deployments: object, good: object, bad: object) -> tuple[list[str], list[str]]:
    try:
        served = resolve_served_version_id(deployments)
    except Exception as exc:
        raise AuditError("could not confirm currently served Engine version") from exc
    if served != GOOD_VERSION:
        raise AuditError("served Engine version is not the recorded safe rollback target")
    old = inventory(good, GOOD_VERSION)
    broken = inventory(bad, BAD_VERSION)
    removed = sorted(f"{name}:{kind}" for name, kind in old.items() if broken.get(name) != kind)
    added = sorted(f"{name}:{kind}" for name, kind in broken.items() if old.get(name) != kind)
    if len(removed) != 6 or added:
        raise AuditError(f"unexpected binding diff counts: removed={len(removed)} added={len(added)}")
    return removed, added


# The six flags are operator-owned plain_text bindings. A served immutable
# version may carry them even if the mutable settings plane used by Wrangler
# no longer does. Compare NAME/TYPE ONLY, never content or targets.
PROTECTED_ENGINE_FLAGS = frozenset({
    "PADIEM_WEB_XLSX_P01_DURABLE_TOOL_ENABLED",
    "PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED",
    "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED",
})


def settings_flags(settings: object, good_version: object) -> list[str]:
    old = inventory(good_version, GOOD_VERSION)
    if any(old.get(name) != "plain_text" for name in PROTECTED_ENGINE_FLAGS):
        raise AuditError("immutable rollback version lacks required plain_text flags")
    if not isinstance(settings, dict) or settings.get("success") is not True:
        raise AuditError("mutable Worker settings GET evidence missing")
    result = settings.get("result")
    items = result.get("bindings") if isinstance(result, dict) else None
    if not isinstance(items, list):
        raise AuditError("mutable Worker settings bindings missing")
    found: dict[str, str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            raise AuditError("invalid mutable settings binding")
        name, kind = entry.get("name"), entry.get("type")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise AuditError("invalid mutable settings binding name")
        if not isinstance(kind, str) or not TYPE_RE.fullmatch(kind):
            raise AuditError("invalid mutable settings binding type")
        if name in found:
            raise AuditError("duplicate mutable settings binding")
        found[name] = kind
    return sorted(name for name in PROTECTED_ENGINE_FLAGS if found.get(name) != "plain_text")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployments", required=True)
    parser.add_argument("--good-version", required=True)
    parser.add_argument("--bad-version", required=True)
    parser.add_argument("--settings", required=True)
    args = parser.parse_args()
    try:
        def load(path: str) -> object:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        previous = load(args.good_version)
        removed, added = compare(
            load(args.deployments), previous, load(args.bad_version),
        )
        settings_missing = settings_flags(load(args.settings), previous)
    except (AuditError, OSError, ValueError) as exc:
        print("B54_ENGINE_READONLY_BINDING_AUDIT=FAIL")
        print("REASON=" + str(exc))
        print("PRODUCTION_MUTATION=0")
        return 1
    print("B54_ENGINE_READONLY_BINDING_AUDIT=PASS")
    print("SERVED_VERSION_EQUALS_ROLLBACK=PASS")
    print("REMOVED_COUNT=" + str(len(removed)))
    for item in removed:
        print("REMOVED_BINDING_NAME_TYPE=" + item)
    print("ADDED_COUNT=" + str(len(added)))
    print("MUTABLE_SETTINGS_FLAGS_MISSING_COUNT=" + str(len(settings_missing)))
    for name in settings_missing:
        print("MUTABLE_SETTINGS_FLAG_MISSING_NAME=" + name)
    print("MUTABLE_SETTINGS_FLAG_PARITY=" + ("PASS" if not settings_missing else "FAIL"))
    print("B54_ENGINE_REDEPLOY_ALLOWED=NO")
    print("SECRET_VALUES_READ=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
