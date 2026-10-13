#!/usr/bin/env python3
"""One-incident, fail-closed 10214 recovery from authenticated P01 SSE snapshot.

Network-free. Only the Worker currently served (SSE OFF) may be replaced with
exact-current-main code and the same settings from the immutable pre-PATCH
snapshot. Never adopts the unaccepted script-level SSE=true setting.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = str(Path(__file__).resolve().parent)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import b62_sse_served_config_drift_guard as drift
from b62_p01_sse_optin_gate import FLAG, bindings, version_bindings, version_result
from cloudflare_served_version import resolve_served_version_id

# Exact incident pins; this emergency recovery route is NOT reusable for new
# release/flag changes without explicit source review.
PREMUTATION_VERSION_ID = "181d637c-de84-4919-9d45-8e966a07f181"
BAD_LATEST_VERSION_ID = "18ee50a1-ab64-4cc0-8fc2-2ed3234f63a5"
PREMUTATION_RUN_ID = 38431252763


class RecoveryRefused(ValueError):
    pass


def candidate(settings: object, served: object) -> None:
    """Read-only candidate proof, before an artifact is downloaded."""
    try:
        script = bindings(settings)
        active = version_bindings(version_result(served))
        script_flag = drift._flag(script.get(FLAG))
        served_flag = drift._flag(active.get(FLAG))
    except Exception as exc:
        raise RecoveryRefused("INVALID_SCRIPT_OR_SERVED_BINDING") from exc
    if script_flag != "true" or served_flag != "absent":
        raise RecoveryRefused("NOT_THE_SSE_TRUE_SCRIPT_OFF_SERVED_INCIDENT")


def validate(
    settings: object, snapshot: object, deployments: object, served: object,
    latest: object,
) -> None:
    candidate(settings, served)
    original = bindings(snapshot)
    script = bindings(settings)
    imm = version_result(served)
    active = version_bindings(imm)
    if FLAG in original or len(original) != 43:
        raise RecoveryRefused("PREMUTATION_SNAPSHOT_NOT_EXACT_SSE_OFF")
    expected_script = dict(original)
    expected_script[FLAG] = {"name": FLAG, "type": "plain_text", "text": "true"}
    if script != expected_script:
        raise RecoveryRefused("UNRELATED_SCRIPT_LEVEL_CONFIG_DRIFT")
    if set(active) != set(original):
        raise RecoveryRefused("SERVED_INVENTORY_DIFFERS_FROM_PREMUTATION_SNAPSHOT")
    if any(
        active[name].get("type") != original[name].get("type")
        or (original[name]["type"] == "plain_text" and
            active[name].get("text") != original[name].get("text"))
        for name in original
    ):
        raise RecoveryRefused("SERVED_BINDING_OR_RUNTIME_DRIFT")
    if imm["id"] != PREMUTATION_VERSION_ID:
        raise RecoveryRefused("SERVED_CODE_VERSION_NOT_PREMUTATION")
    try:
        active_id = resolve_served_version_id(deployments)
    except Exception as exc:
        raise RecoveryRefused("NONCANONICAL_DEPLOYMENT") from exc
    if active_id != PREMUTATION_VERSION_ID:
        raise RecoveryRefused("ACTIVE_SERVING_VERSION_CHANGED")
    if not isinstance(latest, dict) or latest.get("success") is not True:
        raise RecoveryRefused("LATEST_RESPONSE_INVALID")
    try:
        latest_id = latest["result"]["items"][0]["id"]
    except (IndexError, KeyError, TypeError) as exc:
        raise RecoveryRefused("LATEST_VERSION_UNKNOWN") from exc
    if latest_id != BAD_LATEST_VERSION_ID:
        raise RecoveryRefused("LATEST_VERSION_CHANGED")
    if original.get("PADIEM_CHAT_RUNTIME_MODE", {}).get("text") != "b14":
        raise RecoveryRefused("RUNTIME_NOT_READY")
    if original.get("PADIEM_CHAT_LIVE_ENABLED", {}).get("text") != "true":
        raise RecoveryRefused("LIVE_RUNTIME_NOT_READY")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("candidate", "validate"))
    p.add_argument("--settings", type=Path, required=True)
    p.add_argument("--served-version", type=Path, required=True)
    p.add_argument("--snapshot", type=Path)
    p.add_argument("--deployments", type=Path)
    p.add_argument("--latest", type=Path)
    a = p.parse_args()
    try:
        settings = json.loads(a.settings.read_text(encoding="utf-8"))
        served = json.loads(a.served_version.read_text(encoding="utf-8"))
        if a.mode == "candidate":
            candidate(settings, served)
        else:
            if not a.snapshot or not a.deployments or not a.latest:
                raise RecoveryRefused("MISSING_IMMUTABLE_EVIDENCE")
            validate(
                settings,
                json.loads(a.snapshot.read_text(encoding="utf-8")),
                json.loads(a.deployments.read_text(encoding="utf-8")),
                served,
                json.loads(a.latest.read_text(encoding="utf-8")),
            )
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        reason = str(exc) if isinstance(exc, RecoveryRefused) else "MALFORMED_RECOVERY_EVIDENCE"
        print(f"P01_SSE_RECOVERY=BLOCKED:{reason}")
        print("RECOVERY_MUTATION=0")
        return 2
    print("P01_SSE_RECOVERY_SNAPSHOT_EXACT=PASS" if a.mode == "validate" else "P01_SSE_RECOVERY_CANDIDATE=PASS")
    print("SSE_LATEST_SCRIPT_TRUE_BUT_SERVED_ABSENT=YES")
    print("SECRET_VALUES_EMITTED=0")
    print("RECOVERY_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
