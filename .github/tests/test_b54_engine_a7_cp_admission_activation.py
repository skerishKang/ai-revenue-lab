from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "b54-engine-a7-cp-admission-production-activation.yml"
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    data = yaml.safe_load(_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_activation_is_dispatch_only_for_mutation_and_pull_request_is_source_only() -> None:
    wf = _workflow()
    assert "pull_request" in wf["triggers"]
    assert "workflow_dispatch" in wf["triggers"]
    text = _text()
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "activate_cp_engine_admission_worker" in text
    assert "ACTIVATE_PADIEM_CONTROL_PLANE_ENGINE_ADMISSION_FROM_EXACT_MAIN" in text
    assert "environment: production" in text


def test_source_contract_dry_runs_exact_private_worker() -> None:
    text = _text()
    assert "wrangler.engine-admission-authority.jsonc" in text
    assert "pywrangler deploy" in text
    assert "--dry-run" in text
    assert "A7_CP_ADMISSION_PACKAGE_DRY_RUN=PASS" in text
    assert "PRODUCTION_MUTATION=0" in text


def test_first_activation_requires_engine_to_stay_detached() -> None:
    text = _text()
    assert 'test "${ENGINE_BINDING_STATE}" = "ABSENT"' in text
    assert "ENGINE_REMAINS_DETACHED_DURING_CP_ACTIVATION=YES" in text
    assert "ENGINE_BINDING_MUTATION=0" in text
    assert "ENGINE_MUTATION=0" in text


def test_readonly_classifies_absent_or_private_present_without_secret_values() -> None:
    text = _text()
    assert "CP_ENGINE_ADMISSION_WORKER=ABSENT" in text
    assert "CP_ENGINE_ADMISSION_WORKER=PRESENT" in text
    assert "CONTROL_PLANE_ENGINE_ADMISSION_SERVED_BINDING" in text
    assert "--inspect-engine-admission-binding" in text
    assert "SECRET_VALUES_READ=0" in text
    assert "REAL_USER_DATA=0" in text


def test_activation_mutates_only_cp_admission_worker_and_has_no_provider_or_manifest_action() -> None:
    text = _text()
    activation = text.split("activate-cp-engine-admission-worker:", 1)[1]
    assert "packages/padiem-control-plane" in activation
    assert "CP_ENGINE_ADMISSION_DEPLOY=SUCCESS" in activation
    for forbidden in (
        "apps/padiem-ai-engine",
        "wrangler rollback",
        "d1 migrations apply",
        "MANIFEST_E7=AVAILABLE",
        "/internal/v1/orchestrate",
        "PADIEM_KILO_API_KEY",
    ):
        assert forbidden not in activation


def test_post_readback_requires_private_ingress_identity_binding_and_single_served_version() -> None:
    text = _text()
    assert '.result.enabled == false and .result.previews_enabled == false' in text
    assert '"CONTROL_PLANE_IDENTITY"' in text
    assert '"padiem-control-plane-identity"' in text
    assert ".result.deployments[0].versions[0].percentage == 100" in text
    assert "ROLLBACK_POSTURE=ENGINE_STILL_DETACHED_CP_WORKER_MAY_REMAIN_INERT" in text
