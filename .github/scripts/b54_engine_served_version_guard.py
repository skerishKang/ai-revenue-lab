#!/usr/bin/env python3
"""Fail-closed served-version caller-registry guard for padiem-ai-engine.

Validates the caller-registry secrets on the *actually served* Worker version
(the version identified by the deployments API), not the mutable settings plane.
Consumes bounded Cloudflare API GET responses saved to disk by the deploy gate:

- ``resolve-active``: extract the active version id from a deployments GET body.
- ``verify``: assert ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` (and the overlay
  secret when expected) are ``PRESENT:secret_text`` on that exact version.

Emits NAME/TYPE state only. Never reads or prints any binding value, raw
settings JSON, or the Cloudflare account id. Performs no mutation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REGISTRY_SECRET_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY_SECRET_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"
REQUIRED_BINDING_TYPE = "secret_text"

# Version ids are echoed to stdout/GITHUB_ENV; keep them to a safe charset.
_VERSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class ServedVersionGuardError(RuntimeError):
    pass


def _load(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError:
        raise ServedVersionGuardError("payload file could not be read")
    except json.JSONDecodeError:
        raise ServedVersionGuardError("payload file is not valid JSON")


def _success_result(payload: object, what: str) -> object:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ServedVersionGuardError(f"{what} response is not successful")
    return payload.get("result")


def _version_id_of(entry: dict) -> str:
    raw = entry.get("version_id")
    if not isinstance(raw, str):
        raw = entry.get("id")
    if not isinstance(raw, str) or not _VERSION_ID_RE.match(raw):
        raise ServedVersionGuardError("active version id is missing or unsafe")
    return raw


def _pick_active(versions: list, *, source: str) -> str:
    if not versions:
        raise ServedVersionGuardError(f"no active version in {source}")
    if not all(isinstance(v, dict) for v in versions):
        raise ServedVersionGuardError(f"{source} array is malformed")
    full = [v for v in versions if v.get("percentage") == 100]
    if not full:
        raise ServedVersionGuardError(f"no version at 100 percent in {source}")
    if len(full) > 1:
        raise ServedVersionGuardError(f"ambiguous active version in {source}")
    return _version_id_of(full[0])


def resolve_active(payload: object) -> str:
    """Return the single 100-percent served version id from a deployments body.

    Accepts the raw wrangler list (oldest-first deployments), the canonical
    ``result.deployments`` shape, and a ``result.versions`` shape. Fails closed
    on empty, ambiguous, or malformed input.
    """
    if isinstance(payload, list):
        if not payload:
            raise ServedVersionGuardError("deployments list is empty")
        last = payload[-1]
        if not isinstance(last, dict):
            raise ServedVersionGuardError("latest deployment entry is malformed")
        versions = last.get("versions")
        if not isinstance(versions, list):
            raise ServedVersionGuardError("latest deployment versions array is malformed")
        return _pick_active(versions, source="latest deployment")

    result = _success_result(payload, "deployments")
    if isinstance(result, dict):
        if isinstance(result.get("versions"), list):
            return _pick_active(result["versions"], source="result versions")
        deployments = result.get("deployments")
        if not isinstance(deployments, list):
            raise ServedVersionGuardError("deployments result is malformed")
        if not deployments:
            raise ServedVersionGuardError("deployments list is empty")
        first = deployments[0]
        if not isinstance(first, dict):
            raise ServedVersionGuardError("active deployment entry is malformed")
        versions = first.get("versions")
        if not isinstance(versions, list):
            raise ServedVersionGuardError("active deployment versions array is malformed")
        return _pick_active(versions, source="active deployment")
    if isinstance(result, list):
        if not result:
            raise ServedVersionGuardError("deployments list is empty")
        last = result[-1]
        if not isinstance(last, dict):
            raise ServedVersionGuardError("latest deployment entry is malformed")
        versions = last.get("versions")
        if not isinstance(versions, list):
            raise ServedVersionGuardError("latest deployment versions array is malformed")
        return _pick_active(versions, source="latest deployment")
    raise ServedVersionGuardError("deployments result is malformed")


def _version_bindings(payload: object, active_version: str) -> list[dict]:
    """Return the served version bindings, proving version identity first.

    A settings-plane payload without a version tag is rejected here, so a
    settings-only readback can never pass as served-version validation.
    """
    result = _success_result(payload, "version settings")
    if isinstance(result, list):
        if len(result) != 1 or not isinstance(result[0], dict):
            raise ServedVersionGuardError("version settings result is malformed")
        result = result[0]
    if not isinstance(result, dict):
        raise ServedVersionGuardError("version settings result is malformed")

    identity = result.get("tag")
    if not isinstance(identity, str):
        identity = result.get("version_id")
    if not isinstance(identity, str) or not identity.strip():
        raise ServedVersionGuardError("served version identity unproven")
    if not _VERSION_ID_RE.match(identity):
        raise ServedVersionGuardError("version tag is unsafe")
    if identity != active_version:
        raise ServedVersionGuardError("version settings tag does not match active version")

    bindings = result.get("bindings")
    if bindings is None and isinstance(result.get("settings"), dict):
        bindings = result["settings"].get("bindings")
    if not isinstance(bindings, list) or not all(isinstance(b, dict) for b in bindings):
        raise ServedVersionGuardError("served version bindings array is malformed")
    return bindings


def _classify(bindings: list[dict], name: str) -> str:
    matches = [b for b in bindings if b.get("name") == name]
    if len(matches) > 1:
        raise ServedVersionGuardError(f"duplicate binding name on served version: {name}")
    if not matches:
        return "ABSENT"
    binding_type = matches[0].get("type")
    if not isinstance(binding_type, str) or not binding_type.strip():
        raise ServedVersionGuardError(f"binding has no valid type: {name}")
    return f"PRESENT:{binding_type.strip()}"


def verify_served(payload: object, active_version: str, expect_overlay: bool) -> dict[str, str]:
    """Return NAME -> state for the registry and overlay secrets on the version.

    Fails closed on: unproven version identity, version tag mismatch, duplicate
    binding names, missing V1, expected overlay missing, and any type drift.
    """
    if not _VERSION_ID_RE.match(active_version):
        raise ServedVersionGuardError("active version id is unsafe")
    bindings = _version_bindings(payload, active_version)

    registry = _classify(bindings, REGISTRY_SECRET_NAME)
    overlay = _classify(bindings, OVERLAY_SECRET_NAME)

    if registry != f"PRESENT:{REQUIRED_BINDING_TYPE}":
        raise ServedVersionGuardError(
            f"served version registry binding is not {REQUIRED_BINDING_TYPE}: {registry}"
        )
    if overlay not in ("ABSENT", f"PRESENT:{REQUIRED_BINDING_TYPE}"):
        raise ServedVersionGuardError(
            f"served version overlay binding is not {REQUIRED_BINDING_TYPE}: {overlay}"
        )
    if overlay == "ABSENT" and expect_overlay:
        raise ServedVersionGuardError("expected overlay binding is missing on served version")

    overlay_state = overlay if overlay != "ABSENT" else "NOT_EXPECTED"
    return {
        "ENGINE_V1_SERVED_BINDING": registry,
        "ENGINE_OVERLAY_SERVED_BINDING": overlay_state,
        "B54_ENGINE_OVERLAY_EXPECTED": "YES" if overlay != "ABSENT" else "NO",
    }


def _run_resolve(args: argparse.Namespace) -> int:
    version_id = resolve_active(_load(args.deployments))
    print("ENGINE_ACTIVE_VERSION_IDENTIFIED=PASS")
    print(f"ENGINE_ACTIVE_VERSION_ID={version_id}")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("RAW_SECRET_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    states = verify_served(_load(args.version_settings), args.active_version, args.expect_overlay)
    print("B54_ENGINE_SERVED_VERSION_GUARD=PASS")
    print(f"ENGINE_SERVED_VERSION_ID={args.active_version}")
    for key in ("ENGINE_V1_SERVED_BINDING", "ENGINE_OVERLAY_SERVED_BINDING", "B54_ENGINE_OVERLAY_EXPECTED"):
        print(f"{key}={states[key]}")
    print("SERVED_VERSION_SECRET_SET_VALIDATION=YES")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("RAW_BINDING_VALUE_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("RAW_SECRET_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="b54_engine_served_version_guard.py")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve-active", help="extract the served version id")
    resolve.add_argument("--deployments", required=True, help="deployments GET response JSON file")
    resolve.set_defaults(handler=_run_resolve)

    verify = sub.add_parser("verify", help="assert registry secrets on the served version")
    verify.add_argument("--version-settings", required=True, help="version settings GET response JSON file")
    verify.add_argument("--active-version", required=True, help="expected served version id")
    verify.add_argument(
        "--expect-overlay",
        action="store_true",
        help="require the overlay secret to be present on the served version",
    )
    verify.set_defaults(handler=_run_verify)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except ServedVersionGuardError as exc:
        print("B54_ENGINE_SERVED_VERSION_GUARD=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
