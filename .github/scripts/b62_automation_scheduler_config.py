#!/usr/bin/env python3
"""Source-only scheduler environment and Cron activation/rollback contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SCHEDULER_VAR = "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED"
EXPECTED_CRON = "* * * * *"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CRON_RE = re.compile(r"^[0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+$")


class SchedulerConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SchedulerConfigSnapshot:
    variables: dict[str, str]
    triggers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.variables, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in self.variables.items()
        ):
            raise SchedulerConfigError("scheduler variables are malformed")
        if not isinstance(self.triggers, tuple) or not all(
            isinstance(item, str) and _CRON_RE.fullmatch(item)
            for item in self.triggers
        ):
            raise SchedulerConfigError("scheduler triggers are malformed")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "scheduler_var": self.variables.get(SCHEDULER_VAR, "<absent>"),
            "triggers": list(self.triggers),
            "secret_values_included": False,
        }


def parse_snapshot(payload: object) -> SchedulerConfigSnapshot:
    if not isinstance(payload, dict) or set(payload) != {"variables", "triggers"}:
        raise SchedulerConfigError("scheduler config shape is not exact")
    variables = payload["variables"]
    triggers = payload["triggers"]
    if not isinstance(variables, dict) or not isinstance(triggers, list):
        raise SchedulerConfigError("scheduler config shape is not exact")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in variables.items()
    ) or not all(isinstance(item, str) for item in triggers):
        raise SchedulerConfigError("scheduler config values must be text")
    return SchedulerConfigSnapshot(
        variables=dict(variables),
        triggers=tuple(triggers),
    )


def classify(snapshot: SchedulerConfigSnapshot) -> str:
    if SCHEDULER_VAR not in snapshot.variables:
        return "missing"
    value = snapshot.variables[SCHEDULER_VAR]
    if value not in {"true", "false"}:
        return "drift"
    if value == "true" and snapshot.triggers != (EXPECTED_CRON,):
        return "drift"
    if value == "false" and snapshot.triggers:
        return "drift"
    if value == "true":
        return "active"
    return "inert"


def build_activation_plan(
    current: SchedulerConfigSnapshot,
    *,
    target_sha: str,
) -> dict[str, Any]:
    if not isinstance(target_sha, str) or not _SHA_RE.fullmatch(target_sha):
        raise SchedulerConfigError("activation target SHA is invalid")
    state = classify(current)
    if state not in {"inert", "active"}:
        raise SchedulerConfigError("refusing scheduler activation from missing or drifted config")
    variables = dict(current.variables)
    variables[SCHEDULER_VAR] = "true"
    target = SchedulerConfigSnapshot(variables=variables, triggers=(EXPECTED_CRON,))
    return {
        "target_sha": target_sha,
        "before": current.safe_dict(),
        "after": target.safe_dict(),
        "changes": ["SCHEDULER_VAR_SET", "CRON_DECLARATION_ADD"],
        "no_op": state == "active",
        "secret_values_read": 0,
    }


def build_rollback_plan(
    before: SchedulerConfigSnapshot,
    after: SchedulerConfigSnapshot,
    *,
    target_sha: str,
) -> dict[str, Any]:
    if not isinstance(target_sha, str) or not _SHA_RE.fullmatch(target_sha):
        raise SchedulerConfigError("rollback target SHA is invalid")
    if classify(before) != "inert" or classify(after) != "active":
        raise SchedulerConfigError("rollback requires inert-before and active-after snapshots")
    restored = SchedulerConfigSnapshot(
        variables=dict(before.variables),
        triggers=tuple(before.triggers),
    )
    return {
        "target_sha": target_sha,
        "before": after.safe_dict(),
        "after": restored.safe_dict(),
        "changes": ["SCHEDULER_VAR_SET", "CRON_DECLARATION_REMOVE"],
        "secret_values_read": 0,
    }


def render_config(snapshot: SchedulerConfigSnapshot) -> str:
    lines = ["[vars]"]
    if SCHEDULER_VAR in snapshot.variables:
        lines.append(f"{SCHEDULER_VAR} = {snapshot.variables[SCHEDULER_VAR]!r}")
    if snapshot.triggers:
        lines.extend(
            [
                "",
                "[triggers]",
                "crons = [" + ", ".join(repr(item) for item in snapshot.triggers) + "]",
            ]
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "EXPECTED_CRON",
    "SCHEDULER_VAR",
    "SchedulerConfigError",
    "SchedulerConfigSnapshot",
    "build_activation_plan",
    "build_rollback_plan",
    "classify",
    "parse_snapshot",
    "render_config",
]
