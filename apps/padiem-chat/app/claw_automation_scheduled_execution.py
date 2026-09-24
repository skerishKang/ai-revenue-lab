"""Full scheduled execution composition over the existing automation authorities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
    ClawAutomationTriggerReceipt,
)
from kagent.contracts import ContractError

from .claw_automation_background_execution import (
    BackgroundExecutionReceipt,
    BackgroundExecutionStore,
    compose_background_execution,
)
from .claw_automation_due_workspace_discovery import (
    ClawAutomationDueWorkspaceDiscovery,
    DueWorkspaceDiscoveryReceipt,
)
from .claw_automation_execution_bridge import P01ExecutionPort
from .claw_automation_owner_resolution import ClawAutomationOwnerResolver
from .claw_automation_projection_bridge import ClawTaskAlertProjectionStore
from .history import HistoryStore


@dataclass(frozen=True, slots=True)
class ScheduledAutomationExecutionReceipt:
    discovery: DueWorkspaceDiscoveryReceipt
    executions: tuple[BackgroundExecutionReceipt, ...]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "scheduled_execution_composed": True,
            "workspace_count": len(self.discovery.authorized_workspaces),
            "trigger_receipt_count": len(self.discovery.triggered_receipts),
            "execution_receipt_count": len(self.executions),
            "second_scheduler_authority": False,
            "second_run_id": False,
            "second_dedup_authority": False,
            "second_owner_authority": False,
            "second_p01_authority": False,
            "second_history_store": False,
            "second_task_alert_authority": False,
            # This receipt does not observe side effects performed by the injected
            # existing P01/store/history/projection authorities. It must therefore
            # never assert that the composed execution had zero provider calls or
            # zero application-state writes.
            "downstream_side_effects_observed": False,
            "production_config_mutation": 0,
            "production_migration_mutation": 0,
            "workflow_dispatch": 0,
        }


async def compose_scheduled_automation_execution(
    *,
    discovery: ClawAutomationDueWorkspaceDiscovery,
    boundary: ClawAutomationTriggerBoundary,
    store: BackgroundExecutionStore,
    adapter: P01ExecutionPort,
    owner_resolver: ClawAutomationOwnerResolver,
    history_store: HistoryStore,
    task_alert_store: ClawTaskAlertProjectionStore,
    now: datetime,
    recovery_bound: int | None = None,
    lease: Any | None = None,
    product_tier: Any | None = None,
    completed_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ScheduledAutomationExecutionReceipt:
    """Run discovery once, then compose each exact trigger with existing execution."""

    receipt = await discovery.aadiscover_and_trigger(now=now)
    triggers = receipt.triggered_triggers
    trigger_receipts = receipt.triggered_receipts
    if len(triggers) != len(trigger_receipts):
        raise ContractError("scheduled discovery trigger/receipt cardinality mismatch")
    executions: list[BackgroundExecutionReceipt] = []
    for trigger, trigger_receipt in zip(triggers, trigger_receipts, strict=True):
        if not isinstance(trigger, ClawAutomationTrigger) or not isinstance(
            trigger_receipt, ClawAutomationTriggerReceipt
        ):
            raise ContractError("scheduled discovery returned an invalid trigger receipt")
        kwargs: dict[str, Any] = {"trigger_receipt": trigger_receipt}
        if recovery_bound is not None:
            kwargs["recovery_bound"] = recovery_bound
        if lease is not None:
            kwargs["lease"] = lease
        if product_tier is not None:
            kwargs["product_tier"] = product_tier
        if completed_at is not None:
            kwargs["completed_at"] = completed_at
        if clock is not None:
            kwargs["clock"] = clock
        executions.append(
            await compose_background_execution(
                trigger=trigger,
                boundary=boundary,
                store=store,
                adapter=adapter,
                owner_resolver=owner_resolver,
                history_store=history_store,
                task_alert_store=task_alert_store,
                **kwargs,
            )
        )
    return ScheduledAutomationExecutionReceipt(
        discovery=receipt,
        executions=tuple(executions),
    )


__all__ = [
    "ScheduledAutomationExecutionReceipt",
    "compose_scheduled_automation_execution",
]