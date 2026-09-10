#!/usr/bin/env python3
"""Plan and verify the B54 Engine caller-registry V1 provisioning mutation.

This gate provisions ``PADIEM_ENGINE_CALLER_REGISTRY_V1`` (type secret_text)
on the ``padiem-ai-engine`` worker so that the Claw caller ``b54-kagent``
(allowed to ``b54-padiem-claw``) is present in the Engine caller authority.

Three secrets are consumed, all from environment variables only (never argv,
never workflow inputs, never stdout):

- ``B54_ENGINE_CALLER_REGISTRY_V1_BASELINE``: the private baseline — the
  complete V1 registry plaintext held by the owner. Required on the
  preservation path (live V1 already present).
- ``B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS``: the bounded,
  NON-SECRET currentness attestation issued by the private authority process
  (#2400). Required on the preservation path; it is the only proof that the
  supplied baseline is the currently authoritative complete payload. It
  carries no registry plaintext and no credential material.
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

Currentness contract (``BASELINE_CURRENTNESS_PROVEN``):
A structurally valid baseline is NOT sufficient: a stale yet well-formed
baseline could overwrite newer live authority and silently drop unknown
callers. Therefore ``EXTEND_REQUIRED`` additionally requires a canonical,
bounded, non-secret attestation (canonical form)::

    b54-currentness-v1 authority=b54-preservation-authority \
baseline_sha256=<64-lowercase-hex> caller_count=<1-64> \
issued_at=<YYYY-MM-DDTHH:MM:SSZ>

The authority id is the canonical source constant ``CURRENTNESS_AUTHORITY_ID``
(not a free-form field), so credential-shaped material can never occupy that
slot or be echoed into evidence. The gate fails closed unless the attestation
is present, canonical, carries the approved authority, was issued for the
*exact* supplied baseline (SHA-256 of its UTF-8 bytes), matches the baseline
caller count, and is fresh with respect to the source-bounded maximum age. ``BASELINE_CURRENTNESS_PROVEN=YES`` is emitted only then, and the
workflow refuses to reach the PUT unless it is. This proves the private
authority certified the baseline as the currently authoritative complete
payload; it does NOT (and cannot) prove equality with the opaque Cloudflare
``secret_text`` value, which is never retrievable.

The greenfield path (all caller authority ABSENT) remains only as an isolated,
tested capability: a single-caller registry with ``b54-kagent``. It is not the
current Production path and forbids both the baseline and the attestation.

This script never prints a credential, a registry, or any secret value.
Readback is NAME/TYPE-only and reuses the merged B54 caller-authority
read-only classifier so this gate and the read-only gate (#2397) cannot drift.

Subcommands:

- ``classify --settings <worker-settings.json>`` — NAME/TYPE-only authority
  classification plus the provision disposition.
- ``plan --disposition <DISP> --credential-env <ENV> [--baseline-env <ENV>]
  [--currentness-env <ENV>] --output <put-body.json>`` — build the bounded PUT
  body from secrets (and enforce the currentness guard on the preservation
  path).
- ``verify --settings <worker-settings.json>`` — post-mutation NAME/TYPE-only
  readback: registry secret present with type ``secret_text``.
- ``failure-evidence --response <cf-response.json> --http-status <status>`` —
  bounded, NON-SECRET failure evidence for a failed secret PUT. Cloudflare
  error message text and the response body are NEVER selected or printed
  (a future error message could reflect request material), so only the HTTP
  status, a boolean success, integer error codes, and fixed local markers are
  emitted. The response temp file is deleted after extraction.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
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

# Baseline currentness attestation contract (#2400 private authority issues it).
CURRENTNESS_ATTESTATION_PREFIX = "b54-currentness-v1"
# The only authority id the gate accepts. A canonical source constant (not a
# free-form field) so credential-shaped material can never be carried in the
# authority slot or echoed into evidence, and so "valid" means a recognised
# private authority — not merely a well-formed string.
CURRENTNESS_AUTHORITY_ID = "b54-preservation-authority"
CURRENTNESS_FIELD_ORDER = ("authority", "baseline_sha256", "caller_count", "issued_at")
CURRENTNESS_FINGERPRINT_ALGO = "sha256"
CURRENTNESS_MAX_ATTESTATION_BYTES = 1024
# Source-bounded freshness: an attestation older than this cannot prove that
# the baseline is the CURRENT live authority.
CURRENTNESS_MAX_AGE_SECONDS = 24 * 60 * 60
# Tolerated clock skew for an attestation issued slightly in the future.
CURRENTNESS_MAX_FUTURE_SKEW_SECONDS = 5 * 60

# Bounded failure-evidence bounds (a Cloudflare response body is never emitted).
MAX_CLOUDFLARE_ERROR_CODES = 8
_HTTP_STATUS_RE = re.compile(r"^\d{3}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_ISSUED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FORBIDDEN_ATTESTATION_CHARS = ('{', '}', '"')

_ENTRY_KEYS = frozenset({"caller_id", "credential", "allowed_app_ids"})
_TOP_LEVEL_KEYS = frozenset({"version", "callers"})


class ProvisionPlanError(RuntimeError):
    """Safe provisioning-plan failure; never carries credential content."""


def authority_disposition(states: dict[str, str]) -> str:
    """Aggregate NAME/TYPE authority states into the provision disposition.

    - ``EXTEND_REQUIRED``: V1 registry already present as ``secret_text``.
      Its value is opaque/non-retrievable; extension requires the private
      baseline secret, the currentness attestation, and follows the
      preservation path.
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


