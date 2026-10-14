#!/usr/bin/env python3
"""Pre-mutation B54 Engine proof that six live XLSX flags are preserved (#4383).

Checks immutable served-version metadata and Wrangler keep_vars only.
Never reports plaintext values, identity targets, or private response bodies.
"""
from __future__ import annotations

import argparse
import json
import os
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


def render_exact_served_flags(repo_text: str, version: object, version_id: str) -> str:
    """Stage immutable served plain_text values only into an ephemeral config.

    No values are printed, saved in the repository, or taken from user/browser
    input. This is needed because Cloudflare's mutable /settings lost the six
    flags; --keep-vars alone preserved that *incomplete* settings state.
    """
    verify(repo_text, version, version_id)
    config = tomllib.loads(repo_text)
    existing_vars = config.get("vars")
    if not isinstance(existing_vars, dict):
        raise PreserveError("Engine Wrangler missing canonical [vars] table")
    if REQUIRED.intersection(existing_vars):
        raise PreserveError("protected flags must not be checked into Wrangler config")
    result = version["result"]
    bindings = result["resources"]["bindings"]
    if isinstance(bindings, dict):
        items = [{**item, "name": name} for name, item in bindings.items()]
    else:
        items = bindings
    exact: dict[str, str] = {}
    for item in items:
        name = item.get("name")
        if name not in REQUIRED:
            continue
        value = item.get("text")
        if not isinstance(value, str) or len(value) > 512:
            raise PreserveError("protected plain_text value unavailable on immutable version")
        if name in exact:
            raise PreserveError("duplicate protected feature flag")
        exact[name] = value
    if exact.keys() != REQUIRED:
        raise PreserveError("six protected feature flags could not be reconstructed")
    marker = "[vars]\n"
    if repo_text.count(marker) != 1:
        raise PreserveError("unexpected Engine Wrangler vars table")
    additions = "".join(f"{name} = {json.dumps(exact[name], ensure_ascii=True)}\n"
                        for name in sorted(exact))
    generated = repo_text.replace(marker, marker + additions, 1)
    try:
        parsed = tomllib.loads(generated)
    except tomllib.TOMLDecodeError as exc:
        raise PreserveError("generated temporary Wrangler config invalid") from exc
    if parsed["vars"] != {**existing_vars, **exact}:
        raise PreserveError("generated Wrangler variables differ from served authoritative values")
    if {k: v for k, v in parsed.items() if k != "vars"} != {
        k: v for k, v in config.items() if k != "vars"
    }:
        raise PreserveError("unrelated Wrangler configuration changed while staging flags")
    return generated


def stage_exact_served_vars(path: Path, version: object, version_id: str) -> None:
    before = path.read_text(encoding="utf-8")
    generated = render_exact_served_flags(before, version, version_id)
    stage_path = path.with_name(path.name + ".b54-staged")
    # Same-dir atomic replace. Runner-local only, no Cloudflare mutation.
    try:
        with stage_path.open("x", encoding="utf-8", newline="\n") as handle:
            os.chmod(stage_path, 0o600)
            handle.write(generated)
        os.replace(stage_path, path)
    finally:
        stage_path.unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--wrangler", required=True)
    p.add_argument("--version-details", required=True)
    p.add_argument("--active-version", required=True)
    p.add_argument("--stage-served-vars", action="store_true")
    args = p.parse_args()
    try:
        version = json.loads(Path(args.version_details).read_text(encoding="utf-8"))
        if args.stage_served_vars:
            stage_exact_served_vars(Path(args.wrangler), version, args.active_version)
        else:
            verify(Path(args.wrangler).read_text(encoding="utf-8"),
                   version, args.active_version)
    except (OSError, ValueError) as exc:
        print("B54_KEEP_LIVE_VARS_PREDEPLOY=FAIL")
        print(f"REASON={exc}")
        print("PRODUCTION_MUTATION=0")
        return 1
    print("B54_KEEP_LIVE_VARS_PREDEPLOY=PASS")
    print("B54_SIX_PLAIN_TEXT_FLAGS_IN_SERVED_VERSION=PASS")
    print("B54_WRANGLER_KEEP_VARS=TRUE")
    print("FEATURE_FLAG_VALUES_READ=" + ("RUNNER_ONLY" if args.stage_served_vars else "0"))
    print("FEATURE_FLAG_VALUES_EMITTED=0")
    if args.stage_served_vars:
        print("B54_SERVED_SIX_FLAGS_STAGED_FOR_DEPLOY=PASS")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
