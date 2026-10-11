from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / ".github/scripts/b62_automation_scheduler_config.py"
_spec = importlib.util.spec_from_file_location("b62_automation_scheduler_config", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = module
_spec.loader.exec_module(module)


def snapshot(value: str = "false", triggers=()):
    return module.SchedulerConfigSnapshot(
        variables={module.SCHEDULER_VAR: value, "PADIEM_CHAT_RUNTIME_MODE": "production"},
        triggers=tuple(triggers),
    )


def test_inert_and_active_states_are_explicit() -> None:
    assert module.classify(snapshot()) == "inert"
    assert module.classify(
        module.SchedulerConfigSnapshot(variables={}, triggers=())
    ) == "missing"
    assert module.classify(snapshot("true", (module.EXPECTED_CRON,))) == "active"
    assert module.classify(snapshot("true", ("0 * * * *",))) == "drift"
    assert module.classify(snapshot("false", ("0 * * * *",))) == "drift"


def test_activation_and_rollback_are_bounded_and_preserve_unknown_vars() -> None:
    before = snapshot()
    plan = module.build_activation_plan(before, target_sha="a" * 40)
    assert plan["changes"] == ["SCHEDULER_VAR_SET", "CRON_DECLARATION_ADD"]
    assert plan["no_op"] is False
    assert plan["secret_values_read"] == 0
    after = module.SchedulerConfigSnapshot(
        variables={**before.variables, module.SCHEDULER_VAR: "true"},
        triggers=(module.EXPECTED_CRON,),
    )
    rollback = module.build_rollback_plan(before, after, target_sha="a" * 40)
    assert rollback["changes"] == ["SCHEDULER_VAR_SET", "CRON_DECLARATION_REMOVE"]
    assert rollback["after"]["triggers"] == []


def test_invalid_targets_and_drift_refuse() -> None:
    with pytest.raises(module.SchedulerConfigError):
        module.build_activation_plan(snapshot(), target_sha="not-a-sha")
    with pytest.raises(module.SchedulerConfigError):
        module.build_activation_plan(snapshot("true", ("0 * * * *",)), target_sha="a" * 40)
    with pytest.raises(module.SchedulerConfigError):
        module.build_rollback_plan(snapshot(), snapshot(), target_sha="a" * 40)
    with pytest.raises(module.SchedulerConfigError):
        module.build_activation_plan(
            module.SchedulerConfigSnapshot(variables={}, triggers=()),
            target_sha="a" * 40,
        )


def test_parse_snapshot_rejects_coercion() -> None:
    with pytest.raises(module.SchedulerConfigError):
        module.parse_snapshot({"variables": {module.SCHEDULER_VAR: 1}, "triggers": []})
    with pytest.raises(module.SchedulerConfigError):
        module.parse_snapshot({"variables": {}, "triggers": [1]})


def test_rendered_config_contains_only_scheduler_shape() -> None:
    rendered = module.render_config(
        module.SchedulerConfigSnapshot(
            variables={
                module.SCHEDULER_VAR: "true",
                "PADIEM_CHAT_RUNTIME_MODE": "production",
                "UNRELATED_SENSITIVE_VALUE": "must-not-render",
            },
            triggers=(module.EXPECTED_CRON,),
        )
    )
    assert "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED = 'true'" in rendered
    assert "[triggers]" in rendered
    assert "UNRELATED_SENSITIVE_VALUE" not in rendered
    assert "must-not-render" not in rendered


def test_repository_scheduler_source_stays_inert() -> None:
    config = tomllib.loads(
        (ROOT / "apps/padiem-chat/wrangler.toml").read_text(encoding="utf-8")
    )
    assert "triggers" not in config
    assert config["vars"]["PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED"] == "false"
    inert = module.parse_snapshot(
        {"variables": {module.SCHEDULER_VAR: "false"}, "triggers": []}
    )
    assert module.classify(inert) == "inert"
    plan = module.build_activation_plan(inert, target_sha="b" * 40)
    assert plan["after"]["triggers"] == [module.EXPECTED_CRON]
    assert plan["after"]["scheduler_var"] == "true"


def test_scheduler_workflow_is_source_or_plan_only() -> None:
    workflow = (ROOT / ".github/workflows/b62-automation-scheduler-config-gate.yml").read_text(encoding="utf-8")
    assert "PRODUCTION_CRON_ACTIVATION=0" in workflow
    assert "PRODUCTION_DEPLOY=0" in workflow
    assert "CONFIG_MUTATION=0" in workflow
    assert "apply_migration" not in workflow
    assert "deploy_production" not in workflow

def test_pr_workflows_pin_exact_head_without_persisted_credentials() -> None:
    for relative in (
        ".github/workflows/b62-automation-scheduler-config-gate.yml",
        ".github/workflows/b62-automation-canary-gate.yml",
    ):
        workflow = (ROOT / relative).read_text(encoding="utf-8")
        assert "github.event.pull_request.head.sha" in workflow
        assert "fetch-depth: 1" in workflow
        assert "persist-credentials: false" in workflow
