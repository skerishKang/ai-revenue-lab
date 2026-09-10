#!/usr/bin/env python3
"""Plan and verify the B54 Engine caller-registry V1 provisioning mutation.

This gate provisions ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` (type secret_text)
on the ``padiem-ai-engine`` worker so that the Claw caller ``b54-kagent``
(allowed to ``b54-padiem-claw``) is present in the Engine caller authority.

Two secrets are consumed, both from environment variables only (never argv,
never workflow inputs, never stdout):

- ``B54_ENGINE_CALLER_REGISTRY_V1_BASELINE``: the private baseline — the
  CURRENT complete V1 registry plaintext, held by the owner. Required on the
  preservation path (live V1 already present).
- ``B62_P01_ENGINE_CREDENTIAL``: the raw Claw credential. It is embedded in
  the registry UNHASHED — the Engine hashes each entry credential internally
  at load time (``caller_secret_digest`` in
  ``apps/padiem-ai-engine/app/service_identity.py``), so a pre-hashed value
  would break authentication with ``service_authentication_failed``.

Preservation contract (live V1 PRESENT):

- the baseline must parse as a complete V1 registry;
- the baseline must contain ``caller_id=storymemory-b61`` with
  ``allowed_app_ids`` exactly ``["b61"]`` (B61 preservation contract);
- every existing caller entry is preserved verbatim — additional callers are
  opaque existing authority and are never dropped, modified, or regenerated;
- if ``b54-kagent`` is absent, exactly one entry is appended with
  ``allowed_app_ids=["b54-padiem-claw"]`` and the raw new credential;
- if ``b54-kagent`` is already present, the gate fails closed unless the
  baseline entry is exactly compatible (same raw credential, same app list) —
  in that case the plan is a no-op and nothing is written;
- the COMPLETE merged result is validated against the Engine's own registry
  contract (identical semantics to ``parse_caller_registry_v1``).

The greenfield path (all caller authority ABSENT) remains only as an isolated,
tested capability: a single-caller registry with ``b54-kagent``. It is not the
current Production path.

This script never prints a credential, a registry, or any secret value.
Readback is NAME/TYPE-only and reuses the merged B54 caller-authority
read-only classifier so this gate and the read-only gate (#2397) cannot drift.

Subcommands:

- ``classify --settings <worker-settings.json>`` — NAME/TYPE-only authority
  classification plus the provision disposition.
- ``plan --disposition <DISP> --credential-env <ENV> [--baseline-env <ENV>]
  --output <put-body.json>`` — build the bounded PUT body from secrets.
- ``verify --settings <worker-settings.json>`` — post-mutation NAME/TYPE-only
  readback: registry secret present with type ``secret_text``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_authority_spec = importlib.util.spec_from_file_location(
    "b54_engine_caller_authority_readonly",
    _HERE / "b54_engine_caller_authority_readonly.py",
)
assert _authority_spec is not None and _authority_spec.loader is not None
_authority = importlib.util.module_from_spec(_authority_spec)
_authority_spec.loader.exec_module(_authority)
classify_authority = _authority.classify_authority
TARGET_NAMES = _authority.TARGET_NAMES

ENGINE_WORKER = "padiem-ai-engine"
REGISTRY_SECRET_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
LEGACY_TRIO_NAMES = (
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)

# Canonical B54 caller entry (P01 constants: P01_CALLER_VALUE / P01_APP_ID).
CALLER_ID = "b54-kagent"
ALLOWED_APP_IDS = ("b54-padiem-claw",)
REGISTRY_VERSION = 1

# B61 preservation contract (historical accepted Production authority).
B61_CALLER_ID = "storymemory-b61"
B61_ALLOWED_APP_IDS = ("b61",)

# Engine identity contract bounds (apps/padiem-ai-engine/app/service_identity.py
# and app/identity_enforcement.py).
MIN_CREDENTIAL_BYTES = 32
MAX_CREDENTIAL_BYTES = 512
MAX_ENGINE_CALLERS = 64
MAX_CALLER_APP_IDS = 32
MAX_CALLER_REGISTRY_V1_BYTES = 524288
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_ENTRY_KEYS = frozenset({"caller_id", "credential", "allowed_app_ids"})
_TOP_LEVEL_KEYS = frozenset({"version", "callers"})


class ProvisionPlanError(RuntimeError):
    """Safe provisioning-plan failure; never carries credential content."""


def authority_disposition(states: dict[str, str]) -> str:
    """Aggregate NAME/TYPE authority states into the provision disposition.

    - ``EXTEND_REQUIRED``: V1 registry already present as ``secret_text``.
      Its value is opaque/non-retrievable; extension requires the private
      baseline secret and follows the preservation path.
    - ``REFUSE_WRONG_TYPE``: registry name exists but not as ``secret_text``.
    - ``REFUSE_LEGACY_AUTHORITY_PRESENT``: the legacy one-caller trio is
      configured while V1 is absent. Enabling V1 would silently retire that
      trio and its credential value is non-retrievable — refuse mutation.
    - ``PROVISION_REQUIRED``: no caller authority present at all (greenfield).
    """
    registry = states.get(REGISTRY_SECRET_NAME, "ABSENT")
    if registry == "PRESENT:secret_text":
        return "EXTEND_REQUIRED"
    if registry != "ABSENT":
        return "REFUSE_WRONG_TYPE"
    if any(states.get(name, "ABSENT") != "ABSENT" for name in LEGACY_TRIO_NAMES):
        return "REFUSE_LEGACY_AUTHORITY_PRESENT"
    return "PROVISION_REQUIRED"


def _check_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ProvisionPlanError(f"{name} must be a bounded safe identifier")


def _check_registry_shape(payload: object) -> dict:
    """Validate a registry payload with canonical Engine V1 parser semantics."""
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise ProvisionPlanError("registry must contain exactly version and callers")
    version = payload["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != REGISTRY_VERSION:
        raise ProvisionPlanError("registry version is unsupported")
    callers = payload["callers"]
    if not isinstance(callers, list):
        raise ProvisionPlanError("registry callers must be a JSON array")
    if not 1 <= len(callers) <= MAX_ENGINE_CALLERS:
        raise ProvisionPlanError("registry must contain 1 to 64 callers")
    seen: set[str] = set()
    for entry in callers:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            raise ProvisionPlanError(
                "caller entries must contain exactly caller_id, credential, and allowed_app_ids"
            )
        caller_id = entry["caller_id"]
        _check_identifier("caller_id", caller_id)
        if caller_id in seen:
            raise ProvisionPlanError("registry must not contain duplicate caller IDs")
        seen.add(caller_id)
        credential = entry["credential"]
        if not isinstance(credential, str):
            raise ProvisionPlanError("caller credential is not text")
        raw = credential.encode("utf-8")
        if not MIN_CREDENTIAL_BYTES <= len(raw) <= MAX_CREDENTIAL_BYTES:
            raise ProvisionPlanError(
                "caller credential must contain "
                f"{MIN_CREDENTIAL_BYTES} to {MAX_CREDENTIAL_BYTES} bytes"
            )
        app_ids = entry["allowed_app_ids"]
        if not isinstance(app_ids, list):
            raise ProvisionPlanError("allowed_app_ids must be a JSON array")
        if not 1 <= len(app_ids) <= MAX_CALLER_APP_IDS:
            raise ProvisionPlanError("allowed_app_ids must contain 1 to 32 values")
        if len(set(app_ids)) != len(app_ids):
            raise ProvisionPlanError("allowed_app_ids must not contain duplicates")
        for app_id in app_ids:
            _check_identifier("allowed app id", app_id)
    return payload


def _assert_b61_preserved(payload: dict) -> None:
    """Require the B61 entry with allowed_app_ids exactly ``["b61"]``."""
    for entry in payload["callers"]:
        if entry["caller_id"] == B61_CALLER_ID:
            if entry["allowed_app_ids"] != list(B61_ALLOWED_APP_IDS):
                raise ProvisionPlanError(
                    "B61 caller exists but allowed_app_ids is not exactly [\"b61\"]"
                )
            return
    raise ProvisionPlanError("baseline is missing the B61 caller entry (storymemory-b61)")


def _serialized(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def build_registry_payload(*, credential: str) -> dict:
    """Greenfield payload: a single-caller registry with the B54 caller only.

    This is the isolated all-ABSENT capability, not the Production path.
    The credential is embedded raw (never pre-hashed).
    """

    if not isinstance(credential, str):
        raise ProvisionPlanError("caller credential is not text")
    raw = credential.encode("utf-8")
    if not MIN_CREDENTIAL_BYTES <= len(raw) <= MAX_CREDENTIAL_BYTES:
        raise ProvisionPlanError(
            "caller credential must contain "
            f"{MIN_CREDENTIAL_BYTES} to {MAX_CREDENTIAL_BYTES} bytes"
        )
    _check_identifier("caller_id", CALLER_ID)
    for app_id in ALLOWED_APP_IDS:
        _check_identifier("allowed app id", app_id)
    payload = {
        "version": REGISTRY_VERSION,
        "callers": [
            {
                "caller_id": CALLER_ID,
                "credential": credential,
                "allowed_app_ids": list(ALLOWED_APP_IDS),
            }
        ],
    }
    serialized = _serialized(payload)
    if len(serialized.encode("utf-8")) > MAX_CALLER_REGISTRY_V1_BYTES:
        raise ProvisionPlanError("registry payload exceeds the bounded input size")
    return _check_registry_shape(payload)


def _append_b54_entry(callers: list[dict], credential: str) -> tuple[list[dict], str]:
    """Append the B54 entry when absent; otherwise verify exact compatibility.

    Returns ``(merged_callers, verdict)`` where verdict is
    ``APPENDED`` or ``ALREADY_COMPATIBLE``. Existing entries are never
    modified; the B54 entry must match the new credential and app contract
    exactly or the plan fails closed.
    """

    b54_entries = [entry for entry in callers if entry["caller_id"] == CALLER_ID]
    if not b54_entries:
        merged = list(callers)
        merged.append(
            {
                "caller_id": CALLER_ID,
                "credential": credential,
                "allowed_app_ids": list(ALLOWED_APP_IDS),
            }
        )
        return merged, "APPENDED"
    if len(b54_entries) > 1:
        raise ProvisionPlanError("registry contains duplicate b54-kagent entries")
    existing = b54_entries[0]
    if existing.get("credential") != credential:
        raise ProvisionPlanError(
            "existing b54-kagent entry is not compatible with the new credential contract"
        )
    if existing.get("allowed_app_ids") != list(ALLOWED_APP_IDS):
        raise ProvisionPlanError(
            "existing b54-kagent entry is not compatible with the new app contract"
        )
    return list(callers), "ALREADY_COMPATIBLE"


def parse_baseline_registry(baseline: str) -> dict:
    """Parse and validate the private baseline as a complete V1 registry.

    Requires the baseline to parse with canonical Engine semantics and to
    contain the B61 entry (storymemory-b61 / exactly ``["b61"]``).
    """

    if not isinstance(baseline, str) or not baseline.strip():
        raise ProvisionPlanError("baseline registry is missing or blank")
    serialized_baseline = baseline.encode("utf-8")
    if len(serialized_baseline) > MAX_CALLER_REGISTRY_V1_BYTES:
        raise ProvisionPlanError("baseline registry exceeds the bounded input size")
    try:
        payload = json.loads(baseline)
    except (ValueError, RecursionError):
        raise ProvisionPlanError("baseline registry is not valid JSON") from None
    _check_registry_shape(payload)
    _assert_b61_preserved(payload)
    return payload


def merge_b54_caller(payload: dict, credential: str) -> tuple[dict, str]:
    """Preservation merge: baseline verbatim plus the B54 caller entry.

    Every existing caller entry is preserved untouched; the B54 entry is
    appended when absent or verified exactly compatible when present.
    Returns ``(merged, verdict)`` with verdict ``APPENDED`` or
    ``ALREADY_COMPATIBLE``.
    """

    merged_callers, verdict = _append_b54_entry(payload["callers"], credential)
    merged = {"version": REGISTRY_VERSION, "callers": merged_callers}
    serialized = _serialized(merged)
    if len(serialized.encode("utf-8")) > MAX_CALLER_REGISTRY_V1_BYTES:
        raise ProvisionPlanError("merged registry exceeds the bounded input size")
    _check_registry_shape(merged)
    return merged, verdict


def build_put_body(payload: dict) -> dict:
    """Build the Cloudflare Worker secrets PUT body for the registry secret."""

    return {
        "name": REGISTRY_SECRET_NAME,
        "type": "secret_text",
        "text": _serialized(payload),
    }


def _settings_states(settings_payload: object) -> dict[str, str]:
    return classify_authority(settings_payload)


def _cmd_classify(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        states = _settings_states(payload)
    except (OSError, json.JSONDecodeError, _authority.CallerAuthorityEvidenceError) as exc:
        print("B54_ENGINE_CALLER_REGISTRY_CLASSIFY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    disposition = authority_disposition(states)
    for name in TARGET_NAMES:
        print(f"AUTHORITY_STATE {name}={states[name]}")
    print(f"B54_ENGINE_CALLER_REGISTRY_DISPOSITION={disposition}")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("SECRET_VALUES_READ=0")
    print("CLOUDFLARE_MUTATION=0")
    print("PRODUCTION_MUTATION=0")
    return 0 if disposition in ("PROVISION_REQUIRED", "EXTEND_REQUIRED") else 1


def _read_env_secret(name: str, *, label: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ProvisionPlanError(f"{label} is not set (environment variable {name})")
    return value


def _cmd_plan(args: argparse.Namespace) -> int:
    if args.disposition not in ("PROVISION_REQUIRED", "EXTEND_REQUIRED"):
        print(
            f"B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL\n"
            f"REASON=disposition {args.disposition!r} is not a provisionable state",
            file=sys.stderr,
        )
        return 1
    if args.output.exists():
        print("B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL\nREASON=output path already exists", file=sys.stderr)
        return 1
    try:
        credential = _read_env_secret(args.credential_env, label="new Claw credential")
        if args.disposition == "EXTEND_REQUIRED":
            baseline = _read_env_secret(args.baseline_env, label="private baseline registry")
            baseline_payload = parse_baseline_registry(baseline)
            payload, verdict = merge_b54_caller(baseline_payload, credential)
        else:
            if args.baseline_env and os.environ.get(args.baseline_env, ""):
                raise ProvisionPlanError(
                    "baseline is forbidden on the greenfield path (all-ABSENT)"
                )
            payload = build_registry_payload(credential=credential)
            verdict = "GREENFIELD_SINGLE_CALLER"
    except ProvisionPlanError as exc:
        print(f"B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL\nREASON={exc}", file=sys.stderr)
        return 1

    body = build_put_body(payload)
    merged_text = body["text"]
    registry_bytes = len(merged_text.encode("utf-8"))
    no_op = args.disposition == "EXTEND_REQUIRED" and verdict == "ALREADY_COMPATIBLE"

    args.output.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    print("B54_ENGINE_CALLER_REGISTRY_PLAN=PASS")
    print(f"B54_ENGINE_CALLER_REGISTRY_PAYLOAD_BYTES={registry_bytes}")
    print(f"B54_ENGINE_CALLER_REGISTRY_VERSION={REGISTRY_VERSION}")
    if args.disposition == "EXTEND_REQUIRED":
        print("B61_PRESERVATION_ASSERT=PASS")
        print("UNKNOWN_CALLERS_PRESERVED=PASS")
        print("BASELINE_CALLERS_PRESERVED_VERBATIM=PASS")
        if verdict == "ALREADY_COMPATIBLE":
            print("B54_KAGENT_APPEND_ONLY=ALREADY_COMPATIBLE")
        else:
            print("B54_KAGENT_APPEND_ONLY=PASS")
    else:
        print("B54_KAGENT_APPEND_ONLY=GREENFIELD_SINGLE_CALLER")
    print("RAW_CREDENTIAL_PREHASHED=NO")
    print("CREDENTIAL_BYTES_IN_BOUNDS=PASS")
    print("RAW_SECRET_OUTPUT=0")
    print("RAW_REGISTRY_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print(f"B54_ENGINE_CALLER_REGISTRY_NO_OP={'1' if no_op else '0'}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.settings.read_text(encoding="utf-8"))
        states = _settings_states(payload)
    except (OSError, json.JSONDecodeError, _authority.CallerAuthorityEvidenceError) as exc:
        print("B54_ENGINE_CALLER_REGISTRY_VERIFY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        return 1
    if states.get(REGISTRY_SECRET_NAME) != "PRESENT:secret_text":
        print(
            "B54_ENGINE_CALLER_REGISTRY_VERIFY=FAIL\n"
            f"REASON={REGISTRY_SECRET_NAME} is not present as secret_text",
            file=sys.stderr,
        )
        return 1
    print("B54_ENGINE_CALLER_REGISTRY_POST_READBACK=PASS")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("SECRET_VALUES_READ=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    classify = sub.add_parser("classify", help="classify live caller authority (NAME/TYPE only)")
    classify.add_argument("--settings", required=True, type=Path)

    plan = sub.add_parser("plan", help="build the bounded V1 registry PUT body from secrets")
    plan.add_argument(
        "--disposition",
        required=True,
        choices=("PROVISION_REQUIRED", "EXTEND_REQUIRED"),
    )
    plan.add_argument(
        "--credential-env",
        required=True,
        help="environment variable holding the raw new Claw credential",
    )
    plan.add_argument(
        "--baseline-env",
        default="",
        help="environment variable holding the private baseline registry (preservation path)",
    )
    plan.add_argument("--output", required=True, type=Path)

    verify = sub.add_parser("verify", help="post-mutation NAME/TYPE-only readback")
    verify.add_argument("--settings", required=True, type=Path)

    args = parser.parse_args(args_in)
    if args.command == "classify":
        return _cmd_classify(args)
    if args.command == "plan":
        return _cmd_plan(args)
    if args.command == "verify":
        return _cmd_verify(args)
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())