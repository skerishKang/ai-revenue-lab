"""#5015: the live-config activation path for the Chat orchestration variable.

Network-free contract tests. They never read a secret value, never touch the
Cloudflare API, and never activate anything: they prove the plan, the
readback, the targeted rollback and the workflow wiring only.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-claw-live-config-activation-gate.yml"
HELPER = ROOT / ".github/scripts/b62_claw_live_config_activation.py"
CHAT_WRANGLER = ROOT / "apps/padiem-chat/wrangler.toml"
CHAT_BRIDGE = ROOT / "apps/padiem-chat/app/worker_orchestration.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_claw_live_config_activation", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding(name: str, kind: str, **extra):
    return {"name": name, "type": kind, **extra}


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def _live_bindings(*, orchestration=None):
    bindings = [
        _binding("ASSETS", "assets"),
        _binding("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
        _binding("PADIEM_CHAT_RUNTIME_MODE", "plain_text", text="b14"),
        _binding("PADIEM_CHAT_LIVE_ENABLED", "plain_text", text="true"),
        _binding("P01_ENGINE_SERVICE", "service", service="padiem-ai-engine"),
        _binding("P01_ENGINE_CALLER_ID", "plain_text", text="caller"),
        _binding("P01_ENGINE_CREDENTIAL", "secret_text"),
        _binding("ORACLE_MESH_CHANNEL_SECRET", "secret_text", value="do-not-print"),
    ]
    if orchestration is not None:
        bindings.append(_binding("PADIEM_CHAT_ORCHESTRATION_ENABLED", "plain_text", text=orchestration))
    return bindings


def test_state_reports_only_the_bounded_activation_states() -> None:
    helper = _load_helper()
    assert helper.chat_orchestration_state(_settings(_live_bindings())) == "absent"
    assert helper.chat_orchestration_state(
        _settings(_live_bindings(orchestration="true"))
    ) == "enabled"
    assert helper.chat_orchestration_state(
        _settings(_live_bindings(orchestration="false"))
    ) == "unexpected_value"
    retyped = _live_bindings()
    retyped.append(_binding("PADIEM_CHAT_ORCHESTRATION_ENABLED", "secret_text"))
    assert helper.chat_orchestration_state(_settings(retyped)) == "wrong_type"


def test_plan_sets_only_the_one_variable_and_inherits_every_other_binding() -> None:
    helper = _load_helper()
    live = _live_bindings()
    plan = helper.build_chat_orchestration_patch(
        _settings(live), target_sha="a" * 40
    )
    assert plan["no_op"] is False
    assert plan["state"] == "absent"
    assert plan["changes"] == ["CHAT_ORCHESTRATION_ENABLED_SET_TRUE"]
    patch = plan["payload"]
    assert len(patch["bindings"]) == len(live) + 1
    assert sum(1 for b in patch["bindings"] if b["type"] == "inherit") == len(live)
    added = [b for b in patch["bindings"] if b["type"] != "inherit"]
    assert added == [
        {"name": "PADIEM_CHAT_ORCHESTRATION_ENABLED", "type": "plain_text", "text": "true"}
    ]
    assert "do-not-print" not in repr(plan)
    assert patch["annotations"]["workers/message"].endswith("a" * 40)


def test_plan_is_idempotent_when_the_variable_is_already_enabled() -> None:
    helper = _load_helper()
    plan = helper.build_chat_orchestration_patch(
        _settings(_live_bindings(orchestration="true")), target_sha="b" * 40
    )
    assert plan["no_op"] is True
    assert plan["state"] == "enabled"
    assert plan["changes"] == []


def test_plan_refuses_to_overwrite_a_retyped_or_unexpected_value() -> None:
    helper = _load_helper()
    for state, bindings in (
        ("unexpected_value", _live_bindings(orchestration="false")),
        ("wrong_type", _live_bindings() + [
            _binding("PADIEM_CHAT_ORCHESTRATION_ENABLED", "secret_text")
        ]),
    ):
        try:
            helper.build_chat_orchestration_patch(
                _settings(bindings), target_sha="c" * 40
            )
        except helper.ActivationPlanError as exc:
            assert state in str(exc)
        else:
            raise AssertionError(f"expected refusal for {state}")


def test_verify_accepts_exactly_one_changed_name_and_refuses_drift() -> None:
    helper = _load_helper()
    before = _live_bindings()
    after = _live_bindings(orchestration="true")
    helper.verify_chat_orchestration(
        _settings(after), pre_payload=_settings(before)
    )
    with_helper = _load_helper()
    # An unrelated addition, removal or value drift fails closed.
    unrelated = after + [_binding("OTHER_LIVE_VAR", "plain_text", text="x")]
    try:
        with_helper.verify_chat_orchestration(
            _settings(unrelated), pre_payload=_settings(before)
        )
    except with_helper.ActivationPlanError:
        pass
    else:
        raise AssertionError("expected refusal for an unrelated live addition")
    removed = [b for b in after if b["name"] != "PADIEM_CHAT_RUNTIME_MODE"]
    try:
        with_helper.verify_chat_orchestration(
            _settings(removed), pre_payload=_settings(before)
        )
    except with_helper.ActivationPlanError:
        pass
    else:
        raise AssertionError("expected refusal for an unrelated live removal")
    try:
        with_helper.verify_chat_orchestration(_settings(before))
    except with_helper.ActivationPlanError:
        pass
    else:
        raise AssertionError("expected refusal when the variable is not enabled")


def test_targeted_rollback_removes_only_the_orchestration_variable() -> None:
    helper = _load_helper()
    snapshot = _settings(_live_bindings())
    current = _settings(_live_bindings(orchestration="true"))
    admitted = helper.build_rollback_plan(
        snapshot, current,
        credential_created_by_activation=False, target_sha="d" * 40,
        chat_orchestration_rollback=True,
    )
    assert "CONFIG_REMOVE_PADIEM_CHAT_ORCHESTRATION_ENABLED" in admitted["changes"]
    assert not any(
        b["name"] == "PADIEM_CHAT_ORCHESTRATION_ENABLED"
        for b in admitted["payload"]["bindings"]
    )
    kept = helper.build_rollback_plan(
        snapshot, current,
        credential_created_by_activation=False, target_sha="d" * 40,
    )
    assert "CONFIG_REMOVE_PADIEM_CHAT_ORCHESTRATION_ENABLED" not in kept["changes"]
    assert any(
        b["name"] == "PADIEM_CHAT_ORCHESTRATION_ENABLED"
        and b["type"] == "inherit"
        for b in kept["payload"]["bindings"]
    )


def test_latest_served_guard_accepts_the_exact_latest_version():
    helper = _load_helper()
    version_id = "3f2b1c40-1111-2222-3333-444455556666"
    deployments = {
        "success": True,
        "result": {"deployments": [{
            "id": "current",
            "versions": [{"version_id": version_id, "percentage": 100}],
        }]},
    }
    versions = {"success": True, "result": {"items": [{"id": version_id}]}}
    assert helper.verify_latest_served_version(
        deployments=deployments, versions_payload=versions
    ) == version_id


def test_latest_served_guard_refuses_when_the_active_version_is_not_the_latest():
    helper = _load_helper()
    deployments = {
        "success": True,
        "result": {"deployments": [{
            "id": "current",
            "versions": [{"version_id": "aaaa-1111", "percentage": 100}],
        }]},
    }
    versions = {"success": True, "result": {"items": [{"id": "bbbb-2222"}]}}
    try:
        helper.verify_latest_served_version(
            deployments=deployments, versions_payload=versions
        )
    except helper.ActivationPlanError as exc:
        assert "not the latest" in str(exc)
    else:
        raise AssertionError("expected refusal when the served version is not the latest")


def test_latest_served_guard_refuses_when_the_active_version_cannot_be_resolved():
    helper = _load_helper()
    versions = {"success": True, "result": {"items": [{"id": "aaaa-1111"}]}}
    for deployments in (
        {"success": False},
        {"success": True, "result": {"deployments": []}},
        {"success": True, "result": {"deployments": [{
            "id": "current",
            "versions": [{"version_id": "aaaa-1111", "percentage": 50}],
        }]}},
        {"success": True, "result": {"deployments": [{
            "id": "current", "versions": [],
        }]}},
    ):
        try:
            helper.verify_latest_served_version(
                deployments=deployments, versions_payload=versions
            )
        except helper.ActivationPlanError as exc:
            assert "served version could not be resolved" in str(exc)
        else:
            raise AssertionError("expected refusal for an unresolvable served version")


def test_latest_served_guard_refuses_when_the_latest_id_is_missing_or_unusable():
    helper = _load_helper()
    deployments = {
        "success": True,
        "result": {"deployments": [{
            "id": "current",
            "versions": [{"version_id": "aaaa-1111", "percentage": 100}],
        }]},
    }
    for versions in (
        {"success": False},
        {"success": True, "result": {"items": []}},
        {"success": True, "result": {"items": [{}]}},
        {"success": True, "result": {"items": [{"id": ""}]}},
        {"success": True, "result": {"items": [{"id": "bad id with spaces"}]}},
    ):
        try:
            helper.verify_latest_served_version(
                deployments=deployments, versions_payload=versions
            )
        except helper.ActivationPlanError as exc:
            assert "latest Worker version id" in str(exc)
        else:
            raise AssertionError("expected refusal for an unusable latest version id")


def test_the_latest_served_guard_runs_before_the_patch_and_aborts_it():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = text.split("  activate-chat-orchestration:", 1)[1]
    guard = job.index("Refuse the PATCH unless the live active version is the latest version")
    patch = job.index("Apply the one-variable Chat orchestration patch through the settings API")
    assert guard < patch
    guard_block = job[guard:patch]
    assert "verify-latest-served" in guard_block
    # A refused comparison aborts the job before the PATCH runs.
    assert "CHAT_ORCHESTRATION_PATCH_BLOCKED_LATEST_NOT_SERVED=YES" in guard_block
    assert "CHAT_ORCHESTRATION_PATCH=NOT_APPLIED" in guard_block
    assert "exit 1" in guard_block
    assert "PRODUCTION_MUTATION=0" in guard_block
    # The guard reads the live deployment and version state itself.
    assert "/deployments" in guard_block
    assert "/versions?page=1&per_page=1" in guard_block


def test_workflow_exposes_the_reviewed_activation_and_rollback_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "activate_chat_orchestration" in text
    assert "chat_orchestration_rollback" in text
    assert "CONFIRM_ACTIVATE_B62_CHAT_ORCHESTRATION" in text
    assert "plan-chat-orchestration" in text
    assert "verify-chat-orchestration" in text
    assert "--chat-orchestration-rollback" in text
    # The activation is a settings PATCH, never a Worker code redeploy.
    assert text.count("  activate-chat-orchestration:") == 1
    job = text.split("  activate-chat-orchestration:", 1)[1]
    assert "CHAT_ORCHESTRATION_POST_READBACK=PASS" in job
    assert "CHAT_ORCHESTRATION_LIVE=true" in job
    assert "WORKER_CODE_REDEPLOY=0" in job
    assert "SECRET_VALUES_READ=0" in job
    assert "pywrangler" not in job
    assert "wrangler deploy" not in job
    # The rollback stays on the existing CONFIG_ROLLBACK job.
    rollback = text.split("  rollback-config:", 1)[1]
    assert "--chat-orchestration-rollback" in rollback


def test_the_variable_stays_a_live_settings_authority_not_a_source_declaration() -> None:
    # The source contract forbids declaring it in the Chat wrangler.toml, so the
    # live-config path stays the only activation authority.
    assert "PADIEM_CHAT_ORCHESTRATION_ENABLED" not in CHAT_WRANGLER.read_text(
        encoding="utf-8"
    )
    bridge = CHAT_BRIDGE.read_text(encoding="utf-8")
    assert "PADIEM_CHAT_ORCHESTRATION_ENABLED" in bridge
    assert re.search(
        r"ORCHESTRATION_ENABLED_ENV\s*=\s*\"PADIEM_CHAT_ORCHESTRATION_ENABLED\"", bridge
    )


if __name__ == "__main__":
    test_state_reports_only_the_bounded_activation_states()
    test_plan_sets_only_the_one_variable_and_inherits_every_other_binding()
    test_plan_is_idempotent_when_the_variable_is_already_enabled()
    test_plan_refuses_to_overwrite_a_retyped_or_unexpected_value()
    test_verify_accepts_exactly_one_changed_name_and_refuses_drift()
    test_targeted_rollback_removes_only_the_orchestration_variable()
    test_latest_served_guard_accepts_the_exact_latest_version()
    test_latest_served_guard_refuses_when_the_active_version_is_not_the_latest()
    test_latest_served_guard_refuses_when_the_active_version_cannot_be_resolved()
    test_latest_served_guard_refuses_when_the_latest_id_is_missing_or_unusable()
    test_the_latest_served_guard_runs_before_the_patch_and_aborts_it()
    test_workflow_exposes_the_reviewed_activation_and_rollback_paths()
    test_the_variable_stays_a_live_settings_authority_not_a_source_declaration()
    print("B62_CHAT_ORCHESTRATION_ACTIVATION_TESTS=PASS")
