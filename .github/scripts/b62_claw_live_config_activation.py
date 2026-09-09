#!/usr/bin/env python3
"""Classify and plan the B62 Claw live configuration activation without touching secrets.

The live Cloudflare Worker settings dump is the only input. The helper never
reads, writes, or emits secret values: unchanged bindings (including every
secret) are carried into the activation patch as ``inherit``/``latest``
references, exactly like the merged control-plane identity binding gate.
Anything structurally unexpected fails closed so no live binding can be
silently dropped, retyped, or rewired by this activation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("classify", "plan", "verify"))
    parser.add_argument("--settings", required=True, type=Path)
    parser.add_argument("--engine-service", required=True)
    parser.add_argument("--r2-bucket", required=True)
    parser.add_argument("--target-sha", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(args_in)

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


if __name__ == "__main__":
    raise SystemExit(main())