def baseline_fingerprint(baseline: str) -> str:
    """SHA-256 of the exact baseline plaintext bytes (non-secret reference)."""
    if not isinstance(baseline, str) or not baseline:
        raise ProvisionPlanError("baseline registry is missing or blank")
    return hashlib.sha256(baseline.encode("utf-8")).hexdigest()


def parse_currentness_attestation(attestation: str) -> dict:
    """Strictly parse the bounded, NON-SECRET currentness attestation.

    The canonical form is a single ASCII line with exactly the fixed prefix
    and exactly the four ordered ``key=value`` fields. Anything else — raw
    registry JSON, a raw credential, an appended or reordered field — fails
    closed, so secret material can never be smuggled in as provenance.
    """
    if not isinstance(attestation, str) or not attestation.strip():
        raise ProvisionPlanError("baseline currentness attestation is missing or blank")
    if not attestation.isascii():
        raise ProvisionPlanError("baseline currentness attestation must be ASCII")
    if any(ch in attestation for ch in _FORBIDDEN_ATTESTATION_CHARS):
        raise ProvisionPlanError(
            "baseline currentness attestation must not contain registry or credential material"
        )
    if "\n" in attestation or "\r" in attestation or "\t" in attestation:
        raise ProvisionPlanError("baseline currentness attestation must be a single line")
    if len(attestation.encode("utf-8")) > CURRENTNESS_MAX_ATTESTATION_BYTES:
        raise ProvisionPlanError("baseline currentness attestation exceeds the bounded size")

    fields = attestation.split(" ")
    if len(fields) != 1 + len(CURRENTNESS_FIELD_ORDER):
        raise ProvisionPlanError(
            "baseline currentness attestation must have exactly the canonical fields"
        )
    if fields[0] != CURRENTNESS_ATTESTATION_PREFIX:
        raise ProvisionPlanError(
            "baseline currentness attestation prefix is not the approved authority contract"
        )
    parsed: dict[str, str] = {}
    for token, key in zip(fields[1:], CURRENTNESS_FIELD_ORDER):
        name, sep, value = token.partition("=")
        if sep != "=" or name != key or not value:
            raise ProvisionPlanError(
                "baseline currentness attestation fields are not canonical and ordered"
            )
        parsed[key] = value

    _check_identifier("currentness authority", parsed["authority"])
    if parsed["authority"] != CURRENTNESS_AUTHORITY_ID:
        raise ProvisionPlanError(
            "baseline currentness authority is not the approved private authority"
        )
    fingerprint = parsed["baseline_sha256"]
    if not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ProvisionPlanError(
            "baseline currentness fingerprint must be 64 lowercase hex characters"
        )
    try:
        caller_count = int(parsed["caller_count"])
    except ValueError:
        raise ProvisionPlanError("baseline currentness caller_count must be an integer") from None
    if not 1 <= caller_count <= MAX_ENGINE_CALLERS:
        raise ProvisionPlanError("baseline currentness caller_count is out of bounds")
    issued_at_raw = parsed["issued_at"]
    if not _ISSUED_AT_RE.fullmatch(issued_at_raw):
        raise ProvisionPlanError(
            "baseline currentness issued_at must be UTC YYYY-MM-DDTHH:MM:SSZ"
        )
    issued_at = datetime.strptime(issued_at_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return {
        "authority": parsed["authority"],
        "baseline_sha256": fingerprint,
        "caller_count": caller_count,
        "issued_at": issued_at,
        "issued_at_raw": issued_at_raw,
    }


def format_currentness_attestation(
    *,
    authority: str,
    baseline: str,
    caller_count: int,
    issued_at: datetime,
) -> str:
    """Emit the canonical attestation (contract documentation for #2400)."""
    _check_identifier("currentness authority", authority)
    if authority != CURRENTNESS_AUTHORITY_ID:
        raise ProvisionPlanError(
            "currentness authority is not the approved private authority"
        )
    if isinstance(caller_count, bool) or not isinstance(caller_count, int):
        raise ProvisionPlanError("currentness caller_count must be an integer")
    if not 1 <= caller_count <= MAX_ENGINE_CALLERS:
        raise ProvisionPlanError("currentness caller_count is out of bounds")
    if not isinstance(issued_at, datetime) or issued_at.tzinfo is None:
        raise ProvisionPlanError("currentness issued_at must be timezone-aware")
    stamp = issued_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"{CURRENTNESS_ATTESTATION_PREFIX} authority={authority} "
        f"baseline_sha256={baseline_fingerprint(baseline)} "
        f"caller_count={caller_count} issued_at={stamp}"
    )


