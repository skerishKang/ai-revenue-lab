#!/usr/bin/env python3
"""Bounded migration: remove ONLY ``b54-kagent`` from the V1 BASE registry.

The overlay secret ``PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY`` is the sole
authority for caller ``b54-kagent``. When the same caller id also exists in
the base registry, the Engine identity authority fails closed with
``duplicate_service_caller`` and every caller is rejected. This script removes
exactly the ``b54-kagent`` entry from the complete base V1 baseline and builds
a PUT body whose target name is structurally fixed to
``PADIEM_ENGINE_CALLER_REGISTRY_V1`` only, so an overlay rewrite is
impossible through this path.

Source contract (fail closed, verified by the focused test suite):

  MIGRATION_TARGET=BASE_V1_ONLY
  TARGET_CALLER=b54-kagent
  REMOVE_EXACTLY_ONE_TARGET_CALLER=YES
  OTHER_CALLERS_PRESERVED=YES
  B61_PRESERVED=YES
  CURRENTNESS_REQUIRED=YES
  RESULT_ENGINE_PARSE_VALID=YES
  RUNTIME_DUPLICATE_REJECTION_UNCHANGED=YES
  OVERLAY_SHADOWING_NOT_ENABLED=YES

The baseline is read from the environment variable named by
``--baseline-env`` and must be proven currently authoritative by the bounded
NON-SECRET attestation named by ``--currentness-env`` (identical contract as
the provisioning gate). Every refusal emits a fixed reason class only. No
baseline plaintext, registry JSON, credential, hash, or unrelated caller id is
ever emitted. The Engine runtime is never imported for mutation and its
duplicate rejection is never weakened: the production
``parse_caller_registry_v1`` is executed READ-ONLY to prove the RESULT parses.

The ``reconfirm`` subcommand closes the cross-job TOCTOU window: immediately
before the PUT, the apply job performs a fresh GET-only served-version read
and this command proves it still matches what the readonly preflight captured
(SAME SINGLE 100% served version, SAME MIGRATION_REQUIRED disposition, SAME
legacy-trio pre-state). Any divergence fails closed with PUT_COUNT=0.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent

_provision_spec = importlib.util.spec_from_file_location(
    "b54_engine_caller_registry_v1_provision",
    _HERE / "b54_engine_caller_registry_v1_provision.py",
)
assert _provision_spec is not None and _provision_spec.loader is not None
_provision = importlib.util.module_from_spec(_provision_spec)
_provision_spec.loader.exec_module(_provision)

_guard_spec = importlib.util.spec_from_file_location(
    "b54_engine_served_version_guard",
    _HERE / "b54_engine_served_version_guard.py",
)
assert _guard_spec is not None and _guard_spec.loader is not None
_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_guard)

_rotation_spec = importlib.util.spec_from_file_location(
    "b54_engine_caller_registry_overlay_rotation",
    _HERE / "b54_engine_caller_registry_overlay_rotation.py",
)
assert _rotation_spec is not None and _rotation_spec.loader is not None
_rotation = importlib.util.module_from_spec(_rotation_spec)
_rotation_spec.loader.exec_module(_rotation)

# Single-source every shared contract; this script re-implements nothing that
# the provisioning, guard, or rotation modules already own.
CALLER_ID = _provision.CALLER_ID
REGISTRY_SECRET_NAME = _provision.REGISTRY_SECRET_NAME
OVERLAY_SECRET_NAME = _rotation.OVERLAY_SECRET_NAME
LEGACY_TRIO_NAMES = _provision.LEGACY_TRIO_NAMES
PROVEN_BINDING_TYPE = "secret_text"
ENGINE_WORKER = "padiem-ai-engine"

parse_baseline_registry = _provision.parse_baseline_registry
assert_baseline_currentness = _provision.assert_baseline_currentness
assert_b61_preserved = _provision._assert_b61_preserved
check_registry_shape = _provision._check_registry_shape
serialized = _provision._serialized
encode_legacy_states = _rotation.encode_legacy_states
decode_legacy_states = _rotation.decode_legacy_states
_version_bindings = _guard._version_bindings
_classify_binding = _guard._classify
ServedVersionGuardError = _guard.ServedVersionGuardError

def _load_engine_identity_enforcement():
    """Load the PRODUCTION parser read-only under its production module name.

    The Engine ``app`` package ``__init__`` pulls in ``padiem_ai_core``, which
    is not installed for CI gate runners. A stub parent package keeps the
    production import name intact while bypassing ``__init__`` entirely, so
    this CLI executes the verbatim production parser the runtime uses.
    """
    if "app" not in sys.modules:
        package = types.ModuleType("app")
        package.__path__ = [str(_ROOT / "apps" / "padiem-ai-engine" / "app")]  # type: ignore[attr-defined]
        sys.modules["app"] = package
    return importlib.import_module("app.identity_enforcement")


_identity_enforcement = _load_engine_identity_enforcement()
parse_caller_registry_v1 = _identity_enforcement.parse_caller_registry_v1


class BaseV1RemovalError(RuntimeError):
    """Fail-closed refusal carrying only a bounded, non-secret reason class."""


def _served_states(version_detail: object, active_version: str) -> dict[str, str]:
    bindings = _version_bindings(version_detail, active_version)
    names = (REGISTRY_SECRET_NAME, OVERLAY_SECRET_NAME, *LEGACY_TRIO_NAMES)
    return {name: _classify_binding(bindings, name) for name in names}


def remove_b54_kagent_from_baseline(payload: dict) -> dict:
    """Return the base registry with EXACTLY ONE ``b54-kagent`` entry removed.

    Refuses when the target is absent, ambiguous (more than one entry), when
    any non-target entry would not be preserved verbatim, when the result
    would be empty, when the B61 contract would break, or when the result
    does not parse with the production Engine parser.
    """
    callers = payload["callers"]
    matches = [entry for entry in callers if entry["caller_id"] == CALLER_ID]
    if not matches:
        raise BaseV1RemovalError("BASE_CONTAINS_B54_KAGENT=NO")
    if len(matches) > 1:
        raise BaseV1RemovalError("BASE_TARGET_CALLER_AMBIGUOUS")
    remaining = [entry for entry in callers if entry["caller_id"] != CALLER_ID]
    if not remaining:
        raise BaseV1RemovalError("BASE_RESULT_WOULD_HAVE_ZERO_CALLERS")
    if len(remaining) != len(callers) - 1:
        raise BaseV1RemovalError("BASE_NON_TARGET_PRESERVATION_FAILED")
    result = {"version": payload["version"], "callers": remaining}
    check_registry_shape(result)
    assert_b61_preserved(result)
    try:
        parse_caller_registry_v1(serialized(result))
    except Exception:
        raise BaseV1RemovalError("BASE_RESULT_ENGINE_PARSE_INVALID") from None
    return result


def plan_removal(baseline: str, currentness: str) -> tuple[dict, dict]:
    """Parse, prove currentness, and remove the target caller from the base."""
    if not baseline or not baseline.strip():
        raise BaseV1RemovalError("BASELINE_MISSING")
    if not currentness or not currentness.strip():
        raise BaseV1RemovalError("CURRENTNESS_ATTESTATION_MISSING")
    payload = parse_baseline_registry(baseline)
    meta = assert_baseline_currentness(baseline, payload, currentness)
    result = remove_b54_kagent_from_baseline(payload)
    return result, meta


def build_put_body(payload: dict) -> dict:
    """PUT body structurally bound to the BASE V1 secret name only."""
    body = _provision.build_put_body(payload)
    if body.get("name") != REGISTRY_SECRET_NAME or body.get("type") != PROVEN_BINDING_TYPE:
        raise BaseV1RemovalError("BASE_PUT_BODY_TARGET_UNSAFE")
    return body


def migration_disposition(states: dict[str, str]) -> str:
    base = states.get(REGISTRY_SECRET_NAME, "ABSENT")
    overlay = states.get(OVERLAY_SECRET_NAME, "ABSENT")
    if base != f"PRESENT:{PROVEN_BINDING_TYPE}":
        return "REFUSE_BASE_UNAVAILABLE"
    if overlay != f"PRESENT:{PROVEN_BINDING_TYPE}":
        return "REFUSE_OVERLAY_ABSENT"
    return "MIGRATION_REQUIRED"


def _read_env(name: str) -> str:
    return os.environ.get(name, "")


def _cmd_plan(args: argparse.Namespace) -> int:
    baseline = _read_env(args.baseline_env)
    currentness = _read_env(args.currentness_env)
    try:
        result, meta = plan_removal(baseline, currentness)
        body = build_put_body(result)
    except (BaseV1RemovalError, _provision.ProvisionPlanError) as exc:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_PLAN=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("CURRENTNESS_REQUIRED=YES", file=sys.stderr)
        print("BASELINE_CURRENTNESS_PROVEN=NO", file=sys.stderr)
        print("OVERLAY_MUTATION=0", file=sys.stderr)
        print("CLOUDFLARE_MUTATION=0", file=sys.stderr)
        print("PRODUCTION_MUTATION=0", file=sys.stderr)
        print("RAW_REGISTRY_JSON_OUTPUT=0", file=sys.stderr)
        print("SECRET_VALUE_OUTPUT=0", file=sys.stderr)
        return 1
    try:
        Path(args.output).write_text(json.dumps(body), encoding="utf-8")
    except OSError:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_PLAN=FAIL", file=sys.stderr)
        print("REASON=OUTPUT_WRITE_FAILED", file=sys.stderr)
        print("PRODUCTION_MUTATION=0", file=sys.stderr)
        return 1
    print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_PLAN=PASS")
    print("MIGRATION_TARGET=BASE_V1_ONLY")
    print(f"TARGET_CALLER={CALLER_ID}")
    print("BASE_CONTAINS_B54_KAGENT=YES")
    print("REMOVE_EXACTLY_ONE_TARGET_CALLER=YES")
    print("OTHER_CALLERS_PRESERVED=YES")
    print("B61_PRESERVED=YES")
    print("CURRENTNESS_REQUIRED=YES")
    print("BASELINE_CURRENTNESS_PROVEN=YES")
    print("BASELINE_CURRENTNESS_FINGERPRINT_BOUND=YES")
    print("CURRENTNESS_ATTESTATION_CONTAINS_SECRET_MATERIAL=NO")
    print("RESULT_ENGINE_PARSE_VALID=YES")
    print("RUNTIME_DUPLICATE_REJECTION_UNCHANGED=YES")
    print("OVERLAY_SHADOWING_NOT_ENABLED=YES")
    print("OVERLAY_MUTATION=0")
    print(f"PUT_TARGET={REGISTRY_SECRET_NAME}")
    print(f"BASELINE_CALLER_COUNT={meta['caller_count']}")
    print(f"RESULT_CALLER_COUNT={len(result['callers'])}")
    print("RAW_REGISTRY_JSON_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("CLOUDFLARE_MUTATION=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.version_detail.read_text(encoding="utf-8"))
        states = _served_states(payload, args.active_version)
    except (OSError, json.JSONDecodeError, ServedVersionGuardError) as exc:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_CLASSIFY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO", file=sys.stderr)
        return 1
    disposition = migration_disposition(states)
    for name in (REGISTRY_SECRET_NAME, OVERLAY_SECRET_NAME):
        print(f"AUTHORITY_STATE {name}={states[name]}")
    print(f"ENGINE_SERVED_VERSION_ID={args.active_version}")
    print(f"B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_DISPOSITION={disposition}")
    print(f"LEGACY_TRIO_PRE_STATE={encode_legacy_states(states)}")
    print("SERVED_VERSION_CLASSIFICATION=YES")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("SECRET_VALUES_READ=0")
    print("RAW_REGISTRY_JSON_OUTPUT=0")
    print("CLOUDFLARE_MUTATION=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def _cmd_reconfirm(args: argparse.Namespace) -> int:
    """Prove the served version is UNCHANGED since the readonly preflight.

    Runs in the apply job immediately before the PUT, on a FRESH GET-only
    deployments -> resolve-active -> versions/{current} read. Git main being
    unchanged is NOT the freshness proof: the Cloudflare worker secret state
    can move between jobs. Any divergence fails closed; this command performs
    no mutation and emits NAME/TYPE evidence only.
    """
    try:
        payload = json.loads(args.version_detail.read_text(encoding="utf-8"))
        states = _served_states(payload, args.active_version)
    except (OSError, json.JSONDecodeError, ServedVersionGuardError) as exc:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_RECONFIRM=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("TOCTOU_SERVED_VERSION_GUARD=FAIL", file=sys.stderr)
        print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO", file=sys.stderr)
        print("PUT_COUNT=0", file=sys.stderr)
        print("OVERLAY_MUTATION=0", file=sys.stderr)
        print("CLOUDFLARE_MUTATION=0", file=sys.stderr)
        print("PRODUCTION_MUTATION=0", file=sys.stderr)
        return 1
    problems: list[str] = []
    if args.active_version != args.pre_active_version:
        problems.append("SERVED_VERSION_CHANGED_AFTER_READONLY_PREFLIGHT")
    if migration_disposition(states) != "MIGRATION_REQUIRED":
        problems.append("SERVED_DISPOSITION_NO_LONGER_MIGRATION_REQUIRED")
    if encode_legacy_states(states) != args.pre_legacy_state:
        problems.append("LEGACY_TRIO_PRE_STATE_DIVERGED_FROM_READONLY_CAPTURE")
    if problems:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_RECONFIRM=FAIL", file=sys.stderr)
        for problem in problems:
            print(f"REASON={problem}", file=sys.stderr)
        print("TOCTOU_SERVED_VERSION_GUARD=FAIL", file=sys.stderr)
        print("PUT_COUNT=0", file=sys.stderr)
        print("OVERLAY_MUTATION=0", file=sys.stderr)
        print("CLOUDFLARE_MUTATION=0", file=sys.stderr)
        print("PRODUCTION_MUTATION=0", file=sys.stderr)
        print("RAW_REGISTRY_JSON_OUTPUT=0", file=sys.stderr)
        print("SECRET_VALUES_READ=0", file=sys.stderr)
        return 1
    print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_RECONFIRM=PASS")
    print(f"PRE_ACTIVE_VERSION_ID={args.pre_active_version}")
    print(f"CURRENT_ACTIVE_VERSION_ID={args.active_version}")
    print("SERVED_VERSION_UNCHANGED=YES")
    print("PREWRITE_DISPOSITION=MIGRATION_REQUIRED")
    print("LEGACY_TRIO_PRE_STATE_CONFIRMED=YES")
    print("TOCTOU_SERVED_VERSION_GUARD=PASS")
    print("PRE_MUTATION_STATE_SERVED_VERSION=YES")
    print("SINGLE_100_PERCENT_SERVED_VERSION_GUARD=PASS")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("SECRET_VALUES_READ=0")
    print("RAW_REGISTRY_JSON_OUTPUT=0")
    print("PUT_COUNT=0")
    print("OVERLAY_MUTATION=0")
    print("CLOUDFLARE_MUTATION=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.version_detail.read_text(encoding="utf-8"))
        states = _served_states(payload, args.active_version)
        pre_legacy = decode_legacy_states(args.legacy_pre_state)
    except (
        OSError,
        json.JSONDecodeError,
        BaseV1RemovalError,
        ServedVersionGuardError,
        _rotation.OverlayRotationError,
    ) as exc:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_VERIFY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("SECRET_VALUES_READ=0", file=sys.stderr)
        return 1
    expected = f"PRESENT:{PROVEN_BINDING_TYPE}"
    problems: list[str] = []
    if states.get(REGISTRY_SECRET_NAME) != expected:
        problems.append(f"{REGISTRY_SECRET_NAME} is not {expected} on the served version")
    if states.get(OVERLAY_SECRET_NAME) != expected:
        problems.append(f"{OVERLAY_SECRET_NAME} is not {expected} on the served version")
    for name in LEGACY_TRIO_NAMES:
        if states.get(name, "ABSENT") != pre_legacy[name]:
            problems.append(f"legacy trio state changed: {name}")
    if problems:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_VERIFY=FAIL", file=sys.stderr)
        print(f"REASON={'; '.join(problems)}", file=sys.stderr)
        print("PRODUCTION_MUTATION=1", file=sys.stderr)
        return 1
    print(f"ENGINE_SERVED_VERSION_ID={args.active_version}")
    print(f"ENGINE_V1_SERVED_BINDING={states[REGISTRY_SECRET_NAME]}")
    print(f"ENGINE_OVERLAY_SERVED_BINDING={states[OVERLAY_SECRET_NAME]}")
    print(f"LEGACY_TRIO_SERVED_STATE={encode_legacy_states(states)}")
    print("MIGRATION_TARGET=BASE_V1_ONLY")
    print("OVERLAY_PRESERVED=YES")
    print("OVERLAY_MUTATION=0")
    print("LEGACY_TRIO_PRESERVATION=YES")
    print("SERVED_VERSION_READBACK=YES")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_POST_READBACK=PASS")
    print("UNRELATED_SECRET_MUTATION=0")
    print("RAW_REGISTRY_JSON_OUTPUT=0")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("RUNTIME_SUCCESS=UNPROVEN_PENDING_PHASE_A")
    print("PRODUCTION_MUTATION=1")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="b54_engine_caller_registry_base_v1_b54_kagent_removal.py"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="build the bounded base V1 removal PUT body")
    plan.add_argument("--baseline-env", default="B54_ENGINE_CALLER_REGISTRY_V1_BASELINE")
    plan.add_argument(
        "--currentness-env",
        default="B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS",
    )
    plan.add_argument("--output", required=True, help="PUT body output path")
    plan.set_defaults(handler=_cmd_plan)

    classify = sub.add_parser(
        "classify", help="classify NAME/TYPE states on the SERVED version"
    )
    classify.add_argument("--version-detail", required=True, type=Path)
    classify.add_argument("--active-version", required=True)
    classify.set_defaults(handler=_cmd_classify)

    reconfirm = sub.add_parser(
        "reconfirm",
        help="prove the freshly read served version still matches the readonly "
        "preflight capture immediately before the PUT (TOCTOU guard)",
    )
    reconfirm.add_argument("--version-detail", required=True, type=Path)
    reconfirm.add_argument("--active-version", required=True)
    reconfirm.add_argument("--pre-active-version", required=True)
    reconfirm.add_argument("--pre-legacy-state", required=True)
    reconfirm.set_defaults(handler=_cmd_reconfirm)

    verify = sub.add_parser("verify", help="verify the served version after the PUT")
    verify.add_argument("--version-detail", required=True, type=Path)
    verify.add_argument("--active-version", required=True)
    verify.add_argument("--legacy-pre-state", required=True)
    verify.set_defaults(handler=_cmd_verify)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
