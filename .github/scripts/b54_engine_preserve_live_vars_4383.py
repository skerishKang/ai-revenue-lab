#!/usr/bin/env python3
"""Pre-mutation B54 Engine proof that six live XLSX flags are preserved (#4383).

Checks immutable served-version metadata and Wrangler keep_vars only.
Never reports plaintext values, identity targets, or private response bodies.
"""
from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

REQUIRED = frozenset({
    "PADIEM_WEB_XLSX_P01_DURABLE_TOOL_ENABLED",
    "PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED",
    "PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED",
    "PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED",
})


class PreserveError(ValueError):
    pass


def verify(repo_text: str, version: object, version_id: str) -> None:
    try:
        config = tomllib.loads(repo_text)
    except tomllib.TOMLDecodeError as exc:
        raise PreserveError("invalid repository Wrangler configuration") from exc
    if config.get("name") != "padiem-ai-engine" or config.get("keep_vars") is not True:
        raise PreserveError("Engine Wrangler keep_vars must be explicitly true")
    if not isinstance(version, dict) or version.get("success") is not True:
        raise PreserveError("served-version GET evidence missing")
    result = version.get("result")
    if not isinstance(result, dict) or result.get("id") != version_id:
        raise PreserveError("served-version identity is not the pinned pre-deploy version")
    resources = result.get("resources")
    bindings = resources.get("bindings") if isinstance(resources, dict) else None
    if isinstance(bindings, dict):
        items = []
        for name, item in bindings.items():
            if not isinstance(item, dict):
                raise PreserveError("malformed served binding map")
            if item.get("name", name) != name:
                raise PreserveError("served binding identity conflict")
            items.append({**item, "name": name})
    elif isinstance(bindings, list):
        items = bindings
    else:
        raise PreserveError("immutable served bindings missing")
    flags = {}
    for item in items:
        if not isinstance(item, dict):
            raise PreserveError("malformed immutable binding")
        name = item.get("name")
        if name in REQUIRED:
            if name in flags:
                raise PreserveError("duplicate protected feature flag")
            flags[name] = item.get("type")
    if flags.keys() != REQUIRED or any(kind != "plain_text" for kind in flags.values()):
        raise PreserveError("six protected XLSX feature flags are missing or have changed type")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wrangler", required=True)
    p.add_argument("--version-details", required=True)
    p.add_argument("--active-version", required=True)
    args = p.parse_args()
    try:
        verify(
            Path(args.wrangler).read_text(encoding="utf-8"),
            json.loads(Path(args.version_details).read_text(encoding="utf-8")),
            args.active_version,
        )
    except (OSError, ValueError) as exc:
        print("B54_KEEP_LIVE_VARS_PREDEPLOY=FAIL")
        print(f"REASON={exc}")
        print("PRODUCTION_MUTATION=0")
        return 1
    print("B54_KEEP_LIVE_VARS_PREDEPLOY=PASS")
    print("B54_SIX_PLAIN_TEXT_FLAGS_IN_SERVED_VERSION=PASS")
    print("B54_WRANGLER_KEEP_VARS=TRUE")
    print("FEATURE_FLAG_VALUES_READ=0")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
