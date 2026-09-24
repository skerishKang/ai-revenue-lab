"""Bounded source-only canary contract for the #2833 scheduler lane."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TENANT_RE = re.compile(r"^tenant_[0-9a-f]{32}$")
_SUBJECT_RE = re.compile(r"^sub_[0-9a-f]{32}$")
_RULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TIMEZONE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+-]{0,63}$")
_INTERVAL_RE = re.compile(r"^[1-9][0-9]{0,3}[smhd]$")
_CRON_RE = re.compile(r"^[0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+$")


class CanaryContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AutomationCanaryPlan:
    workspace_id: str
    rule_id: str
    canonical_subject_id: str
    schedule_kind: str
    schedule_expression: str
    timezone: str
    target_source: str
    output_type: str
    max_occurrences: int = 1
    max_runs: int = 1
    max_task_alert_outputs: int = 1
    external_write: bool = False
    external_send: bool = False

    def __post_init__(self) -> None:
        if not _TENANT_RE.fullmatch(self.workspace_id):
            raise CanaryContractError("canary workspace must be a canonical tenant")
        if not _SUBJECT_RE.fullmatch(self.canonical_subject_id):
            raise CanaryContractError("canary subject must be canonical")
        if not _RULE_RE.fullmatch(self.rule_id):
            raise CanaryContractError("canary rule id is invalid")
        if self.schedule_kind not in {"cron", "interval", "daypart"}:
            raise CanaryContractError("canary schedule kind is invalid")
        if not self.schedule_expression or len(self.schedule_expression) > 128:
            raise CanaryContractError("canary schedule expression is invalid")
        if self.schedule_kind == "interval" and not _INTERVAL_RE.fullmatch(self.schedule_expression):
            raise CanaryContractError("canary interval expression is invalid")
        if self.schedule_kind == "cron" and not _CRON_RE.fullmatch(self.schedule_expression):
            raise CanaryContractError("canary cron expression is invalid")
        if self.schedule_kind == "daypart" and self.schedule_expression not in {
            "morning",
            "midday",
            "evening",
            "close_of_business",
        }:
            raise CanaryContractError("canary daypart expression is invalid")
        if not _TIMEZONE_RE.fullmatch(self.timezone):
            raise CanaryContractError("canary timezone is invalid")
        if self.target_source not in {"memory", "inbox", "tasks"}:
            raise CanaryContractError("canary target must not use connectors")
        if self.output_type not in {"report", "alert", "task_proposal"}:
            raise CanaryContractError("canary output type is invalid")
        for name, value in (
            ("max_occurrences", self.max_occurrences),
            ("max_runs", self.max_runs),
            ("max_task_alert_outputs", self.max_task_alert_outputs),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value != 1:
                raise CanaryContractError(f"{name} must equal one")
        if self.external_write or self.external_send:
            raise CanaryContractError("canary external side effects are forbidden")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "canary_ready": True,
            "workspace_id": self.workspace_id,
            "rule_id": self.rule_id,
            "canonical_subject_id": self.canonical_subject_id,
            "schedule_kind": self.schedule_kind,
            "schedule_expression": self.schedule_expression,
            "timezone": self.timezone,
            "target_source": self.target_source,
            "output_type": self.output_type,
            "max_occurrences": self.max_occurrences,
            "max_runs": self.max_runs,
            "max_task_alert_outputs": self.max_task_alert_outputs,
            "external_write": False,
            "external_send": False,
            "live_probe": False,
        }


__all__ = ["AutomationCanaryPlan", "CanaryContractError"]
