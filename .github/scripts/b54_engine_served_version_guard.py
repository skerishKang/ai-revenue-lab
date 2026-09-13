#!/usr/bin/env python3
"""Fail-closed served-version caller-registry guard for padiem-ai-engine.

Validates the caller-registry secrets on the *actually served* Worker version
(the version identified by the deployments API), not the mutable settings plane.
Consumes bounded Cloudflare API GET responses saved to disk by the deploy gate:

- ``resolve-active``: extract the active version id from a deployments GET body.
- ``verify``: assert ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` (and the overlay
  secret when expected) are ``PRESENT:secret_text`` on that exact version.

Version-detail parsing follows the documented Cloudflare response authority:
identity is ``result.id`` and bindings are ``result.resources.bindings``
(list or name-keyed map). Settings-plane payloads are never accepted as
served-version proof.

``resolve-active`` accepts ONLY the canonical Cloudflare deployments envelope,
converged under #2452 with the #2427 B62 contract: object ``result``, active
deployment ``result.deployments[0]``, exactly one version at 100 percent, safe
``version_id``. Raw top-level lists, list-shaped ``result`` values, and the
``result.versions`` shortcut are refused with no ordering fallback.

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
    """Return the served version id of an active-deployment version entry.

    The deployments history shape names the field ``version_id``; a bare ``id``
    is a version-list/detail field and is not accepted here, so a payload from
    an endpoint other than ``/deployments`` can never resolve as served version.
    """
    raw = entry.get("version_id")
    if not isinstance(raw, str) or not _VERSION_ID_RE.match(raw):
        raise ServedVersionGuardError("active version id is missing or unsafe")
    return raw


def resolve_active(payload: object) -> str:
    """Return the served version id from a canonical Cloudflare deployments envelope.

    Contract (converged with the #2427 B62 canonical resolver under #2452):

    - input is a successful Cloudflare API envelope with an object ``result``;
    - the active deployment is ``result.deployments[0]`` — the endpoint returns
      deployment history and documents the first entry as the latest deployment
      actively serving traffic, so later entries are previous deployments and
      are not ambiguity;
    - that deployment serves exactly one version, at 100 percent traffic;
    - the version id must be present and carry a safe charset.

    Refused, with no ordering guess and no fallback: a raw top-level list (the
    wrangler CLI shape, whose entry order is not a documented served-version
    authority), a list-shaped ``result``, and a ``result.versions`` shortcut.
    Each of those can resolve a stale version as served — a descending
    (newest-first) raw list makes any last-entry rule pick the oldest deployment.
    A caller that holds wrangler raw-list output must convert it behind an
    explicitly named adapter with its own ordering contract before it reaches
    this resolver; no repository caller does today.

    Fails closed on empty, ambiguous, or malformed input. Performs no mutation
    and reads no binding value.
    """
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ServedVersionGuardError(
            "deployments payload is not a successful Cloudflare API envelope"
        )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ServedVersionGuardError(
            "ambiguous active deployment: deployments payload has no result object"
        )
    deployments = result.get("deployments")
    if not isinstance(deployments, list) or not deployments:
        raise ServedVersionGuardError(
            "ambiguous active deployment: no deployment records returned"
        )
    first = deployments[0]
    if not isinstance(first, dict):
        raise ServedVersionGuardError(
            "ambiguous active deployment: deployment entry is not an object"
        )
    versions = first.get("versions")
    if not isinstance(versions, list) or len(versions) != 1:
        raise ServedVersionGuardError(
            "ambiguous active deployment: expected exactly one served version"
        )
    entry = versions[0]
    if not isinstance(entry, dict):
        raise ServedVersionGuardError(
            "ambiguous active deployment: served version entry is not an object"
        )
    if entry.get("percentage") != 100:
        raise ServedVersionGuardError(
            "ambiguous active deployment: served version traffic split is not 100"
        )
    return _version_id_of(entry)


def _binding_entries(bindings: object) -> list[dict]:
    """Normalize the documented bindings collection (list or name-keyed map).

    A name-keyed map is tolerated only when each entry's own ``name`` (if
    present) agrees with its key, so normalization can never invent or mask a
    binding identity.
    """
    if isinstance(bindings, list):
        for raw in bindings:
            if not isinstance(raw, dict):
                raise ServedVersionGuardError("served version bindings array is malformed")
        return list(bindings)
    if isinstance(bindings, dict):
        entries: list[dict] = []
        for name, raw in bindings.items():
            if not isinstance(raw, dict):
                raise ServedVersionGuardError(f"served binding {name!r} metadata is malformed")
            if isinstance(raw.get("name"), str) and raw["name"] != name:
                raise ServedVersionGuardError(
                    f"served binding key {name!r} disagrees with its entry name"
                )
            entries.append({**raw, "name": name})
        return entries
    raise ServedVersionGuardError("served version bindings collection is missing or malformed")


def _version_bindings(payload: object, active_version: str) -> list[dict]:
    """Return the served version bindings, proving version identity first.

    Canonical documented version-detail shape: identity is ``result.id`` and
    bindings are ``result.resources.bindings``. A settings-plane payload is
    rejected here, so a settings-only readback can never pass as
    served-version validation.
    """
    result = _success_result(payload, "version detail")
    if not isinstance(result, dict):
        raise ServedVersionGuardError("version detail result is malformed")

    identity = result.get("id")
    if not isinstance(identity, str) or not identity.strip():
        raise ServedVersionGuardError("served version identity unproven")
    if not _VERSION_ID_RE.match(identity):
        raise ServedVersionGuardError("version id is unsafe")
    if identity != active_version:
        raise ServedVersionGuardError("version detail id does not match active version")

    resources = result.get("resources")
    if not isinstance(resources, dict):
        raise ServedVersionGuardError("version detail has no resources object")
    return _binding_entries(resources.get("bindings"))


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

    Fails closed on: unproven version identity, version id mismatch, duplicate
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
    verify.add_argument("--version-settings", required=True, help="version detail GET response JSON file")
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
