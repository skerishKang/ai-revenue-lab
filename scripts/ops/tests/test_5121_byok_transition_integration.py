from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRANSITION_PATH = ROOT / "scripts" / "ops" / "byok_key_transition.py"
READINESS_PATH = ROOT / "apps" / "padiem-chat" / "scripts" / "byok_predeploy_readiness.py"
RUNBOOK = ROOT / "docs" / "operations" / "BYOK_KEY_TRANSITION_RUNBOOK_20261019.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


transition = _load("byok_key_transition_integration_ops", TRANSITION_PATH)
readiness = _load("byok_predeploy_readiness_integration", READINESS_PATH)


def _state(**overrides):
    state = {
        "deployed_byok_route": "PRESENT",
        "d1_migration_053": "APPLIED",
        "dpapi_custom_key_secret": "PRESENT",
        "worker_custom_key_secret": "PRESENT",
    }
    state.update(overrides)
    return state


def test_transition_and_readiness_share_the_key_contract():
    assert transition.SECRET_NAME == readiness.SECRET_NAME
    assert transition.MIN_SECRET_CHARS == readiness.MIN_SECRET_CHARS
    assert transition.MIGRATION_RELATIVE.is_file()

    migration = (ROOT / transition.MIGRATION_RELATIVE).read_text(encoding="utf-8")
    assert f"CREATE TABLE IF NOT EXISTS {readiness.TABLE}" in migration
    assert "PRIMARY KEY (user_id, provider_id)" in migration
    assert readiness.TABLE in TRANSITION_PATH.read_text(encoding="utf-8")


def test_next_action_follows_the_documented_deploy_order():
    assert (
        transition._next_action(_state(deployed_byok_route="ABSENT"))
        == "deploy_exact_main_to_worker_and_refresh_local_release"
    )
    assert (
        transition._next_action(_state(d1_migration_053="MISSING"))
        == "apply-migration"
    )
    assert (
        transition._next_action(_state(dpapi_custom_key_secret="MISSING"))
        == "register-local"
    )
    assert (
        transition._next_action(_state(worker_custom_key_secret="MISSING"))
        == "upload-worker"
    )
    assert transition._next_action(_state()) == "owner_bounded_byok_verify"

    route_gap = _state(
        deployed_byok_route="ABSENT",
        d1_migration_053="MISSING",
        dpapi_custom_key_secret="MISSING",
        worker_custom_key_secret="MISSING",
    )
    assert transition._next_action(route_gap) == (
        "deploy_exact_main_to_worker_and_refresh_local_release"
    )


def test_plan_reports_steps_in_execution_order(capsys):
    transition.print_plan(
        {
            **_state(),
            "ready": True,
            "custom_credential_rows": 0,
        }
    )
    output = capsys.readouterr().out
    markers = [
        "STEP_1_DEPLOY_EXACT_MAIN_BYOK_CODE=DONE",
        "STEP_2_APPLY_MIGRATION_053=DONE",
        "STEP_3_REGISTER_COM2_DPAPI_SECRET=DONE",
        "STEP_4_UPLOAD_WORKER_SECRET=DONE",
        "STEP_5_PREFLIGHT_REQUIRE_READY=DONE",
        "STEP_6_OWNER_BOUNDED_BYOK_VERIFY=PENDING",
        "STEP_7_LEGACY_RESEAL_HASH_CHECK=NOT_APPLICABLE",
        "NEXT=owner_bounded_byok_verify",
    ]
    positions = [output.index(marker) for marker in markers]
    assert positions == sorted(positions)


def test_runbook_wires_both_tools_and_distinct_failure_states():
    text = RUNBOOK.read_text(encoding="utf-8")

    for command in (
        "scripts/ops/byok_key_transition.py preflight",
        "byok_predeploy_readiness.py check-d1",
        "byok_predeploy_readiness.py check ",
        "--require-ready",
        "--inspect-local-key",
    ):
        assert command in text

    for signal in (
        "DEPLOYED_BYOK_ROUTE=ABSENT",
        "DEPLOYED_BYOK_ROUTE=UNKNOWN",
        "SECRET_READY=NO",
        "SECRET_MISSING",
        "MIGRATION_053_MISSING",
        "MIGRATION_053_DRIFT",
        "BYOK_PREDEPLOY_STATE=READY",
        "custom_provider_unavailable",
        "custom_credential_save_failed",
        "custom_credential_unavailable",
        "custom_credential_required",
    ):
        assert signal in text

    steps = [f"### Step {index} " for index in range(7)]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
