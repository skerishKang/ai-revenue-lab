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
evidence, the served-version readback, and the workflow's dispatch-only,
exact-main, overlay-untouchable structure.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b54_engine_caller_registry_base_v1_b54_kagent_removal.py"
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-registry-base-v1-b54-kagent-removal-gate.yml"
PROVISION = ROOT / ".github/scripts/b54_engine_caller_registry_v1_provision.py"
ROTATION = ROOT / ".github/scripts/b54_engine_caller_registry_overlay_rotation.py"
IDENTITY = ROOT / "apps/padiem-ai-engine/app/identity_enforcement.py"

VERSION_ID = "30fb2308-f5d3-4365-a8fd-9c4c307e7535"
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
    settings = _settings_plane([
        _binding(BASE_NAME),
        _binding(OVERLAY_NAME),
        _binding(LEGACY_NAMES[0], "plain_text"),
    ])
    path = Path(tempfile.mkdtemp(prefix="b54-removal-classify-")) / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    code, stdout, stderr = _run(["classify", "--settings", str(path)])
    assert code == 0, stdout + stderr
    assert "B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_DISPOSITION=MIGRATION_REQUIRED" in stdout
    assert f"AUTHORITY_STATE {BASE_NAME}=PRESENT:secret_text" in stdout
    assert f"AUTHORITY_STATE {OVERLAY_NAME}=PRESENT:secret_text" in stdout
    assert "LEGACY_TRIO_PRE_STATE=" in stdout
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in stdout
    assert "{" not in stdout


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


def test_workflow_readonly_and_readback_use_name_type_only() -> None:
    text = _workflow_text()
    assert "GET_ONLY=PASS" in text
    assert "BINDING_NAME_AND_TYPE_ONLY=YES" in text
    assert "resolve-active" in text
    assert "/versions/${active_version}" in text
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


def _main() -> None:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests")
    print("B54_ENGINE_BASE_V1_B54_KAGENT_REMOVAL_GATE_TESTS=PASS")


if __name__ == "__main__":
    _main()
