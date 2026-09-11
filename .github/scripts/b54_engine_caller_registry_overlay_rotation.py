#!/usr/bin/env python3
"""Bounded rotation of the b54-kagent Engine caller-registry OVERLAY credential.

This gate replaces ONLY ``PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY`` (a served
Worker ``secret_text`` on the ``padiem-ai-engine`` worker) with a canonical
single-caller overlay built from the current GitHub Actions secret
``B62_P01_ENGINE_CREDENTIAL``. It never mutates the base
``PADIEM_ENGINE_CALLER_REGISTRY_V1``, never touches the legacy one-caller trio,
and never requires or consumes the private base-registry baseline or its
currentness attestation (that material belongs to the separate V1 provisioning
gate and is deliberately not referenced here).

Authority model (apps/padiem-ai-engine/app/identity_enforcement.py):
- ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` is the base multi-caller authority.
- ``PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY`` is an optional additive
  SINGLE-caller authority, independently bounded at authentication time. When
  the request caller_id equals the overlay caller_id the Engine authenticates
  directly against the overlay caller; the overlay must not duplicate a base
  caller id, and configuring it while the V1 base is absent fails closed.

Because the #2375 Production authority established the overlay specifically for
caller ``b54-kagent`` / app ``b54-padiem-claw``, the credential drift after the
B62 rotation is an OVERLAY credential drift, not a base V1 rewrite. This gate
therefore requires BOTH the base V1 and the overlay to already be present as
``secret_text`` (NAME/TYPE only) before it will plan, and it PUTs only the
overlay.

Canonical overlay payload (credential embedded UNHASHED; the Engine hashes it
internally via ``caller_secret_digest``):

    {"version": 1,
     "caller": {"caller_id": "b54-kagent",
                "credential": <raw B62_P01_ENGINE_CREDENTIAL>,
                "allowed_app_ids": ["b54-padiem-claw"]}}

Pre- and post-mutation readback is proven on the ACTUALLY SERVED Worker version
(deployments API -> ``versions/{active}`` detail -> ``result.resources.bindings``),
never the mutable settings plane, because a secret PUT may create/activate a new
version. This reuses the shared B54 served-version guard so the deploy gate and
this rotation gate cannot drift on version-detail parsing.

The credential comes from an environment variable only (never argv, never a
workflow input, never stdout). This script never prints a credential, an
overlay, a secret value, a secret length, or a secret hash.

Subcommands:

- ``classify --version-detail <version-detail.json> --active-version <id>`` —
  served-version NAME/TYPE-only authority classification plus the rotation
  disposition (base V1 + overlay present, legacy trio untouched).
- ``plan --credential-env <ENV> --output <put-body.json>`` — build the bounded
  overlay-only PUT body from the raw credential (enforcing the 32..512 UTF-8
  byte credential gate before any output is written).
- ``verify --version-detail <version-detail.json> --active-version <id>`` —
  post-mutation served-version NAME/TYPE-only readback proving base V1 and the
  overlay are both ``PRESENT:secret_text`` and the legacy trio is untouched.
- ``failure-evidence --response <cf-response.json> --http-status <status>`` —
  bounded, NON-SECRET failure evidence for a failed secret PUT. Cloudflare
  error message text and the response body are NEVER selected or printed.
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

_guard_spec = importlib.util.spec_from_file_location(
    "b54_engine_served_version_guard",
    _HERE / "b54_engine_served_version_guard.py",
)
assert _guard_spec is not None and _guard_spec.loader is not None
_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_guard)

# Reuse the shared served-version primitives so version-detail identity and
# binding normalization are single-sourced with the deploy gate.
_version_bindings = _guard._version_bindings
_classify_binding = _guard._classify
ServedVersionGuardError = _guard.ServedVersionGuardError

ENGINE_WORKER = "padiem-ai-engine"
REGISTRY_SECRET_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY_SECRET_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"
REQUIRED_BINDING_TYPE = "secret_text"
LEGACY_TRIO_NAMES = (
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)

# Canonical overlay caller (P01 constants: P01_CALLER_VALUE / P01_APP_ID). These
# are fixed source constants, never dispatcher-tunable, so the rotation can never
# widen or re-point the overlay authority.
CALLER_ID = "b54-kagent"
ALLOWED_APP_IDS = ("b54-padiem-claw",)
OVERLAY_VERSION = 1

# Engine identity contract bounds (apps/padiem-ai-engine/app/service_identity.py
# and app/identity_enforcement.py). The credential byte gate is enforced before
# any mutation so a too-short or too-long secret can never reach Cloudflare.
MIN_CREDENTIAL_BYTES = 32
MAX_CREDENTIAL_BYTES = 512
MAX_CALLER_APP_IDS = 32
MAX_CALLER_REGISTRY_V1_BYTES = 524288
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Overlay payload shape (mirrors parse_caller_registry_v1_overlay exactly).
_OVERLAY_TOP_LEVEL_KEYS = frozenset({"version", "caller"})
_OVERLAY_ENTRY_KEYS = frozenset({"caller_id", "credential", "allowed_app_ids"})

# Bounded failure-evidence bounds (a Cloudflare response body is never emitted).
MAX_CLOUDFLARE_ERROR_CODES = 8
_HTTP_STATUS_RE = re.compile(r"^\d{3}$")

# Names this gate classifies on the served version (base + overlay + legacy trio).
_TARGET_NAMES = (REGISTRY_SECRET_NAME, OVERLAY_SECRET_NAME) + LEGACY_TRIO_NAMES


class OverlayRotationError(RuntimeError):
    """Safe overlay-rotation failure; never carries credential content."""


def rotation_disposition(states: dict[str, str]) -> str:
    """Aggregate served-version NAME/TYPE states into the rotation disposition.

    The overlay rotation is only safe when the base V1 authority is intact and
    the overlay already exists (this is a credential DRIFT fix, not a create).
    Every other shape is refused for direct operator review:

    - ``ROTATION_REQUIRED``: base V1 and overlay are both ``secret_text`` and
      the legacy trio is genuinely absent.
    - ``REFUSE_BASE_V1_ABSENT``: no base authority to be additive to.
    - ``REFUSE_BASE_V1_WRONG_TYPE``: base V1 exists but not as ``secret_text``.
    - ``REFUSE_LEGACY_TRIO_PRESENT``: legacy trio configured alongside V1; the
      overlay path must not proceed while that mixed authority exists.
    - ``REFUSE_OVERLAY_ABSENT``: overlay missing -> this is not a rotation;
      creation belongs to the provisioning gate and needs human review.
    - ``REFUSE_OVERLAY_WRONG_TYPE``: overlay exists but not as ``secret_text``.
    """
    base = states.get(REGISTRY_SECRET_NAME, "ABSENT")
    overlay = states.get(OVERLAY_SECRET_NAME, "ABSENT")
    if base == "ABSENT":
        return "REFUSE_BASE_V1_ABSENT"
    if base != f"PRESENT:{REQUIRED_BINDING_TYPE}":
        return "REFUSE_BASE_V1_WRONG_TYPE"
    if any(states.get(name, "ABSENT") != "ABSENT" for name in LEGACY_TRIO_NAMES):
        return "REFUSE_LEGACY_TRIO_PRESENT"
    if overlay == "ABSENT":
        return "REFUSE_OVERLAY_ABSENT"
    if overlay != f"PRESENT:{REQUIRED_BINDING_TYPE}":
        return "REFUSE_OVERLAY_WRONG_TYPE"
    return "ROTATION_REQUIRED"


def _check_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise OverlayRotationError(f"{name} must be a bounded safe identifier")


def _serialized(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _check_overlay_shape(payload: object) -> dict:
    """Validate an overlay payload with canonical Engine parser semantics.

    Mirrors ``parse_caller_registry_v1_overlay``: exactly ``version`` and
    ``caller`` at the top level, ``version`` an int equal to 1 (never a bool),
    the caller entry with exactly ``caller_id``, ``credential`` and
    ``allowed_app_ids``, bounded identifier grammar, and the 32..512 UTF-8 byte
    credential gate.
    """
    if not isinstance(payload, dict) or set(payload) != _OVERLAY_TOP_LEVEL_KEYS:
        raise OverlayRotationError("overlay must contain exactly version and caller")
    version = payload["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != OVERLAY_VERSION
    ):
        raise OverlayRotationError("overlay version is unsupported")
    entry = payload["caller"]
    if not isinstance(entry, dict) or set(entry) != _OVERLAY_ENTRY_KEYS:
        raise OverlayRotationError(
            "overlay caller must contain exactly caller_id, credential, and allowed_app_ids"
        )
    _check_identifier("caller_id", entry["caller_id"])
    credential = entry["credential"]
    if not isinstance(credential, str):
        raise OverlayRotationError("caller credential is not text")
    raw = credential.encode("utf-8")
    if not MIN_CREDENTIAL_BYTES <= len(raw) <= MAX_CREDENTIAL_BYTES:
        raise OverlayRotationError(
            "caller credential must contain "
            f"{MIN_CREDENTIAL_BYTES} to {MAX_CREDENTIAL_BYTES} bytes"
        )
    app_ids = entry["allowed_app_ids"]
    if not isinstance(app_ids, list):
        raise OverlayRotationError("allowed_app_ids must be a JSON array")
    if not 1 <= len(app_ids) <= MAX_CALLER_APP_IDS:
        raise OverlayRotationError("allowed_app_ids must contain 1 to 32 values")
    if len(set(app_ids)) != len(app_ids):
        raise OverlayRotationError("allowed_app_ids must not contain duplicates")
    for app_id in app_ids:
        _check_identifier("allowed app id", app_id)
    return payload


def build_overlay_payload(*, credential: str) -> dict:
    """Build the canonical single-caller overlay from fixed constants + credential.

    The caller id and app id are fixed source constants; only the credential is
    supplied at runtime, and it is embedded UNHASHED (the Engine hashes it at
    load time). The credential is size-gated before the payload is returned so a
    malformed secret can never be serialized or PUT.
    """
    if not isinstance(credential, str):
        raise OverlayRotationError("caller credential is not text")
    raw = credential.encode("utf-8")
    if not MIN_CREDENTIAL_BYTES <= len(raw) <= MAX_CREDENTIAL_BYTES:
        raise OverlayRotationError(
            "caller credential must contain "
            f"{MIN_CREDENTIAL_BYTES} to {MAX_CREDENTIAL_BYTES} bytes"
        )
    _check_identifier("caller_id", CALLER_ID)
    for app_id in ALLOWED_APP_IDS:
        _check_identifier("allowed app id", app_id)
    payload = {
        "version": OVERLAY_VERSION,
        "caller": {
            "caller_id": CALLER_ID,
            "credential": credential,
            "allowed_app_ids": list(ALLOWED_APP_IDS),
        },
    }
    if len(_serialized(payload).encode("utf-8")) > MAX_CALLER_REGISTRY_V1_BYTES:
        raise OverlayRotationError("overlay payload exceeds the bounded input size")
    return _check_overlay_shape(payload)


def build_overlay_put_body(payload: dict) -> dict:
    """Build the Cloudflare Worker secrets PUT body for the OVERLAY secret only.

    The target name is structurally fixed to the overlay, so a base V1 rewrite
    is impossible through this path.
    """
    return {
        "name": OVERLAY_SECRET_NAME,
        "type": REQUIRED_BINDING_TYPE,
        "text": _serialized(payload),
    }


def bounded_cloudflare_failure_evidence(response_path: Path, http_status: str) -> dict:
    """Extract ONLY bounded, non-secret evidence from a Cloudflare response.

    Never returns ``.errors[].message``, ``.messages``, ``.result``, the raw
    response body, or any request material: only the HTTP status, a boolean
    ``success``, and integer error codes. A non-integer code (e.g. a
    credential-shaped string) is dropped rather than emitted.
    """
    status = http_status if _HTTP_STATUS_RE.fullmatch(http_status or "") else "unknown"
    evidence: dict = {
        "http_status": status,
        "success": "unknown",
        "error_codes": [],
        "error_codes_total": 0,
        "body_parsable": False,
    }
    try:
        raw = response_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return evidence
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        return evidence
    evidence["body_parsable"] = True
    if not isinstance(payload, dict):
        return evidence
    success = payload.get("success")
    if isinstance(success, bool):
        evidence["success"] = "true" if success else "false"
    errors = payload.get("errors")
    if isinstance(errors, list):
        codes: list[int] = []
        for entry in errors:
            if isinstance(entry, dict):
                code = entry.get("code")
                if isinstance(code, int) and not isinstance(code, bool):
                    codes.append(code)
        evidence["error_codes_total"] = len(codes)
        evidence["error_codes"] = codes[:MAX_CLOUDFLARE_ERROR_CODES]
    return evidence


def delete_response_file(response_path: Path) -> bool:
    """Deterministically remove the response temp file; returns cleanup state."""
    try:
        response_path.unlink(missing_ok=True)
    except OSError:
        pass
    return not response_path.exists()


def _served_states(version_detail: object, active_version: str) -> dict[str, str]:
    bindings = _version_bindings(version_detail, active_version)
    return {name: _classify_binding(bindings, name) for name in _TARGET_NAMES}


def _read_env_secret(name: str, *, label: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise OverlayRotationError(f"{label} is not set (environment variable {name})")
    return value


def _cmd_classify(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.version_detail.read_text(encoding="utf-8"))
        states = _served_states(payload, args.active_version)
    except (OSError, json.JSONDecodeError, ServedVersionGuardError) as exc:
        print("B54_ENGINE_OVERLAY_ROTATION_CLASSIFY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("SECRET_VALUES_READ=0", file=sys.stderr)
        return 1
    disposition = rotation_disposition(states)
    for name in _TARGET_NAMES:
        print(f"AUTHORITY_STATE {name}={states[name]}")
    print(f"B54_ENGINE_OVERLAY_ROTATION_DISPOSITION={disposition}")
    print("SERVED_VERSION_READBACK=YES")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("SECRET_VALUES_READ=0")
    print("CLOUDFLARE_MUTATION=0")
    print("PRODUCTION_MUTATION=0")
    return 0 if disposition == "ROTATION_REQUIRED" else 1


def _cmd_plan(args: argparse.Namespace) -> int:
    if args.output.exists():
        print(
            "B54_ENGINE_OVERLAY_ROTATION_PLAN=FAIL\nREASON=output path already exists",
            file=sys.stderr,
        )
        return 1
    try:
        credential = _read_env_secret(args.credential_env, label="new Claw credential")
        payload = build_overlay_payload(credential=credential)
    except OverlayRotationError as exc:
        print("B54_ENGINE_OVERLAY_ROTATION_PLAN=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("RAW_SECRET_OUTPUT=0", file=sys.stderr)
        print("SECRET_VALUE_OUTPUT=0", file=sys.stderr)
        return 1
    body = build_overlay_put_body(payload)
    args.output.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    print("B54_ENGINE_OVERLAY_ROTATION_PLAN=PASS")
    print(f"B54_ENGINE_OVERLAY_TARGET_NAME={OVERLAY_SECRET_NAME}")
    print(f"OVERLAY_VERSION={OVERLAY_VERSION}")
    print(f"OVERLAY_CALLER_ID={CALLER_ID}")
    print(f"OVERLAY_ALLOWED_APP_IDS={','.join(ALLOWED_APP_IDS)}")
    print("CREDENTIAL_BYTES_IN_BOUNDS=PASS")
    print("RAW_CREDENTIAL_PREHASHED=NO")
    print("ENGINE_BASE_V1_MUTATION=0")
    print("LEGACY_TRIO_MUTATION=0")
    print("UNRELATED_SECRET_MUTATION=0")
    print("BASELINE_OR_CURRENTNESS_CONSUMED=0")
    print("RAW_SECRET_OUTPUT=0")
    print("RAW_OVERLAY_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("SECRET_LENGTH_OUTPUT=0")
    print("SECRET_HASH_OUTPUT=0")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.version_detail.read_text(encoding="utf-8"))
        states = _served_states(payload, args.active_version)
    except (OSError, json.JSONDecodeError, ServedVersionGuardError) as exc:
        print("B54_ENGINE_OVERLAY_ROTATION_VERIFY=FAIL", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
        print("SECRET_VALUES_READ=0", file=sys.stderr)
        return 1
    expected = f"PRESENT:{REQUIRED_BINDING_TYPE}"
    problems: list[str] = []
    if states.get(REGISTRY_SECRET_NAME) != expected:
        problems.append(f"{REGISTRY_SECRET_NAME} is not {expected} on the served version")
    if states.get(OVERLAY_SECRET_NAME) != expected:
        problems.append(f"{OVERLAY_SECRET_NAME} is not {expected} on the served version")
    for name in LEGACY_TRIO_NAMES:
        if states.get(name, "ABSENT") != "ABSENT":
            problems.append(f"legacy trio binding unexpectedly present: {name}")
    if problems:
        print("B54_ENGINE_OVERLAY_ROTATION_VERIFY=FAIL", file=sys.stderr)
        print(f"REASON={'; '.join(problems)}", file=sys.stderr)
        print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO", file=sys.stderr)
        print("SECRET_VALUES_READ=0", file=sys.stderr)
        return 1
    print(f"ENGINE_SERVED_VERSION_ID={args.active_version}")
    print(f"ENGINE_V1_SERVED_BINDING={states[REGISTRY_SECRET_NAME]}")
    print(f"ENGINE_OVERLAY_SERVED_BINDING={states[OVERLAY_SECRET_NAME]}")
    print("LEGACY_TRIO_SERVED_BINDING=ABSENT")
    print("B54_ENGINE_OVERLAY_ROTATION_POST_READBACK=PASS")
    print("ENGINE_BASE_V1_MUTATION=0")
    print("LEGACY_TRIO_MUTATION=0")
    print("UNRELATED_SECRET_MUTATION=0")
    print("SERVED_VERSION_READBACK=YES")
    print("SETTINGS_PLANE_ONLY_ACCEPTANCE=NO")
    print("BINDING_NAME_AND_TYPE_ONLY=YES")
    print("SECRET_VALUES_READ=0")
    print("RAW_SECRET_OUTPUT=0")
    print("RAW_OVERLAY_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("RUNTIME_SUCCESS=UNPROVEN_PENDING_PHASE_A")
    print("PRODUCTION_MUTATION=0")
    return 0


def _cmd_failure_evidence(args: argparse.Namespace) -> int:
    evidence = bounded_cloudflare_failure_evidence(args.response, args.http_status)
    cleaned = delete_response_file(args.response)
    codes = evidence["error_codes"]
    print("B54_ENGINE_OVERLAY_ROTATION=FAIL")
    print(f"CLOUDFLARE_HTTP_STATUS={evidence['http_status']}")
    print(f"CLOUDFLARE_SUCCESS={evidence['success']}")
    print(f"CLOUDFLARE_ERROR_CODE_COUNT={evidence['error_codes_total']}")
    print(f"CLOUDFLARE_ERROR_CODE={codes[0] if codes else 'NONE'}")
    print(f"CLOUDFLARE_ERROR_CODES={','.join(str(code) for code in codes) or 'NONE'}")
    print(f"CLOUDFLARE_ERROR_BODY_PARSABLE={'YES' if evidence['body_parsable'] else 'NO'}")
    print("CLOUDFLARE_ERROR_MESSAGE_OUTPUT=0")
    print("CLOUDFLARE_RESPONSE_BODY_OUTPUT=0")
    print(f"RESPONSE_TEMP_CLEANUP={'PASS' if cleaned else 'FAIL'}")
    print("RAW_SECRET_OUTPUT=0")
    print("RAW_OVERLAY_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="b54_engine_caller_registry_overlay_rotation.py",
        description=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    classify = sub.add_parser(
        "classify", help="classify served-version caller authority (NAME/TYPE only)"
    )
    classify.add_argument("--version-detail", required=True, type=Path)
    classify.add_argument("--active-version", required=True)
    classify.set_defaults(handler=_cmd_classify)

    plan = sub.add_parser(
        "plan", help="build the bounded overlay-only PUT body from the raw credential"
    )
    plan.add_argument(
        "--credential-env",
        required=True,
        help="environment variable holding the raw new Claw credential",
    )
    plan.add_argument("--output", required=True, type=Path)
    plan.set_defaults(handler=_cmd_plan)

    verify = sub.add_parser(
        "verify", help="post-mutation served-version NAME/TYPE-only readback"
    )
    verify.add_argument("--version-detail", required=True, type=Path)
    verify.add_argument("--active-version", required=True)
    verify.set_defaults(handler=_cmd_verify)

    failure = sub.add_parser(
        "failure-evidence",
        help="bounded non-secret evidence for a failed secret PUT (never the response body)",
    )
    failure.add_argument("--response", required=True, type=Path)
    failure.add_argument(
        "--http-status", default="", help="curl HTTP status (bounded digits)"
    )
    failure.set_defaults(handler=_cmd_failure_evidence)

    args = parser.parse_args(args_in)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
