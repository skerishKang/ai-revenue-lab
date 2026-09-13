#!/usr/bin/env python3
"""Prove the complete secret binding set on the actually served B62 Worker version.

The settings plane is not proof of what a version serves, so this guard resolves
the served version id from the deployment record and reads the binding metadata
from the version detail endpoint. Only binding names and types are compared;
secret values are never read, copied, or emitted. The guard fails closed on an
ambiguous active deployment, a missing served version id, a version detail that
does not match the served version, duplicate binding names, a missing required
secret, type drift, the loss of any pre-existing secret, and unexpected
additions to the served secret set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SECRET_TYPE = "secret_text"
REQUIRED_SECRETS = {
    "PADIEM_CHAT_QUOTA_SALT": SECRET_TYPE,
    "P01_ENGINE_CREDENTIAL": SECRET_TYPE,
}
CAPTURE_SCHEMA = "b62-served-version-secret-set/v1"


class ServedVersionGuardError(RuntimeError):
    pass


def _success_result(payload: object, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ServedVersionGuardError(f"{label} is not a successful Cloudflare API response")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ServedVersionGuardError(f"{label} has no result object")
    return result


def resolve_served_version_id(deployments_payload: object) -> str:
    """Return the 100%-traffic served version id of the active deployment or fail closed.

    The Cloudflare deployments endpoint returns deployment history and documents
    that the first entry is the latest deployment actively serving traffic, so
    later entries are previous deployments and are not ambiguity.
    """
    result = _success_result(deployments_payload, "deployments payload")
    deployments = result.get("deployments")
    if not isinstance(deployments, list) or len(deployments) == 0:
        raise ServedVersionGuardError("ambiguous active deployment: no deployment records returned")
    first = deployments[0]
    if not isinstance(first, dict):
        raise ServedVersionGuardError("ambiguous active deployment: deployment entry is not an object")
    versions = first.get("versions")
    if not isinstance(versions, list) or len(versions) != 1:
        raise ServedVersionGuardError("ambiguous active deployment: expected exactly one served version")
    entry = versions[0]
    if not isinstance(entry, dict):
        raise ServedVersionGuardError("ambiguous active deployment: served version entry is not an object")
    if entry.get("percentage") != 100:
        raise ServedVersionGuardError("ambiguous active deployment: served version traffic split is not 100")
    version_id = entry.get("version_id")
    if not isinstance(version_id, str) or not version_id.strip():
        raise ServedVersionGuardError("served version id is missing")
    return version_id


def _binding_entries(bindings: object) -> list[dict]:
    """Normalize the version-detail bindings shape (name-keyed map or list)."""
    if isinstance(bindings, dict):
        entries: list[dict] = []
        for name, raw in bindings.items():
            if not isinstance(raw, dict):
                raise ServedVersionGuardError(f"served binding {name!r} metadata is not an object")
            if isinstance(raw.get("name"), str) and raw["name"] != name:
                raise ServedVersionGuardError(
                    f"served binding key {name!r} disagrees with its entry name"
                )
            entries.append({**raw, "name": name})
        return entries
    if isinstance(bindings, list):
        for raw in bindings:
            if not isinstance(raw, dict):
                raise ServedVersionGuardError("served binding entry is not an object")
        return list(bindings)
    raise ServedVersionGuardError("version detail has no served bindings collection")


def served_version_bindings(version_detail_payload: object, *, expected_version_id: str) -> list[dict]:
    """Return the served version binding metadata, verified to be the served version."""
    result = _success_result(version_detail_payload, "version detail payload")
    detail_id = result.get("id")
    if detail_id != expected_version_id:
        raise ServedVersionGuardError(
            "version detail id does not match the served version id"
        )
    resources = result.get("resources")
    if not isinstance(resources, dict):
        raise ServedVersionGuardError("version detail has no resources object")
    bindings = _binding_entries(resources.get("bindings"))
    names: list[str] = []
    for raw in bindings:
        name = raw.get("name")
        kind = raw.get("type")
        if not isinstance(name, str) or not name:
            raise ServedVersionGuardError("served binding without a usable name")
        if not isinstance(kind, str) or not kind:
            raise ServedVersionGuardError(f"served binding {name!r} without a usable type")
        names.append(name)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ServedVersionGuardError(f"duplicate binding names: {', '.join(duplicates)}")
    return bindings


def secret_name_type_set(bindings: list[dict]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(
        (raw["name"], raw["type"]) for raw in bindings if raw.get("type") == SECRET_TYPE
    ))


def _type_by_name(bindings: list[dict]) -> dict[str, str]:
    return {raw["name"]: raw["type"] for raw in bindings}


def require_required_secrets(bindings: list[dict], *, stage: str) -> None:
    actual = _type_by_name(bindings)
    for name, kind in sorted(REQUIRED_SECRETS.items()):
        found = actual.get(name)
        if found is None:
            raise ServedVersionGuardError(f"{stage}: required secret absent from served version: {name}")
        if found != kind:
            raise ServedVersionGuardError(
                f"{stage}: required secret type drift: {name} is {found!r}, expected {kind!r}"
            )


def build_capture(version_id: str, bindings: list[dict]) -> dict:
    return {
        "schema": CAPTURE_SCHEMA,
        "version_id": version_id,
        "secrets": [
            {"name": name, "type": kind} for name, kind in secret_name_type_set(bindings)
        ],
    }


def load_capture(payload: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(payload, dict) or payload.get("schema") != CAPTURE_SCHEMA:
        raise ServedVersionGuardError("expected capture is not a served-version secret set capture")
    secrets = payload.get("secrets")
    if not isinstance(secrets, list):
        raise ServedVersionGuardError("expected capture has no secrets array")
    entries: list[tuple[str, str]] = []
    for raw in secrets:
        if not isinstance(raw, dict) or set(raw) != {"name", "type"}:
            raise ServedVersionGuardError(
                "expected capture entries must carry the binding name and type only"
            )
        name = raw["name"]
        kind = raw["type"]
        if not isinstance(name, str) or not name or not isinstance(kind, str) or not kind:
            raise ServedVersionGuardError("expected capture entry has an unusable name or type")
        entries.append((name, kind))
    if len(entries) != len(set(entries)):
        raise ServedVersionGuardError("duplicate entries in expected capture")
    return tuple(sorted(entries))


def verify_secret_set(expected: tuple[tuple[str, str], ...], post_bindings: list[dict]) -> None:
    require_required_secrets(post_bindings, stage="post-deploy")
    post = secret_name_type_set(post_bindings)
    post_types = _type_by_name(post_bindings)
    pre_names = {name for name, _ in expected}
    post_names = {name for name, _ in post}
    problems: list[str] = []
    for name in sorted(pre_names - post_names):
        drifted = post_types.get(name)
        if drifted is not None:
            problems.append(f"type drift: {name} is {drifted!r} on the served version")
        else:
            problems.append(f"missing pre-existing secret: {name}")
    for name in sorted(post_names - pre_names):
        problems.append(f"unexpected new secret: {name}")
    if not problems and expected != post:
        problems.append("secret name/type set differs from the pre-deploy served version")
    if problems:
        raise ServedVersionGuardError("; ".join(problems))


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServedVersionGuardError(f"cannot read payload: {exc}") from exc


def _emit_required_present(bindings: list[dict]) -> None:
    for name in sorted(REQUIRED_SECRETS):
        print(f"{name}=PRESENT:{REQUIRED_SECRETS[name]}")


def _run_capture(args: argparse.Namespace) -> int:
    deployments = _load(args.deployments)
    detail = _load(args.version_detail)
    version_id = resolve_served_version_id(deployments)
    bindings = served_version_bindings(detail, expected_version_id=version_id)
    require_required_secrets(bindings, stage="pre-deploy")
    capture = build_capture(version_id, bindings)
    if args.output.exists():
        raise ServedVersionGuardError("capture output path already exists")
    args.output.write_text(json.dumps(capture, separators=(",", ":")), encoding="utf-8")
    print(f"PREDEPLOY_SERVED_VERSION_ID={version_id}")
    print(f"PREDEPLOY_SERVED_SECRET_COUNT={len(capture['secrets'])}")
    _emit_required_present(bindings)
    print("PREDEPLOY_SERVED_SECRET_SET=CAPTURED")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    expected = load_capture(_load(args.expected))
    deployments = _load(args.deployments)
    detail = _load(args.version_detail)
    version_id = resolve_served_version_id(deployments)
    bindings = served_version_bindings(detail, expected_version_id=version_id)
    verify_secret_set(expected, bindings)
    print(f"POSTDEPLOY_SERVED_VERSION_ID={version_id}")
    print(f"POSTDEPLOY_SERVED_SECRET_COUNT={len(secret_name_type_set(bindings))}")
    _emit_required_present(bindings)
    print("SERVED_VERSION_SECRET_SET_EQUALITY=PASS")
    print("B62_SERVED_VERSION_SECRET_SET=PRESERVED")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="record the pre-deploy served version secret set")
    capture.add_argument("--deployments", required=True, type=Path)
    capture.add_argument("--version-detail", required=True, type=Path)
    capture.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify", help="prove the post-deploy served version kept every secret")
    verify.add_argument("--expected", required=True, type=Path)
    verify.add_argument("--deployments", required=True, type=Path)
    verify.add_argument("--version-detail", required=True, type=Path)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "capture":
            return _run_capture(args)
        return _run_verify(args)
    except ServedVersionGuardError as exc:
        print("B62_SERVED_VERSION_SECRET_SET=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("SECRET_VALUES_READ=0", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
