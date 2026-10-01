"""Static contracts for the owner-gated A7 authenticated USER canary."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-a7-authenticated-user-canary.yml"
SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a7_authenticated_user_production_canary.py"
CP_WORKER = ROOT / "packages" / "padiem-control-plane" / "engine_admission_authority_worker.py"
PRODUCER = ROOT / "packages" / "padiem-control-plane" / "padiem_control_plane" / "engine_entitlement_producer.py"
ENGINE_SERVICE = ROOT / "apps" / "padiem-ai-engine" / "app" / "execution_admission_service.py"


def _workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    trigger = data.get("on", data.get(True))
    return {"trigger": trigger, "jobs": data["jobs"]}


def _live_job() -> dict:
    return _workflow()["jobs"]["live-authenticated-user-canary"]


def _live_runs() -> str:
    return "\n".join(str(step.get("run", "")) for step in _live_job()["steps"])


def test_canary_source_uses_canonical_primary_and_protected_subject_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "from padiem_ai_core.model_primary import TEXT_PRIMARY_MODEL_ID" in source
    assert '"subject_id": subject_id' in source
    assert '"max_tokens": 8' in source
    assert "PADIEM_A7_CANARY_SUBJECT_ID" in source
    assert "REAL_PROVIDER_CALL_MAX=1" in source
    assert "RAW_SUBJECT_OUTPUT=0" in source
    assert "print(CANARY_SUBJECT_ID" not in source
    assert "CUSTOM_PAYLOAD_JSON" not in source
    assert not re.search(r"(space-bunny|sensenova|openai|anthropic)", source, re.I)


def test_cp_worker_auto_ensures_entitlement_from_identity_without_engine_install() -> None:
    worker = CP_WORKER.read_text(encoding="utf-8")
    producer = PRODUCER.read_text(encoding="utf-8")
    assert "ensure_authenticated_user_engine_entitlement" in worker
    assert "await self._ensure_current_entitlement(" in worker
    assert "async def fetch_entitlement_snapshot" in worker
    assert "async def reserve_usage" in worker
    assert "ENGINE_GATEWAY_CAN_INSTALL_ENTITLEMENTS = False" in worker
    assert "CONTROL_PLANE_IDENTITY_REQUIRED_FOR_ENTITLEMENT = True" in worker
    assert "resolve_current_auth_session" in producer
    assert "SubjectType.USER" in producer
    assert 'ENGINE_ORCHESTRATION_GRANT = "orchestration.run"' in producer


def test_engine_success_path_is_fail_closed_on_terminal_usage_receipt() -> None:
    source = ENGINE_SERVICE.read_text(encoding="utf-8")
    assert "await self._record_terminal_usage(" in source
    assert 'outcome="succeeded"' in source
    assert "return self._receipt_error(exc)" in source
    assert "record_usage_receipt" in source


def test_workflow_pr_path_is_source_only_and_live_mode_is_explicit() -> None:
    wf = _workflow()
    assert "pull_request" in wf["trigger"]
    assert "workflow_dispatch" in wf["trigger"]
    job = _live_job()
    assert job["environment"] == "production"
    assert "live_authenticated_user_canary" in str(job["if"])
    assert "RUN_A7_AUTHENTICATED_USER_CANARY_FROM_EXACT_MAIN" in str(job["if"])


def test_live_job_requires_exact_main_and_exact_served_version() -> None:
    runs = _live_runs()
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in runs
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in runs
    assert "EXPECTED_SERVED_VERSION_UNSAFE" in runs
    assert "resolve-active" in runs
    assert "SERVED_VERSION_MISMATCH" in runs
    assert "--inspect-engine-admission-binding" in runs
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING=PRESENT:service" in runs
    assert "ENGINE_ADMISSION_BINDING_TARGET_VALIDATED=YES" in runs


def test_subject_and_caller_secrets_are_consumed_but_never_echoed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    runs = _live_runs()
    env = _live_job()["env"]
    assert env["PADIEM_A7_CANARY_SUBJECT_ID"] == "${{ secrets.PADIEM_A7_CANARY_SUBJECT_ID }}"
    assert env["CALLER_SECRET"] == "${{ secrets.B62_P01_ENGINE_CREDENTIAL }}"
    assert "add-mask::${PADIEM_A7_CANARY_SUBJECT_ID}" in runs
    assert "echo \"${PADIEM_A7_CANARY_SUBJECT_ID}" not in runs
    assert "secrets." not in runs
    assert "PADIEM_A7_CANARY_SUBJECT_ID" in text


def test_live_gate_records_bounded_mutation_surface_and_never_flips_manifest() -> None:
    runs = _live_runs()
    assert "LIVE_PROVIDER_CALL_MAX=1" in runs
    assert "CP_USAGE_MUTATION=BOUNDED" in runs
    assert "ENGINE_IDEMPOTENCY_MUTATION=BOUNDED" in runs
    assert "MANIFEST_FLIP=0" in runs
    for forbidden in (
        "pywrangler deploy",
        "wrangler deploy",
        "wrangler secret",
        "secret put",
        "d1 migrations",
        "install_entitlement_snapshot",
    ):
        assert forbidden not in runs
