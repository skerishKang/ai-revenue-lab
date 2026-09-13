#!/usr/bin/env python3
"""Classify and plan the B62 Claw live configuration activation without touching secrets.

The live Cloudflare Worker settings dump is the only input. The helper never
reads, writes, or emits secret values: unchanged bindings (including every
secret) are carried into the activation patch as ``inherit``/``latest``
references, exactly like the merged control-plane identity binding gate.
Anything structurally unexpected fails closed so no live binding can be
silently dropped, retyped, or rewired by this activation.

The bounded replacement path (#2428) additionally gates a source credential
that will replace an EXISTING ``P01_ENGINE_CREDENTIAL`` secret. The quality
gate reports only bounded presence/quality evidence over the UTF-8 byte
length; the value, its length, and any digest are never emitted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "b62_cloudflare_production_deploy_config", _HERE / "b62_cloudflare_production_deploy_config.py"
)
assert _spec is not None and _spec.loader is not None
_deploy_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_deploy_config)
parse_live_bindings = _deploy_config.parse_live_bindings

_guard_spec = importlib.util.spec_from_file_location(
    "b62_binding_state_guard", _HERE / "b62_binding_state_guard.py"
)
assert _guard_spec is not None and _guard_spec.loader is not None
_binding_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_binding_guard)
canonical_binding = _binding_guard.canonical_binding

WORKER = "padiem-chat"

QUOTA_VALUES = {
    "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT": "20",
    "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT": "1000000",
    "PADIEM_CHAT_USER_BURST_LIMIT": "40",
    "PADIEM_CHAT_USER_DAILY_LIMIT": "1000000",
    "PADIEM_CHAT_GLOBAL_DAILY_LIMIT": "10000",
}
R2_BINDING_NAME = "PADIEM_WORKSPACE_FILES"
P01_SERVICE_NAME = "P01_ENGINE_SERVICE"
P01_CALLER_NAME = "P01_ENGINE_CALLER_ID"
P01_CALLER_VALUE = "b54-kagent"
P01_CREDENTIAL_NAME = "P01_ENGINE_CREDENTIAL"

# Bounded source-credential replacement gate (#2428). These thresholds mirror
# the runtime authority in apps/padiem-chat/app/worker_config.py
# (_P01_CREDENTIAL_MIN_BYTES/_P01_CREDENTIAL_MAX_BYTES) and are validated
# against it by a network-free contract test.
P01_CREDENTIAL_MIN_BYTES = 32
P01_CREDENTIAL_MAX_BYTES = 512
SOURCE_CREDENTIAL_ENV = "B62_P01_ENGINE_CREDENTIAL"

TARGET_NAMES = frozenset(QUOTA_VALUES) | {
    R2_BINDING_NAME,
    P01_SERVICE_NAME,
    P01_CALLER_NAME,
    P01_CREDENTIAL_NAME,
}


class ActivationPlanError(RuntimeError):
    pass


def _raw_bindings(settings_payload: object) -> list[dict]:
    """Validate the payload through the deploy-config authority and return raw bindings."""
    parse_live_bindings(settings_payload)
    result = settings_payload["result"]  # validated by parse_live_bindings
    return result["bindings"]


def classify_live_config(
    settings_payload: object,
    *,
    engine_service_name: str,
    r2_bucket_name: str,
) -> dict[str, str]:
    """Return a per-target state map over exact/missing/drift/wrong_type."""
    if not engine_service_name:
        raise ActivationPlanError("engine service name input is required")
    if not r2_bucket_name:
        raise ActivationPlanError("r2 bucket name input is required")
    by_name = {binding["name"]: binding for binding in _raw_bindings(settings_payload)}
    states: dict[str, str] = {}

    for name, expected in QUOTA_VALUES.items():
        binding = by_name.get(name)
        if binding is None:
            states[name] = "missing"
        elif binding.get("type") != "plain_text":
            states[name] = "wrong_type"
        elif binding.get("text") != expected:
            states[name] = "drift"
        else:
            states[name] = "exact"

    r2 = by_name.get(R2_BINDING_NAME)
    if r2 is None:
        states[R2_BINDING_NAME] = "missing"
    elif r2.get("type") != "r2_bucket":
        states[R2_BINDING_NAME] = "wrong_type"
    elif r2.get("bucket_name") != r2_bucket_name:
        states[R2_BINDING_NAME] = "drift"
    else:
        states[R2_BINDING_NAME] = "exact"

    service = by_name.get(P01_SERVICE_NAME)
    if service is None:
        states[P01_SERVICE_NAME] = "missing"
    elif service.get("type") != "service":
        states[P01_SERVICE_NAME] = "wrong_type"
    elif service.get("service") != engine_service_name:
        states[P01_SERVICE_NAME] = "drift"
    else:
        states[P01_SERVICE_NAME] = "exact"

    caller = by_name.get(P01_CALLER_NAME)
    if caller is None:
        states[P01_CALLER_NAME] = "missing"
    elif caller.get("type") != "plain_text":
        states[P01_CALLER_NAME] = "wrong_type"
    elif caller.get("text") != P01_CALLER_VALUE:
        states[P01_CALLER_NAME] = "drift"
    else:
        states[P01_CALLER_NAME] = "exact"

    credential = by_name.get(P01_CREDENTIAL_NAME)
    if credential is None:
        states[P01_CREDENTIAL_NAME] = "missing_secret"
    elif credential.get("type") != "secret_text":
        states[P01_CREDENTIAL_NAME] = "wrong_type"
    else:
        states[P01_CREDENTIAL_NAME] = "exact"

    return states


def disposition(states: dict[str, str]) -> str:
    """Aggregate per-target states into the gate disposition."""
    if any(state == "wrong_type" for state in states.values()):
        return "REFUSE_WRONG_TYPE"
    if any(
        name in (R2_BINDING_NAME, P01_SERVICE_NAME) and state == "drift"
        for name, state in states.items()
    ):
        return "REFUSE_TARGET_DRIFT"
    if any(state in {"missing", "missing_secret", "drift"} for state in states.values()):
        return "ACTIVATION_REQUIRED"
    return "ALREADY_EXACT"


def build_activation_patch(
    settings_payload: object,
    *,
    engine_service_name: str,
    r2_bucket_name: str,
    target_sha: str,
) -> dict:
    """Build the minimal settings patch; refuse on any unapproved structural change."""
    states = classify_live_config(
        settings_payload,
        engine_service_name=engine_service_name,
        r2_bucket_name=r2_bucket_name,
    )
    overall = disposition(states)
    if overall.startswith("REFUSE"):
        refused = sorted(name for name, state in states.items() if state in {"wrong_type", "drift"})
        raise ActivationPlanError(
            f"{overall}: refusing to overwrite live targets: {', '.join(refused)}"
        )

    bindings = _raw_bindings(settings_payload)
    patch_bindings: list[dict] = []
    changes: list[str] = []
    credential_create_required = False

    for binding in bindings:
        name = binding["name"]
        if name not in TARGET_NAMES or states[name] == "exact":
            patch_bindings.append({"name": name, "type": "inherit", "version_id": "latest"})

    for name in sorted(TARGET_NAMES):
        state = states[name]
        if state == "exact":
            continue
        if name in QUOTA_VALUES:
            patch_bindings.append({"name": name, "type": "plain_text", "text": QUOTA_VALUES[name]})
            changes.append("QUOTA_SET" if state == "drift" else "QUOTA_ADD")
        elif name == R2_BINDING_NAME:
            patch_bindings.append(
                {"name": name, "type": "r2_bucket", "bucket_name": r2_bucket_name}
            )
            changes.append("R2_ADD")
        elif name == P01_SERVICE_NAME:
            patch_bindings.append({"name": name, "type": "service", "service": engine_service_name})
            changes.append("P01_SERVICE_ADD")
        elif name == P01_CALLER_NAME:
            patch_bindings.append({"name": name, "type": "plain_text", "text": P01_CALLER_VALUE})
            changes.append("P01_CALLER_SET" if state == "drift" else "P01_CALLER_ADD")
        elif name == P01_CREDENTIAL_NAME:
            credential_create_required = True
            changes.append("P01_CREDENTIAL_CREATE")

    payload = {
        "bindings": patch_bindings,
        "annotations": {
            "workers/message": f"B62 Claw live config activation gate {target_sha}",
            "workers/triggered_by": "b62-claw-live-config-activation-gate",
        },
    }
    return {
        "payload": payload,
        "changes": changes,
        "credential_create_required": credential_create_required,
        "no_op": not changes,
        "preserved_bindings": sum(1 for b in patch_bindings if b["type"] == "inherit"),
    }


QUOTA_TARGET_NAMES = tuple(sorted(QUOTA_VALUES))
P01_TARGET_NAMES = (P01_SERVICE_NAME, P01_CALLER_NAME, P01_CREDENTIAL_NAME)
WORKSPACE_R2_TARGET_NAMES = (R2_BINDING_NAME,)


def source_credential_quality(value: object) -> bool:
    """Bounded UTF-8 byte-quality gate for the replacement source credential.

    Mirrors the runtime validation order in worker_config: the value must be a
    non-empty string whose UTF-8 encoding is within the accepted byte range.
    Returns only a boolean; callers must never print the value, its length, or
    any digest of it.
    """
    if not isinstance(value, str) or not value:
        return False
    byte_length = len(value.encode("utf-8"))
    return P01_CREDENTIAL_MIN_BYTES <= byte_length <= P01_CREDENTIAL_MAX_BYTES


def replacement_precheck(settings_payload: object) -> dict:
    """Gate the replacement path on an existing P01_ENGINE_CREDENTIAL secret_text.

    An absent credential must go through the activate_config create path; a
    non-secret binding at that name is refused rather than overwritten. Only
    binding names and types are inspected; no secret value is ever read.
    """
    bindings = _raw_bindings(settings_payload)
    by_name = {binding["name"]: binding for binding in bindings}
    credential = by_name.get(P01_CREDENTIAL_NAME)
    if credential is None:
        raise ActivationPlanError(
            f"{P01_CREDENTIAL_NAME} is absent; replacement requires an existing "
            "secret_text binding (an absent credential uses the activate_config create path)"
        )
    if credential.get("type") != "secret_text":
        raise ActivationPlanError(
            f"{P01_CREDENTIAL_NAME} exists with type {credential.get('type')!r}; "
            "refusing to overwrite a non-secret binding"
        )
    return {
        "secret_names": sorted(
            binding["name"] for binding in bindings if binding.get("type") == "secret_text"
        ),
    }


def verify_replacement_readback(pre_payload: object, post_payload: object) -> list[str]:
    """Compare pre/post served configuration by binding name and type only.

    Every binding present before the replacement must still be present with the
    same type afterwards, and P01_ENGINE_CREDENTIAL must remain secret_text.
    Secret values are never read or compared.
    """
    pre_types = {binding["name"]: binding.get("type") for binding in _raw_bindings(pre_payload)}
    post_types = {binding["name"]: binding.get("type") for binding in _raw_bindings(post_payload)}
    failures: list[str] = []
    if post_types.get(P01_CREDENTIAL_NAME) != "secret_text":
        failures.append(
            f"{P01_CREDENTIAL_NAME}: expected PRESENT:secret_text after replacement, "
            f"found {post_types.get(P01_CREDENTIAL_NAME)}"
        )
    for name, kind in sorted(pre_types.items()):
        if post_types.get(name) != kind:
            failures.append(f"{name}: pre-existing binding type {kind} is missing or retyped")
    return failures


def deploy_prereq_failures(states: dict[str, str]) -> list[str]:
    """Every activation target must already be exactly accepted before a code deploy."""
    return sorted(name for name, state in states.items() if state != "exact")


def _group_exact(states: dict[str, str], names: tuple[str, ...]) -> bool:
    return all(states[name] == "exact" for name in names)


def _inherit(name: str) -> dict:
    return {"name": name, "type": "inherit", "version_id": "latest"}


def _inline_binding(binding: dict) -> dict:
    kind = binding["type"]
    entry: dict = {"name": binding["name"], "type": kind}
    if kind == "plain_text":
        entry["text"] = binding["text"]
    elif kind == "service":
        entry["service"] = binding["service"]
        if isinstance(binding.get("environment"), str) and binding["environment"]:
            entry["environment"] = binding["environment"]
    elif kind == "d1":
        entry["id"] = binding["id"]
    elif kind == "r2_bucket":
        entry["bucket_name"] = binding["bucket_name"]
        if isinstance(binding.get("jurisdiction"), str) and binding["jurisdiction"]:
            entry["jurisdiction"] = binding["jurisdiction"]
    return entry


class ManualConfigRecoveryRequired(ActivationPlanError):
    pass


def build_rollback_plan(
    snapshot_payload: object,
    current_payload: object,
    *,
    credential_created_by_activation: bool,
    target_sha: str,
) -> dict:
    """Plan a settings restore bounded to the pre-activation snapshot.

    This is CONFIG_ROLLBACK authority, never a code-version rollback claim.
    Anything that cannot be restored from bounded pre-mutation evidence without
    reading or reconstructing a secret value fails closed with
    MANUAL_CONFIG_RECOVERY_REQUIRED instead of claiming a full config rollback.
    """
    snapshot_bindings = _raw_bindings(snapshot_payload)
    current_bindings = _raw_bindings(current_payload)
    snapshot_by_name = {binding["name"]: binding for binding in snapshot_bindings}
    current_by_name = {binding["name"]: binding for binding in current_bindings}

    patch_bindings: list[dict] = []
    changes: list[str] = []
    manual_reasons: list[str] = []

    for name in sorted(snapshot_by_name):
        snapshot = snapshot_by_name[name]
        current = current_by_name.get(name)
        if snapshot.get("type") == "secret_text":
            if current is not None and current.get("type") == "secret_text":
                patch_bindings.append(_inherit(name))
            else:
                manual_reasons.append(
                    f"{name}: pre-activation secret binding is gone or retyped and its value "
                    "cannot be reconstructed from bounded evidence"
                )
            continue
        if current is not None and canonical_binding(snapshot) == canonical_binding(current):
            patch_bindings.append(_inherit(name))
        elif name in TARGET_NAMES:
            patch_bindings.append(_inline_binding(snapshot))
            changes.append(f"CONFIG_RESTORE_{name}")
        else:
            manual_reasons.append(
                f"{name}: unrelated binding changed after activation; refusing to overwrite it"
            )

    for name in sorted(current_by_name):
        if name in snapshot_by_name:
            continue
        if name == P01_CREDENTIAL_NAME:
            if credential_created_by_activation:
                changes.append("P01_CREDENTIAL_REMOVE_NEW")
            else:
                manual_reasons.append(
                    f"{name}: present live but absent from the pre-activation snapshot and this "
                    "rollback run does not attribute its creation to the recorded activation"
                )
        elif name in TARGET_NAMES:
            changes.append(f"CONFIG_REMOVE_{name}")
        else:
            patch_bindings.append(_inherit(name))

    if manual_reasons:
        raise ManualConfigRecoveryRequired("; ".join(manual_reasons))

    payload = {
        "bindings": patch_bindings,
        "annotations": {
            "workers/message": f"B62 Claw config rollback from pre-activation snapshot {target_sha}",
            "workers/triggered_by": "b62-claw-live-config-activation-gate",
        },
    }
    return {
        "payload": payload,
        "changes": changes,
        "no_op": not changes,
        "restored_bindings": sum(1 for b in patch_bindings if b["type"] != "inherit"),
        "inherited_bindings": sum(1 for b in patch_bindings if b["type"] == "inherit"),
    }


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "classify",
            "plan",
            "verify",
            "deploy-prereq",
            "rollback-plan",
            "credential-quality",
            "replacement-precheck",
            "replacement-verify",
        ),
    )
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--engine-service", default="")
    parser.add_argument("--r2-bucket", default="")
    parser.add_argument("--target-sha", default="")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--pre-settings", type=Path)
    parser.add_argument("--credential-created-by-activation", default="false")
    args = parser.parse_args(args_in)

    if args.command == "credential-quality":
        return _main_credential_quality()
    if args.command == "replacement-precheck":
        return _main_replacement_precheck(args)
    if args.command == "replacement-verify":
        return _main_replacement_verify(args)
    if not args.settings:
        print(f"usage: {args.command} requires --settings", file=sys.stderr)
        return 2

    if args.command == "rollback-plan":
        return _main_rollback_plan(args)

    if not args.engine_service or not args.r2_bucket:
        print(f"usage: {args.command} requires --engine-service and --r2-bucket", file=sys.stderr)
        return 2

    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        states = classify_live_config(
            payload,
            engine_service_name=args.engine_service,
            r2_bucket_name=args.r2_bucket,
        )
    except (OSError, json.JSONDecodeError, ActivationPlanError, _deploy_config.ProductionConfigError) as exc:
        print(f"B62_CLAW_LIVE_CONFIG_{args.command.upper()}=FAIL\nREASON={exc}", file=sys.stderr)
        return 1

    if args.command == "deploy-prereq":
        for name in sorted(states):
            print(f"BINDING_STATE {name}={states[name]}")
        failures = deploy_prereq_failures(states)
        print(f"QUOTA_PREDEPLOY_EXACT={'PASS' if _group_exact(states, QUOTA_TARGET_NAMES) else 'FAIL'}")
        print(f"P01_PREDEPLOY_EXACT={'PASS' if _group_exact(states, P01_TARGET_NAMES) else 'FAIL'}")
        print(
            "WORKSPACE_R2_PREDEPLOY_EXACT="
            f"{'PASS' if _group_exact(states, WORKSPACE_R2_TARGET_NAMES) else 'FAIL'}"
        )
        print("P01_CREDENTIAL_AUTHORITY=NAME_AND_TYPE_ONLY")
        print("SECRET_VALUES_READ=0")
        print("APPLICATION_ROW_READ=0")
        if failures:
            for name in failures:
                print(f"PREREQ_REFUSE_TARGET {name}={states[name]}", file=sys.stderr)
            print("B62_DEPLOY_LIVE_PREREQ=FAIL", file=sys.stderr)
            return 1
        print("B62_DEPLOY_LIVE_PREREQ=PASS")
        return 0

    overall = disposition(states)
    for name in sorted(states):
        print(f"BINDING_STATE {name}={states[name]}")

    if args.command == "classify":
        print(f"B62_CLAW_LIVE_CONFIG_DISPOSITION={overall}")
        return 0 if not overall.startswith("REFUSE") else 1

    if args.command == "verify":
        if overall == "ALREADY_EXACT":
            print("B62_CLAW_LIVE_CONFIG_VERIFY=EXACT")
            return 0
        print(f"B62_CLAW_LIVE_CONFIG_VERIFY=INCOMPLETE\nDISPOSITION={overall}", file=sys.stderr)
        return 1

    if not args.output or not args.target_sha:
        print("usage: plan requires --output and --target-sha", file=sys.stderr)
        return 2
    try:
        plan = build_activation_patch(
            payload,
            engine_service_name=args.engine_service,
            r2_bucket_name=args.r2_bucket,
            target_sha=args.target_sha,
        )
    except ActivationPlanError as exc:
        print(f"B62_CLAW_LIVE_CONFIG_PLAN=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    if args.output.exists():
        print("B62_CLAW_LIVE_CONFIG_PLAN=FAIL\nREASON=output path already exists", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(plan["payload"], separators=(",", ":")), encoding="utf-8")
    for change in plan["changes"]:
        print(f"CONFIG_CHANGE {change}")
    print(f"B62_CLAW_LIVE_CONFIG_PLAN=PASS DISPOSITION={overall}")
    print(f"B62_CLAW_CONFIG_NO_OP={'1' if plan['no_op'] else '0'}")
    print(f"B62_CLAW_CONFIG_CREDENTIAL_CREATE_REQUIRED={'1' if plan['credential_create_required'] else '0'}")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    return 0


def _main_rollback_plan(args: argparse.Namespace) -> int:
    if not args.snapshot or not args.output:
        print("usage: rollback-plan requires --snapshot and --output", file=sys.stderr)
        return 2
    if args.credential_created_by_activation not in {"true", "false"}:
        print("--credential-created-by-activation must be true or false", file=sys.stderr)
        return 2
    try:
        current_payload = json.loads(args.settings.read_text(encoding="utf-8"))
        snapshot_payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"B62_CLAW_CONFIG_ROLLBACK_PLAN=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    try:
        plan = build_rollback_plan(
            snapshot_payload,
            current_payload,
            credential_created_by_activation=args.credential_created_by_activation == "true",
            target_sha=args.target_sha,
        )
    except ManualConfigRecoveryRequired as exc:
        print(
            "B62_CLAW_CONFIG_ROLLBACK_PLAN=MANUAL_CONFIG_RECOVERY_REQUIRED\n"
            f"REASON={exc}\n"
            "CONFIG_ROLLBACK=MANUAL_CONFIG_RECOVERY_REQUIRED\n"
            "CODE_VERSION_ROLLBACK_UNAFFECTED=YES\n"
            "FULL_CONFIG_ROLLBACK_CLAIM=NO\n"
            "SECRET_VALUES_READ=0",
            file=sys.stderr,
        )
        return 3
    except (ActivationPlanError, _deploy_config.ProductionConfigError) as exc:
        print(f"B62_CLAW_CONFIG_ROLLBACK_PLAN=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    if args.output.exists():
        print("B62_CLAW_CONFIG_ROLLBACK_PLAN=FAIL\nREASON=output path already exists", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(plan["payload"], separators=(",", ":")), encoding="utf-8")
    for change in plan["changes"]:
        print(f"CONFIG_CHANGE {change}")
    print("B62_CLAW_CONFIG_ROLLBACK_PLAN=PASS")
    print(f"B62_CLAW_CONFIG_ROLLBACK_NO_OP={'1' if plan['no_op'] else '0'}")
    print(f"CONFIG_RESTORED_BINDINGS={plan['restored_bindings']}")
    print(f"CONFIG_INHERITED_BINDINGS={plan['inherited_bindings']}")
    print("CONFIG_ROLLBACK_SCOPE=SNAPSHOT_BOUNDED_SETTINGS_ONLY")
    print("CODE_VERSION_ROLLBACK_DISTINGUISHED=YES")
    print("FULL_CONFIG_ROLLBACK_CLAIM=NO_UNTIL_READBACK")
    print("PIECEMEAL_SECRET_RESTORE=0")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    return 0


def _main_credential_quality() -> int:
    value = os.environ.get(SOURCE_CREDENTIAL_ENV)
    present = value is not None and value != ""
    quality = source_credential_quality(value)
    print(f"SOURCE_CREDENTIAL_PRESENT={'YES' if present else 'NO'}")
    print(f"SOURCE_CREDENTIAL_QUALITY={'PASS' if quality else 'FAIL'}")
    print("SECRET_VALUE_OUTPUT=0")
    print("SECRET_LENGTH_OUTPUT=0")
    print("SECRET_HASH_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0 if quality else 1


def _main_replacement_precheck(args: argparse.Namespace) -> int:
    if not args.settings:
        print("usage: replacement-precheck requires --settings", file=sys.stderr)
        return 2
    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        result = replacement_precheck(payload)
    except (
        OSError,
        json.JSONDecodeError,
        ActivationPlanError,
        _deploy_config.ProductionConfigError,
    ) as exc:
        print(f"B62_P01_REPLACEMENT_PRECHECK=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print("B62_P01_REPLACEMENT_PRECHECK=PASS")
    print(f"EXISTING_SECRET_NAMES={','.join(result['secret_names']) or 'NONE'}")
    print("OLD_SECRET_VALUE_READ=NO")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def _main_replacement_verify(args: argparse.Namespace) -> int:
    if not args.settings or not args.pre_settings:
        print("usage: replacement-verify requires --settings and --pre-settings", file=sys.stderr)
        return 2
    try:
        post_payload = json.loads(args.settings.read_text(encoding="utf-8"))
        pre_payload = json.loads(args.pre_settings.read_text(encoding="utf-8"))
        failures = verify_replacement_readback(pre_payload, post_payload)
    except (
        OSError,
        json.JSONDecodeError,
        ActivationPlanError,
        _deploy_config.ProductionConfigError,
    ) as exc:
        print(f"B62_P01_REPLACEMENT_VERIFY=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f"READBACK_FAIL {failure}", file=sys.stderr)
        print("B62_P01_REPLACEMENT_VERIFY=FAIL", file=sys.stderr)
        return 1
    print("B62_P01_REPLACEMENT_VERIFY=PASS")
    print(f"{P01_CREDENTIAL_NAME}=PRESENT:secret_text")
    print("UNRELATED_SECRET_MUTATION=0")
    print("RUNTIME_SUCCESS_CLAIM=NO_UNTIL_PHASE_A_RERUN")
    print("SECRET_VALUES_READ=0")
    print("SECRET_VALUES_EMITTED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
