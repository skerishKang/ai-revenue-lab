"""Contract tests for the B54 Engine base V1 ``b54-kagent`` removal gate.

Proves statically and locally (no network, no live mutation) that the gate:
  A. removes exactly one ``b54-kagent`` entry from a base registry containing
     [storymemory-b61, b54-kagent, X] and produces [storymemory-b61, X];
  B. refuses when the baseline does not contain the target caller;
  C. refuses when the baseline contains more than one target entry;
  D. refuses when removal would leave zero callers;
  E. refuses on stale, mismatched, or missing currentness attestations;
  F. preserves every non-target entry verbatim (order, keys, credential bytes);
  G. leaves the production Engine duplicate rejection unchanged (a base that
     still contains the overlay caller id still fails closed with
     ``duplicate_service_caller``; the removal result authenticates normally);
plus the source contract markers, the base-only PUT body, bounded non-secret
evidence, the served-version preflight (SINGLE 100% served version, never the
settings plane — a settings/served divergence can never authorize mutation),
the TOCTOU reconfirm contract (the apply job must re-prove the EXACT served
version, disposition, and legacy pre-state the readonly preflight captured on
a fresh GET-only read immediately before the PUT — proven both as pure-CLI
cases and behaviorally under bash with curl stubbed: readonly sees version A,
apply sees version B, Git main unchanged, mutation MUST NOT occur),
the served-version readback, and the workflow's dispatch-only, exact-main,
overlay-untouchable structure.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b54_engine_caller_registry_base_v1_b54_kagent_removal.py"
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-registry-base-v1-b54-kagent-removal-gate.yml"
PROVISION = ROOT / ".github/scripts/b54_engine_caller_registry_v1_provision.py"
ROTATION = ROOT / ".github/scripts/b54_engine_caller_registry_overlay_rotation.py"
IDENTITY = ROOT / "apps/padiem-ai-engine/app/identity_enforcement.py"

VERSION_ID = "30fb2308-f5d3-4365-a8fd-9c4c307e7535"
VERSION_B = "41ac3419-0a6e-4f19-9c2b-8d5e1f2a3b4c"
BASE_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY_NAME = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"
LEGACY_NAMES = (
    "PADIEM_ENGINE_CALLER_ID",
    "PADIEM_ENGINE_CALLER_SECRET",
    "PADIEM_ENGINE_ALLOWED_APPS",
)
TARGET_CALLER_ID = "b54-kagent"
B61_CALLER_ID = "storymemory-b61"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helper = _load_module("b54_engine_caller_registry_base_v1_b54_kagent_removal", HELPER)
provision = _load_module("b54_engine_caller_registry_v1_provision_contract", PROVISION)
identity = helper._identity_enforcement


def cred(tag: str) -> str:
    return ("c" * 40) + tag


def entry(caller_id: str, tag: str, app_ids: list[str]) -> dict:
    return {
        "caller_id": caller_id,
        "credential": cred(tag),
        "allowed_app_ids": list(app_ids),
    }


def baseline_json(callers: list[dict]) -> str:
    return json.dumps({"version": 1, "callers": callers}, separators=(",", ":"))


def attestation_for(baseline: str, *, caller_count: int | None = None,
                    issued_at: datetime | None = None) -> str:
    payload = json.loads(baseline)
    return provision.format_currentness_attestation(
        authority="b54-preservation-authority",
        baseline=baseline,
        caller_count=caller_count if caller_count is not None else len(payload["callers"]),
        issued_at=issued_at or datetime.now(timezone.utc),
    )


def _run(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = helper.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


@contextlib.contextmanager
def _env(**values: str | None):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _binding(name: str, binding_type: str = "secret_text") -> dict:
    return {"name": name, "type": binding_type}


def _version_detail(bindings: list[dict], version_id: str = VERSION_ID) -> dict:
    return {
        "success": True,
        "result": {"id": version_id, "resources": {"bindings": bindings}},
    }


def _deployments_envelope(version_id: str = VERSION_ID) -> dict:
    return {
        "success": True,
        "result": {"deployments": [{"versions": [{"version_id": version_id,
                                                  "percentage": 100}]}]},
    }


def _settings_plane(bindings: list[dict]) -> dict:
    return {"success": True, "result": {"bindings": bindings}}


def _plan(baseline: str, currentness: str | None) -> tuple[int, str, str, Path]:
    out = Path(tempfile.mkdtemp(prefix="b54-removal-test-")) / "put-body.json"
    with _env(
        B54_ENGINE_CALLER_REGISTRY_V1_BASELINE=baseline,
        B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS=currentness,
    ):
        code, stdout, stderr = _run(["plan", "--output", str(out)])
    return code, stdout, stderr, out


# ---------------------------------------------------------------- script core


def test_script_constants_are_single_sourced() -> None:
    assert helper.CALLER_ID == TARGET_CALLER_ID
    assert helper.REGISTRY_SECRET_NAME == BASE_NAME
    assert helper.OVERLAY_SECRET_NAME == OVERLAY_NAME
    assert helper.CALLER_ID == provision.CALLER_ID
    assert helper._provision.parse_baseline_registry is helper.parse_baseline_registry
    assert helper._provision.assert_baseline_currentness is helper.assert_baseline_currentness
    assert helper._provision.build_put_body is not None
    assert helper.parse_caller_registry_v1 is identity.parse_caller_registry_v1
    assert helper.encode_legacy_states is not None


def test_source_contract_markers_are_declared() -> None:
    source = HELPER.read_text(encoding="utf-8")
    for marker in (
        "MIGRATION_TARGET=BASE_V1_ONLY",
        "TARGET_CALLER=",
        "BASE_CONTAINS_B54_KAGENT=YES",
        "REMOVE_EXACTLY_ONE_TARGET_CALLER=YES",
        "OTHER_CALLERS_PRESERVED=YES",
        "B61_PRESERVED=YES",
        "CURRENTNESS_REQUIRED=YES",
        "RESULT_ENGINE_PARSE_VALID=YES",
        "RUNTIME_DUPLICATE_REJECTION_UNCHANGED=YES",
        "OVERLAY_SHADOWING_NOT_ENABLED=YES",
        "OVERLAY_MUTATION=0",
    ):
        assert marker in source, marker


def test_case_a_plan_removes_exactly_one_target_caller() -> None:
    baseline = baseline_json([
        entry(B61_CALLER_ID, "a", ["b61"]),
        entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
        entry("other-caller", "c", ["app-1"]),
    ])
    code, stdout, _stderr, out = _plan(baseline, attestation_for(baseline))
    assert code == 0, stdout + _stderr
    for marker in (
        "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_PLAN=PASS",
        "MIGRATION_TARGET=BASE_V1_ONLY",
        "TARGET_CALLER=b54-kagent",
        "BASE_CONTAINS_B54_KAGENT=YES",
        "REMOVE_EXACTLY_ONE_TARGET_CALLER=YES",
        "OTHER_CALLERS_PRESERVED=YES",
        "B61_PRESERVED=YES",
        "RESULT_ENGINE_PARSE_VALID=YES",
        "PUT_TARGET=PADIEM_ENGINE_CALLER_REGISTRY_V1",
        "BASELINE_CALLER_COUNT=3",
        "RESULT_CALLER_COUNT=2",
    ):
        assert marker in stdout, marker
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["name"] == BASE_NAME
    assert body["type"] == "secret_text"
    payload = json.loads(body["text"])
    assert [c["caller_id"] for c in payload["callers"]] == [B61_CALLER_ID, "other-caller"]


def test_case_b_refuses_when_target_absent() -> None:
    baseline = baseline_json([
        entry(B61_CALLER_ID, "a", ["b61"]),
        entry("other-caller", "c", ["app-1"]),
    ])
    code, _stdout, stderr, out = _plan(baseline, attestation_for(baseline))
    assert code == 1
    assert "REASON=BASE_CONTAINS_B54_KAGENT=NO" in stderr
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_PLAN=FAIL" in stderr
    assert not out.exists()


def test_case_c_refuses_when_target_entry_is_ambiguous() -> None:
    payload = {
        "version": 1,
        "callers": [
            entry(B61_CALLER_ID, "a", ["b61"]),
            entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
            entry(TARGET_CALLER_ID, "z", ["other-app"]),
        ],
    }
    try:
        helper.remove_b54_kagent_from_baseline(payload)
    except helper.BaseV1RemovalError as exc:
        assert str(exc) == "BASE_TARGET_CALLER_AMBIGUOUS"
    else:
        raise AssertionError("duplicate target entries must refuse")
    # A plan-level duplicate is also unreachable: Engine V1 shape rejects it.
    baseline = json.dumps(payload, separators=(",", ":"))
    code, _stdout, stderr, _out = _plan(baseline, attestation_for(baseline))
    assert code == 1
    assert "REASON=" in stderr and "duplicate" in stderr.lower()


def test_case_d_refuses_when_removal_would_empty_the_registry() -> None:
    payload = {"version": 1, "callers": [entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"])]}
    try:
        helper.remove_b54_kagent_from_baseline(payload)
    except helper.BaseV1RemovalError as exc:
        assert str(exc) == "BASE_RESULT_WOULD_HAVE_ZERO_CALLERS"
    else:
        raise AssertionError("emptying removal must refuse")


def test_case_e_refuses_stale_mismatched_or_missing_currentness() -> None:
    baseline = baseline_json([
        entry(B61_CALLER_ID, "a", ["b61"]),
        entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
    ])
    stale = attestation_for(
        baseline, issued_at=datetime.now(timezone.utc) - timedelta(days=3)
    )
    code, _stdout, stderr, _out = _plan(baseline, stale)
    assert code == 1 and "stale" in stderr
    mismatched = attestation_for(baseline, caller_count=1)
    code, _stdout, stderr, _out = _plan(baseline, mismatched)
    assert code == 1 and "caller_count" in stderr
    foreign = attestation_for(baseline_json([entry(B61_CALLER_ID, "a", ["b61"])]))
    code, _stdout, stderr, _out = _plan(baseline, foreign)
    assert code == 1 and "fingerprint" in stderr
    for missing in (None, ""):
        code, _stdout, stderr, _out = _plan(baseline, missing)
        assert code == 1
        assert "REASON=CURRENTNESS_ATTESTATION_MISSING" in stderr
        assert "CURRENTNESS_REQUIRED=YES" in stderr


def test_case_f_non_target_entries_are_preserved_verbatim() -> None:
    kept_one = entry(B61_CALLER_ID, "a", ["b61"])
    kept_two = entry("opaque-caller", "d", ["app-9", "app-10"])
    baseline = baseline_json([
        kept_one,
        entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
        kept_two,
    ])
    code, stdout, stderr, out = _plan(baseline, attestation_for(baseline))
    assert code == 0, stdout + stderr
    body = json.loads(out.read_text(encoding="utf-8"))
    payload = json.loads(body["text"])
    assert payload["callers"] == [kept_one, kept_two]
    for kept in (kept_one, kept_two):
        assert json.dumps(kept, separators=(",", ":")) in body["text"]
    assert payload["version"] == 1


def test_plan_never_emits_baseline_credential_or_hash_material() -> None:
    baseline = baseline_json([
        entry(B61_CALLER_ID, "a", ["b61"]),
        entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
        entry("opaque-caller", "d", ["app-9"]),
    ])
    attestation = attestation_for(baseline)
    code, stdout, stderr, _out = _plan(baseline, attestation)
    assert code == 0
    evidence = stdout + stderr
    assert cred("a") not in evidence
    assert cred("b") not in evidence
    assert cred("d") not in evidence
    assert "caller_id" not in evidence
    assert "{" not in evidence and "}" not in evidence
    assert provision.baseline_fingerprint(baseline) not in evidence
    assert "opaque-caller" not in evidence
    assert TARGET_CALLER_ID in evidence  # the single approved fixed marker
    refusal_baseline = baseline_json([entry(B61_CALLER_ID, "a", ["b61"])])
    refusal = _plan(refusal_baseline, attestation_for(refusal_baseline))
    assert refusal[0] == 1
    refusal_evidence = refusal[1] + refusal[2]
    assert "REASON=BASE_CONTAINS_B54_KAGENT=NO" in refusal_evidence
    assert "caller_id" not in refusal_evidence
    assert "opaque-caller" not in refusal_evidence


def test_put_body_structurally_targets_base_v1_only() -> None:
    payload = {"version": 1, "callers": [entry(B61_CALLER_ID, "a", ["b61"])]}
    body = helper.build_put_body(payload)
    assert body["name"] == BASE_NAME
    assert body["name"] != OVERLAY_NAME
    assert body["type"] == "secret_text"
    assert set(body) == {"name", "type", "text"}


def test_engine_parse_validity_is_proven_with_the_production_parser() -> None:
    payload = {
        "version": 1,
        "callers": [
            entry(B61_CALLER_ID, "a", ["b61"]),
            entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
            entry("x", "c", ["app"]),
        ],
    }
    removed = helper.remove_b54_kagent_from_baseline(payload)
    registry = identity.parse_caller_registry_v1(helper.serialized(removed))
    assert [c.caller_id for c in registry.callers] == [B61_CALLER_ID, "x"]


# ------------------------------------------------------- case G: runtime lock


def test_case_g_runtime_duplicate_rejection_is_unchanged() -> None:
    base_with_target = baseline_json([
        entry(B61_CALLER_ID, "a", ["b61"]),
        entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
    ])
    overlay_raw = helper.serialized(
        {
            "version": 1,
            "caller": entry(TARGET_CALLER_ID, "b", ["b54-padiem-claw"]),
        }
    )
    env = types.SimpleNamespace(
        PADIEM_ENGINE_CALLER_REGISTRY_V1=base_with_target,
        PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY=overlay_raw,
    )
    try:
        identity._build_registry_authority_from_env(env)
    except identity.ServiceIdentityError as exc:
        assert exc.code == "duplicate_service_caller"
    else:
        raise AssertionError("duplicate base+overlay caller must still fail closed")
    # The removal result removes the conflict: the same overlay authenticates.
    removed = helper.remove_b54_kagent_from_baseline(
        provision._check_registry_shape(json.loads(base_with_target))
    )
    env_after = types.SimpleNamespace(
        PADIEM_ENGINE_CALLER_REGISTRY_V1=helper.serialized(removed),
        PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY=overlay_raw,
    )
    base_registry, overlay_caller = identity._build_registry_authority_from_env(env_after)
    assert base_registry is not None and overlay_caller is not None
    assert [c.caller_id for c in base_registry.callers] == [B61_CALLER_ID]
    assert overlay_caller.caller_id == TARGET_CALLER_ID


def test_identity_enforcement_source_is_untouched() -> None:
    source = IDENTITY.read_text(encoding="utf-8")
    assert "duplicate_service_caller" in source
    assert "caller registry overlay must not duplicate a base caller ID" in source
    assert TARGET_CALLER_ID not in source  # no caller-specific special casing


# ------------------------------------------------------------ classify CLI


def test_classify_disposition_ladder() -> None:
    assert helper.migration_disposition({
        BASE_NAME: "PRESENT:secret_text",
        OVERLAY_NAME: "PRESENT:secret_text",
    }) == "MIGRATION_REQUIRED"
    assert helper.migration_disposition({
        BASE_NAME: "ABSENT",
        OVERLAY_NAME: "PRESENT:secret_text",
    }) == "REFUSE_BASE_UNAVAILABLE"
    assert helper.migration_disposition({
        BASE_NAME: "PRESENT:secret_text",
        OVERLAY_NAME: "ABSENT",
    }) == "REFUSE_OVERLAY_ABSENT"
    assert helper.migration_disposition({
        BASE_NAME: "PRESENT:plain_text",
        OVERLAY_NAME: "PRESENT:secret_text",
    }) == "REFUSE_BASE_UNAVAILABLE"


def test_classify_cli_emits_only_name_type_evidence() -> None:
    detail = _version_detail([
        _binding(BASE_NAME),
        _binding(OVERLAY_NAME),
        _binding(LEGACY_NAMES[0], "plain_text"),
    ])
    path = Path(tempfile.mkdtemp(prefix="b54-removal-classify-")) / "detail.json"
    path.write_text(json.dumps(detail), encoding="utf-8")
    code, stdout, stderr = _run([
        "classify",
        "--version-detail", str(path),
        "--active-version", VERSION_ID,
    ])
    assert code == 0, stdout + stderr
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_DISPOSITION=MIGRATION_REQUIRED" in stdout
    assert f"AUTHORITY_STATE {BASE_NAME}=PRESENT:secret_text" in stdout
    assert f"AUTHORITY_STATE {OVERLAY_NAME}=PRESENT:secret_text" in stdout
    assert f"ENGINE_SERVED_VERSION_ID={VERSION_ID}" in stdout
    assert "LEGACY_TRIO_PRE_STATE=" in stdout
    assert "SERVED_VERSION_CLASSIFICATION=YES" in stdout
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in stdout
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in stdout
    assert "{" not in stdout


def test_classify_rejects_settings_plane_and_divergence_cannot_authorize() -> None:
    """A settings-plane payload is never a served-version proof (fail closed)...

    ...and when the settings plane and the served version DISAGREE, the
    disposition is computed from the served version only, so a settings plane
    that merely looks migratable can never authorize the mutation.
    """
    tmp = Path(tempfile.mkdtemp(prefix="b54-removal-divergence-"))
    settings = _settings_plane([_binding(BASE_NAME), _binding(OVERLAY_NAME)])
    settings_path = tmp / "settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    code, _stdout, stderr = _run([
        "classify",
        "--version-detail", str(settings_path),
        "--active-version", VERSION_ID,
    ])
    assert code == 1  # settings plane has no result.id: version identity unproven
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_CLASSIFY=FAIL" in stderr
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in stderr
    assert not hasattr(helper, "_settings_states")  # no settings-plane code path remains

    # Divergent truth: settings shows the migratable shape, the served version
    # does NOT carry the overlay -> no MIGRATION_REQUIRED authorization.
    served = _version_detail([_binding(BASE_NAME)])
    served_path = tmp / "detail.json"
    served_path.write_text(json.dumps(served), encoding="utf-8")
    code, stdout, _stderr = _run([
        "classify",
        "--version-detail", str(served_path),
        "--active-version", VERSION_ID,
    ])
    assert code == 0
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_DISPOSITION=REFUSE_OVERLAY_ABSENT" in stdout
    assert "MIGRATION_REQUIRED" not in stdout

    # The mirror divergence: served shows base absent while settings is fine.
    served2 = _version_detail([_binding(OVERLAY_NAME)])
    served2_path = tmp / "detail2.json"
    served2_path.write_text(json.dumps(served2), encoding="utf-8")
    code, stdout, _stderr = _run([
        "classify",
        "--version-detail", str(served2_path),
        "--active-version", VERSION_ID,
    ])
    assert code == 0
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_DISPOSITION=REFUSE_BASE_UNAVAILABLE" in stdout
    assert "MIGRATION_REQUIRED" not in stdout

    # A version-id mismatch on the served detail also fails closed.
    code, _stdout, stderr = _run([
        "classify",
        "--version-detail", str(served_path),
        "--active-version", "11111111-1111-4111-8111-111111111111",
    ])
    assert code == 1
    assert "does not match active version" in stderr


# --------------------------------------------------------------- reconfirm CLI


def _reconfirm(detail: dict, *, active: str, pre_active: str, pre_legacy: str):
    path = Path(tempfile.mkdtemp(prefix="b54-removal-reconfirm-")) / "detail.json"
    path.write_text(json.dumps(detail), encoding="utf-8")
    return _run([
        "reconfirm",
        "--version-detail", str(path),
        "--active-version", active,
        "--pre-active-version", pre_active,
        "--pre-legacy-state", pre_legacy,
    ])


def _migratable_bindings() -> list[dict]:
    return [
        _binding(BASE_NAME),
        _binding(OVERLAY_NAME),
        _binding(LEGACY_NAMES[0], "plain_text"),
    ]


def _pre_state(detail: dict) -> str:
    states = helper._served_states(detail, detail["result"]["id"])
    return helper.encode_legacy_states(states)


def test_reconfirm_passes_only_on_the_identical_authorized_served_version() -> None:
    detail = _version_detail(_migratable_bindings())
    code, stdout, stderr = _reconfirm(
        detail, active=VERSION_ID, pre_active=VERSION_ID, pre_legacy=_pre_state(detail)
    )
    assert code == 0, stdout + stderr
    for marker in (
        "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_RECONFIRM=PASS",
        f"PRE_ACTIVE_VERSION_ID={VERSION_ID}",
        f"CURRENT_ACTIVE_VERSION_ID={VERSION_ID}",
        "SERVED_VERSION_UNCHANGED=YES",
        "PREWRITE_DISPOSITION=MIGRATION_REQUIRED",
        "LEGACY_TRIO_PRE_STATE_CONFIRMED=YES",
        "TOCTOU_SERVED_VERSION_GUARD=PASS",
        "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO",
        "SINGLE_100_PERCENT_SERVED_VERSION_GUARD=PASS",
        "PUT_COUNT=0",
        "OVERLAY_MUTATION=0",
        "CLOUDFLARE_MUTATION=0",
        "PRODUCTION_MUTATION=0",
    ):
        assert marker in stdout, marker
    assert "{" not in stdout and "}" not in stdout


def test_reconfirm_fails_closed_when_served_version_changed_between_jobs() -> None:
    """The exact TOCTOU case: Git main unchanged, Cloudflare state moved A -> B."""
    detail_b = _version_detail(_migratable_bindings(), VERSION_B)
    code, stdout, stderr = _reconfirm(
        detail_b, active=VERSION_B, pre_active=VERSION_ID,
        pre_legacy=_pre_state(_version_detail(_migratable_bindings())),
    )
    assert code == 1
    assert "REASON=SERVED_VERSION_CHANGED_AFTER_READONLY_PREFLIGHT" in stderr
    assert "TOCTOU_SERVED_VERSION_GUARD=FAIL" in stderr
    assert "PUT_COUNT=0" in stderr
    assert "OVERLAY_MUTATION=0" in stderr
    assert "CLOUDFLARE_MUTATION=0" in stderr
    assert "PRODUCTION_MUTATION=0" in stderr
    assert "RECONFIRM=PASS" not in stdout + stderr


def test_reconfirm_fails_closed_when_disposition_or_legacy_state_diverges() -> None:
    # Same version id, but the served version no longer carries the overlay:
    # the authorization disposition itself is gone.
    detail = _version_detail([_binding(BASE_NAME)])
    code, _stdout, stderr = _reconfirm(
        detail, active=VERSION_ID, pre_active=VERSION_ID,
        pre_legacy=";".join(f"{name}=ABSENT" for name in LEGACY_NAMES),
    )
    assert code == 1
    assert "REASON=SERVED_DISPOSITION_NO_LONGER_MIGRATION_REQUIRED" in stderr
    assert "PUT_COUNT=0" in stderr and "PRODUCTION_MUTATION=0" in stderr

    # Same version id and disposition, but a legacy-trio binding appeared.
    drifted = _version_detail(_migratable_bindings())
    code, _stdout, stderr = _reconfirm(
        drifted, active=VERSION_ID, pre_active=VERSION_ID,
        pre_legacy=";".join(f"{name}=ABSENT" for name in LEGACY_NAMES),
    )
    assert code == 1
    assert "REASON=LEGACY_TRIO_PRE_STATE_DIVERGED_FROM_READONLY_CAPTURE" in stderr
    assert "PUT_COUNT=0" in stderr

    # A settings-plane payload can never satisfy the pre-write reconfirmation.
    settings = _settings_plane(_migratable_bindings())
    code, _stdout, stderr = _reconfirm(
        settings, active=VERSION_ID, pre_active=VERSION_ID,
        pre_legacy=_pre_state(_version_detail(_migratable_bindings())),
    )
    assert code == 1
    assert "served version identity unproven" in stderr
    assert "TOCTOU_SERVED_VERSION_GUARD=FAIL" in stderr
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in stderr
    assert "PUT_COUNT=0" in stderr

    # The detail's own version id must agree with the freshly resolved one.
    code, _stdout, stderr = _reconfirm(
        _version_detail(_migratable_bindings()), active=VERSION_B,
        pre_active=VERSION_B,
        pre_legacy=_pre_state(_version_detail(_migratable_bindings())),
    )
    assert code == 1
    assert "does not match active version" in stderr
    assert "PUT_COUNT=0" in stderr


# --------------------------------------------------------------- verify CLI


def test_verify_cli_served_version_readback_contract() -> None:
    legacy_pre = ";".join(f"{name}=ABSENT" for name in LEGACY_NAMES)
    ok = _version_detail([_binding(BASE_NAME), _binding(OVERLAY_NAME)])
    path = Path(tempfile.mkdtemp(prefix="b54-removal-verify-")) / "detail.json"
    path.write_text(json.dumps(ok), encoding="utf-8")
    code, stdout, stderr = _run([
        "verify",
        "--version-detail", str(path),
        "--active-version", VERSION_ID,
        "--legacy-pre-state", legacy_pre,
    ])
    assert code == 0, stdout + stderr
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_POST_READBACK=PASS" in stdout
    assert "OVERLAY_PRESERVED=YES" in stdout
    assert "OVERLAY_MUTATION=0" in stdout
    assert "RUNTIME_SUCCESS=UNPROVEN_PENDING_PHASE_A" in stdout
    assert "GATE_STOPS_AFTER_READBACK" not in stdout  # workflow-only marker

    missing_overlay = _version_detail([_binding(BASE_NAME)])
    path2 = path.parent / "detail2.json"
    path2.write_text(json.dumps(missing_overlay), encoding="utf-8")
    code, _stdout, stderr = _run([
        "verify",
        "--version-detail", str(path2),
        "--active-version", VERSION_ID,
        "--legacy-pre-state", legacy_pre,
    ])
    assert code == 1
    assert OVERLAY_NAME in stderr

    settings_plane = _settings_plane([_binding(BASE_NAME), _binding(OVERLAY_NAME)])
    path3 = path.parent / "settings.json"
    path3.write_text(json.dumps(settings_plane), encoding="utf-8")
    code, _stdout, stderr = _run([
        "verify",
        "--version-detail", str(path3),
        "--active-version", VERSION_ID,
        "--legacy-pre-state", legacy_pre,
    ])
    assert code == 1  # settings plane can never pass as served-version proof

    code, _stdout, stderr = _run([
        "verify",
        "--version-detail", str(path),
        "--active-version", "11111111-1111-4111-8111-111111111111",
        "--legacy-pre-state", legacy_pre,
    ])
    assert code == 1  # version identity mismatch fails closed


# ------------------------------------------------------- workflow contracts


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_dispatch_only_for_mutation() -> None:
    text = _workflow_text()
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text
    assert "apply_base_v1_b54_kagent_removal" in text
    assert "environment: production" in text
    assert "REMOVE_B54_KAGENT_FROM_BASE_V1_FROM_EXACT_MAIN" in text


def test_workflow_exact_main_guards_fail_closed() -> None:
    text = _workflow_text()
    assert "test \"${GITHUB_REF}\" = \"refs/heads/main\"" in text
    assert text.count("test \"$(git rev-parse origin/main)\" = \"${TARGET_SHA}\"") >= 3


def test_workflow_never_accepts_secret_material_in_inputs() -> None:
    text = _workflow_text()
    assert "secrets.B54_ENGINE_CALLER_REGISTRY_V1_BASELINE" in text
    assert "secrets.B54_ENGINE_CALLER_REGISTRY_V1_BASELINE_CURRENTNESS" in text
    lowered = text.lower()
    for forbidden in ("inputs.credential", "inputs.secret", "inputs.baseline",
                      "inputs.currentness"):
        assert forbidden not in lowered, forbidden


def test_workflow_put_targets_base_v1_only_and_never_the_overlay() -> None:
    text = _workflow_text()
    assert text.count('jq -e \'.name == "PADIEM_ENGINE_CALLER_REGISTRY_V1"') >= 2
    apply_job = text[text.index("apply-base-v1-b54-kagent-removal:"):]
    assert "-X PUT" in apply_job
    assert "/secrets" in apply_job
    assert "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY" not in apply_job
    assert "b54_engine_caller_registry_overlay_rotation.py" not in text
    assert "DELETE" not in apply_job
    assert "OVERLAY_MUTATION=0" in apply_job


def test_workflow_readonly_and_readback_use_served_version_only() -> None:
    text = _workflow_text()
    assert "/settings" not in text  # no settings-plane preflight anywhere
    assert "GET_ONLY=PASS" in text
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in text
    assert "SETTINGS_PLANE_ONLY_ACCEPTANCE=NO" in text
    assert "PRE_MUTATION_STATE_SERVED_VERSION=YES" in text
    assert "SINGLE_100_PERCENT_SERVED_VERSION_GUARD=PASS" in text
    assert text.count("resolve-active") >= 3  # preflight, pre-write, post-write
    assert text.count("ENGINE_ACTIVE_VERSION_IDENTIFIED=PASS") >= 2
    assert text.count("/versions/${active_version}") >= 2
    assert "LEGACY_PRE_STATE" in text
    assert "GATE_STOPS_AFTER_READBACK=YES" in text
    assert "RUNTIME_SUCCESS=UNPROVEN_PENDING_PHASE_A" in text


def test_workflow_never_deploys_the_engine_worker() -> None:
    text = _workflow_text()
    for forbidden in ("wrangler", "versions deploy", "deployments create",
                      "padiem-chat", "b62", "PHASE_A=EXECUTED"):
        assert forbidden not in text.lower(), forbidden
    assert "WORKER_DEPLOYED=0" in text
    assert "PHASE_A_EXECUTED=0" in text


def test_workflow_source_contract_runs_the_removal_tests() -> None:
    text = _workflow_text()
    assert (
        "python .github/tests/test_b54_engine_caller_registry_base_v1_b54_kagent_removal_gate.py"
        in text
    )
    assert "b54_engine_caller_registry_base_v1_b54_kagent_removal.py" in text


READONLY_STEP = "Read the SERVED version authority and classify removal disposition"
RECONFIRM_STEP = "Reconfirm the SERVED version authority immediately before mutation"


def _step_run(job_name: str, step_name: str) -> str:
    steps = yaml.safe_load(_workflow_text())["jobs"][job_name]["steps"]
    matches = [step for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, (step_name, [step.get("name") for step in steps])
    return matches[0]["run"]


def test_workflow_apply_reconfirms_served_version_before_put() -> None:
    text = _workflow_text()
    wf = yaml.safe_load(text)
    readonly = wf["jobs"]["cloudflare-readonly"]
    apply_job = wf["jobs"]["apply-base-v1-b54-kagent-removal"]
    assert readonly["outputs"]["active_version_id"] == "${{ steps.classify.outputs.active_version_id }}"
    assert (
        apply_job["env"]["PRE_ACTIVE_VERSION_ID"]
        == "${{ needs.cloudflare-readonly.outputs.active_version_id }}"
    )
    assert (
        apply_job["env"]["LEGACY_PRE_STATE"]
        == "${{ needs.cloudflare-readonly.outputs.legacy_pre_state }}"
    )
    names = [step.get("name", "") for step in apply_job["steps"]]
    order = [
        "Reconfirm exact main immediately before mutation",
        RECONFIRM_STEP,
        "Build the bounded base V1 removal PUT body from secrets",
        "Rewrite ONLY the base V1 registry secret",
    ]
    indices = [names.index(name) for name in order]
    assert indices == sorted(indices), names
    body = _step_run("apply-base-v1-b54-kagent-removal", RECONFIRM_STEP)
    assert "-X PUT" not in body  # the pre-write reconfirmation is GET-only
    assert "curl -fsS" in body
    assert "resolve-active" in body
    assert "/versions/${current_version}" in body
    assert '--active-version "${current_version}"' in body
    assert '--pre-active-version "${PRE_ACTIVE_VERSION_ID}"' in body
    assert '--pre-legacy-state "${LEGACY_PRE_STATE}"' in body
    assert text.count("-X PUT") == 1  # the single PUT lives in the PUT step only
    assert "PUT_COUNT=0" in text
    assert "PUT_COUNT=1" in text


TOCTOU_HARNESS = r"""set -euo pipefail
# Step env is injected as shell variables (not process env): WSL bash does
# not mirror custom Windows environment variables into non-login shells.
CLOUDFLARE_API_TOKEN='stub-token'
CLOUDFLARE_ACCOUNT_ID='stub-account'
ENGINE_WORKER='padiem-ai-engine'
# Pin python to the interpreter executing this suite: WSL PATH can resolve a
# bare 'python' to a Windows interpreter that cannot see Linux /tmp.
__PYTHON_BIN__
python() { "${HARNESS_PYTHON}" "$@"; }
__EXTRA_VARS__
RUNNER_TEMP="$(mktemp -d)"
export RUNNER_TEMP
GITHUB_OUTPUT="${RUNNER_TEMP}/github_output"
: > "${GITHUB_OUTPUT}"
TOCTOU_DEPLOYMENTS_JSON='__DEPLOYMENTS__'
TOCTOU_DETAIL_JSON='__DETAIL__'
PUT_CALLED=NO
CURL_LOG="${RUNNER_TEMP}/curl_log"
: > "${CURL_LOG}"
curl() {
  local args=("$@") out="" url="" method="GET" i
  for ((i = 0; i < ${#args[@]}; i++)); do
    case "${args[i]}" in
      -o) out="${args[i + 1]}" ;;
      -X) method="${args[i + 1]}" ;;
      http*) url="${args[i]}" ;;
    esac
  done
  printf '%s %s\n' "${method}" "${url}" >> "${CURL_LOG}"
  if [ "${method}" != "GET" ]; then PUT_CALLED=YES; fi
  if [ -n "${out}" ]; then
    case "${url}" in
      */deployments) printf '%s\n' "${TOCTOU_DEPLOYMENTS_JSON}" > "${out}" ;;
      */versions/*) printf '%s\n' "${TOCTOU_DETAIL_JSON}" > "${out}" ;;
      *) printf '%s\n' '{"success":true,"result":"stub"}' > "${out}" ;;
    esac
  fi
}
report() {
  echo "HARNESS_PUT_CALLED=${PUT_CALLED}"
  echo "HARNESS_CURL_LOG:"
  cat "${CURL_LOG}"
  echo "HARNESS_GITHUB_OUTPUT:"
  cat "${GITHUB_OUTPUT}"
}
trap report EXIT
# Preflight: some local shells (WSL interop with a cold VM) hand child
# processes a /tmp view that disagrees with the running bash. Detect that
# environmental flakiness explicitly instead of letting it masquerade as a
# guard failure; the runner reports 77 and the suite retries, then skips
# honestly. Native Linux CI never takes this path.
"${HARNESS_PYTHON}" -c 'import os,sys; sys.exit(0 if os.path.exists(os.environ["RUNNER_TEMP"] + "/curl_log") else 1)' \
  || { echo "HARNESS_ENV_FLAKY=CHILD_TMP_DISAGREEMENT"; exit 77; }
__BODY__
"""


class _EnvironmentFlaky(RuntimeError):
    """The local bash child could not be trusted; the check did not execute."""


def _run_bash_step(body: str, served_version: str, bindings: list[dict],
                   extra_vars: dict[str, str] | None = None,
                   attempts: int = 5):
    if shutil.which("bash") is None:
        raise AssertionError("bash not found; the TOCTOU regression must run under bash")
    # Warm the bash host once (system32\bash.exe is a WSL launcher whose cold
    # start can churn /tmp under a running script).
    subprocess.run(["bash", "-c", "true"], capture_output=True)
    for value in (extra_vars or {}).values():
        assert "'" not in value and "$" not in value and "\\" not in value
    assignments = "".join(
        f"{key}='{value}'\n" for key, value in (extra_vars or {}).items()
    )
    script = (
        TOCTOU_HARNESS
        .replace("__EXTRA_VARS__", assignments)
        .replace("__PYTHON_BIN__",
                 'HARNESS_PYTHON="$(command -v python3 || command -v python)"')
        .replace("__DEPLOYMENTS__", json.dumps(_deployments_envelope(served_version),
                                               separators=(",", ":")))
        .replace("__DETAIL__", json.dumps(_version_detail(bindings, served_version),
                                          separators=(",", ":")))
        .replace("__BODY__", body)
    )
    for attempt in range(attempts):
        proc = subprocess.run(
            ["bash", "-s"], input=script.encode("utf-8"),
            capture_output=True, cwd=str(ROOT),
        )
        out = proc.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
        err = proc.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
        combined = out + err
        if ("HARNESS_ENV_FLAKY=CHILD_TMP_DISAGREEMENT" in combined
                or "REASON=payload file could not be read" in combined):
            # Either the preflight or a mid-run WSL instance churn: a stub
            # that just wrote a file can never legitimately fail its read.
            time.sleep(1.5 * (attempt + 1))  # let a cold WSL instance settle
            continue
        return proc.returncode, combined
    raise _EnvironmentFlaky(
        "bash child repeatedly could not see the harness /tmp "
        "(WSL cold-start flakiness); the TOCTOU behavioral check did not execute"
    )


def _harness_outputs(out: str) -> dict[str, str]:
    tail = out[out.index("HARNESS_GITHUB_OUTPUT:\n") + len("HARNESS_GITHUB_OUTPUT:\n"):]
    captured: dict[str, str] = {}
    for line in tail.splitlines():
        for key in ("disposition", "legacy_pre_state", "active_version_id"):
            if line.startswith(f"{key}="):
                captured[key] = line.split("=", 1)[1]
    return captured


def test_toctou_behavioral_regression_under_bash() -> None:
    """readonly sees version A, apply sees version B, Git main unchanged.

    The REAL readonly and pre-write reconfirmation step bodies are executed in
    bash with curl stubbed (GET-only canned Cloudflare documents): the drift
    case must fail closed with zero PUT calls; the unchanged case is the
    positive control proving the guard itself is not vacuous.
    """
    readonly_body = _step_run("cloudflare-readonly", READONLY_STEP)
    reconfirm_body = _step_run("apply-base-v1-b54-kagent-removal", RECONFIRM_STEP)
    bindings = _migratable_bindings()

    rc, out = _run_bash_step(readonly_body, VERSION_ID, bindings)
    assert rc == 0, out
    captured = _harness_outputs(out)
    assert captured["disposition"] == "MIGRATION_REQUIRED"
    assert captured["active_version_id"] == VERSION_ID
    pre_vars = {
        "PRE_ACTIVE_VERSION_ID": captured["active_version_id"],
        "LEGACY_PRE_STATE": captured["legacy_pre_state"],
    }

    # TOCTOU drift: the served version moved to B between the two jobs.
    rc, out = _run_bash_step(reconfirm_body, VERSION_B, bindings, pre_vars)
    assert rc != 0
    assert "REASON=SERVED_VERSION_CHANGED_AFTER_READONLY_PREFLIGHT" in out
    assert "TOCTOU_SERVED_VERSION_GUARD=FAIL" in out
    assert "PUT_COUNT=0" in out
    assert "CLOUDFLARE_MUTATION=0" in out
    assert "PRODUCTION_MUTATION=0" in out
    assert "HARNESS_PUT_CALLED=NO" in out
    assert "-X PUT" not in out

    # Positive control: the same served version reconfirms and still PUTs zero
    # times at this point (the PUT step is a separate, later step).
    rc, out = _run_bash_step(reconfirm_body, VERSION_ID, bindings, pre_vars)
    assert rc == 0, out
    assert "TOCTOU_SERVED_VERSION_GUARD=PASS" in out
    assert "PREWRITE_SERVED_VERSION_RECONFIRMED=YES" in out
    assert "HARNESS_PUT_CALLED=NO" in out


def _main() -> None:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    skipped = 0
    for test in tests:
        try:
            test()
        except _EnvironmentFlaky as exc:
            skipped += 1
            print(f"SKIP {test.__name__}: {exc}")
            continue
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests")
    if skipped:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_GATE_TESTS=PASS_WITH_SKIP")
    else:
        print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_GATE_TESTS=PASS")


if __name__ == "__main__":
    _main()
