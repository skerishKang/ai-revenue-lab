from __future__ import annotations

from pathlib import Path

import pytest
from app.claw_automation_canary import AutomationCanaryPlan, CanaryContractError

TENANT = "tenant_0123456789abcdef0123456789abcdef"
SUBJECT = "sub_0123456789abcdef0123456789abcdef"


def plan(**overrides) -> AutomationCanaryPlan:
    values = {
        "workspace_id": TENANT,
        "rule_id": "canary_rule",
        "canonical_subject_id": SUBJECT,
        "schedule_kind": "interval",
        "schedule_expression": "1h",
        "timezone": "UTC",
        "target_source": "memory",
        "output_type": "report",
    }
    values.update(overrides)
    return AutomationCanaryPlan(**values)


def test_canary_plan_is_bounded_and_source_only() -> None:
    value = plan().safe_dict()
    assert value["canary_ready"] is True
    assert value["max_occurrences"] == 1
    assert value["max_runs"] == 1
    assert value["max_task_alert_outputs"] == 1
    assert value["external_write"] is False
    assert value["external_send"] is False
    assert value["live_probe"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"workspace_id": "owner:usr_legacy"},
        {"canonical_subject_id": "subject:legacy"},
        {"rule_id": "bad rule id"},
        {"timezone": ""},
        {"schedule_expression": "not-an-interval"},
        {"target_source": "connectors"},
        {"max_runs": 2},
        {"external_write": True},
        {"external_send": True},
    ],
)
def test_canary_plan_fails_closed(overrides) -> None:
    with pytest.raises(CanaryContractError):
        plan(**overrides)


def test_canary_workflow_has_no_live_dispatch() -> None:
    workflow = (
        Path(__file__).resolve().parents[3]
        / ".github/workflows/b62-automation-canary-gate.yml"
    ).read_text(encoding="utf-8")
    assert "LIVE_CANARY=0" in workflow
    assert "PROVIDER_CALLS=0" in workflow
    assert "EXTERNAL_WRITE=0" in workflow
    assert "CONNECTOR_WRITE=0" in workflow
    assert "EXTERNAL_SEND=0" in workflow