def assert_baseline_currentness(
    baseline: str,
    payload: dict,
    attestation: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Fail closed unless the baseline is proven currently authoritative.

    Binds the attestation to the EXACT supplied baseline (UTF-8 SHA-256), to
    its caller count, and to a source-bounded freshness window. Returns the
    bounded non-secret attestation metadata on success.
    """
    meta = parse_currentness_attestation(attestation)
    reference = now if now is not None else datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ProvisionPlanError("currentness clock must be timezone-aware")
    age_seconds = (reference - meta["issued_at"]).total_seconds()
    if age_seconds < -CURRENTNESS_MAX_FUTURE_SKEW_SECONDS:
        raise ProvisionPlanError("baseline currentness attestation is issued in the future")
    if age_seconds > CURRENTNESS_MAX_AGE_SECONDS:
        raise ProvisionPlanError(
            "baseline currentness attestation is stale (older than the bounded maximum age)"
        )
    if baseline_fingerprint(baseline) != meta["baseline_sha256"]:
        raise ProvisionPlanError(
            "baseline currentness fingerprint does not match the supplied baseline"
        )
    if meta["caller_count"] != len(payload["callers"]):
        raise ProvisionPlanError(
            "baseline currentness caller_count does not match the supplied baseline"
        )
    return meta


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


def _cmd_failure_evidence(args: argparse.Namespace) -> int:
    """Emit bounded non-secret PUT-failure evidence, then delete the response."""
    evidence = bounded_cloudflare_failure_evidence(args.response, args.http_status)
    cleaned = delete_response_file(args.response)
    codes = evidence["error_codes"]
    print("B54_ENGINE_CALLER_REGISTRY=FAIL")
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
    print("RAW_REGISTRY_OUTPUT=0")
    print("SECRET_VALUE_OUTPUT=0")
    print("PRODUCTION_MUTATION=0")
    return 0


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
        currentness: dict | None = None
        if args.disposition == "EXTEND_REQUIRED":
            baseline = _read_env_secret(args.baseline_env, label="private baseline registry")
            # Fail closed BEFORE parsing/merging anything when the currentness
            # attestation is missing: a structurally valid baseline is not
            # proof that it is the CURRENT live authority.
            attestation = _read_env_secret(
                args.currentness_env, label="baseline currentness attestation"
            )
            baseline_payload = parse_baseline_registry(baseline)
            currentness = assert_baseline_currentness(
                baseline, baseline_payload, attestation
            )
            payload, verdict = merge_b54_caller(baseline_payload, credential)
        else:
            if args.baseline_env and os.environ.get(args.baseline_env, ""):
                raise ProvisionPlanError(
                    "baseline is forbidden on the greenfield path (all-ABSENT)"
                )
            if args.currentness_env and os.environ.get(args.currentness_env, ""):
                raise ProvisionPlanError(
                    "currentness attestation is forbidden on the greenfield path (all-ABSENT)"
                )
            payload = build_registry_payload(credential=credential)
            verdict = "GREENFIELD_SINGLE_CALLER"
    except ProvisionPlanError as exc:
        print("B54_ENGINE_CALLER_REGISTRY_PLAN=FAIL", file=sys.stderr)
        if args.disposition == "EXTEND_REQUIRED":
            print("BASELINE_CURRENTNESS_PROVEN=NO", file=sys.stderr)
        print(f"REASON={exc}", file=sys.stderr)
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
        assert currentness is not None
        print("B61_PRESERVATION_ASSERT=PASS")
        print("UNKNOWN_CALLERS_PRESERVED=PASS")
        print("BASELINE_CALLERS_PRESERVED_VERBATIM=PASS")
        print("BASELINE_CURRENTNESS_PROVEN=YES")
        print(f"BASELINE_CURRENTNESS_AUTHORITY={CURRENTNESS_AUTHORITY_ID}")
        print(f"BASELINE_CURRENTNESS_ISSUED_AT={currentness['issued_at_raw']}")
        print(f"BASELINE_CURRENTNESS_CALLER_COUNT={currentness['caller_count']}")
        print("BASELINE_CURRENTNESS_FINGERPRINT_BOUND=YES")
        print("CURRENTNESS_ATTESTATION_CONTAINS_SECRET_MATERIAL=NO")
        if verdict == "ALREADY_COMPATIBLE":
            print("B54_KAGENT_APPEND_ONLY=ALREADY_COMPATIBLE")
        else:
            print("B54_KAGENT_APPEND_ONLY=PASS")
    else:
        print("B54_KAGENT_APPEND_ONLY=GREENFIELD_SINGLE_CALLER")
        print("BASELINE_CURRENTNESS_PROVEN=GREENFIELD_NOT_APPLICABLE")
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
    plan.add_argument(
        "--currentness-env",
        default="",
        help=(
            "environment variable holding the non-secret baseline currentness attestation "
            "(required on the preservation path)"
        ),
    )
    plan.add_argument("--output", required=True, type=Path)

    verify = sub.add_parser("verify", help="post-mutation NAME/TYPE-only readback")
    verify.add_argument("--settings", required=True, type=Path)

    failure = sub.add_parser(
        "failure-evidence",
        help="bounded non-secret evidence for a failed secret PUT (never the response body)",
    )
    failure.add_argument("--response", required=True, type=Path)
    failure.add_argument("--http-status", default="", help="curl HTTP status (bounded digits)")

    args = parser.parse_args(args_in)
    if args.command == "classify":
        return _cmd_classify(args)
    if args.command == "plan":
        return _cmd_plan(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "failure-evidence":
        return _cmd_failure_evidence(args)
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
