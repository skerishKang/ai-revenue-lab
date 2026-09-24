"""#2833 S-1: trusted background scheduler trigger boundary.

A trusted scheduler trigger is the only thing allowed to drive the durable
automation tick kernel from outside a request. This module defines that
boundary; it deliberately owns no scheduling logic of its own.

```text
trusted trigger  ->  one explicit workspace_id
                 ->  authoritative membership projection
                 ->  ClawAutomationTickRuntime (existing authority)
                 ->  durable occurrence claim (existing occurrence_key dedup)
                 ->  bounded trigger receipt
```

Design boundaries pinned here:

* ONE_TRIGGER_ONE_WORKSPACE. A trigger names exactly one workspace. There is no
  enumeration or "all workspaces" sweep, and no tenant-wide implicit authority.
* Membership is mandatory and must be a ``TrustedWorkspaceMembershipProjection``.
  A caller-minted value (``None``, a dict, a bare id, ``0``, ``False``) is
  rejected fail-closed, so "no membership" can never become a wildcard grant.
* A foreign membership projection is rejected; an expired or not-yet-valid
  projection produces zero runs without an error.
* No new scheduling algorithm, no second dedup authority, no lock table and no
  store of its own: the pre-existing tick runtime and its ``occurrence_key``
  claim semantics are reused unchanged.
* No misfire policy. Only the exact observed instant is evaluated, so a late
  trigger cannot mass-run past occurrences. Catch-up stays a separate decision.
* No side effects: no provider call, no external send, no connector write, no
  canonical P01 dispatch and no sandbox allocation.

The boundary is source-ready for a gated Worker scheduled handler. Production
activation and canonical scheduled execution remain separate gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .claw_automation import (
    ClawAutomationTickReceipt,
    ClawAutomationTickRuntime,
    ContractError,
    # Shared validation authorities from the automation contract: importing them
    # keeps one definition of "bounded safe id" and "timezone-aware instant",
    # instead of growing a second, drifting copy in this module.
    _aware_utc,
    _safe_id,
)
from .workspace_visibility import TrustedWorkspaceMembershipProjection

__all__ = [
    "ClawAutomationTrigger",
    "ClawAutomationTriggerBoundary",
    "ClawAutomationTriggerReceipt",
]


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ClawAutomationTrigger:
    """A trusted scheduler trigger for exactly one workspace.

    ``trigger_id`` identifies the trusted source that raised the trigger;
    ``correlation_id`` ties the delivered trigger to its receipt. Both are
    bounded safe ids. ``membership`` must be the authoritative projection minted
    by the control plane -- this contract never mints or widens it.
    """

    trigger_id: str
    correlation_id: str
    workspace_id: str
    observed_at: datetime
    membership: TrustedWorkspaceMembershipProjection

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_id", _safe_id(self.trigger_id, "trigger_id"))
        object.__setattr__(
            self, "correlation_id", _safe_id(self.correlation_id, "correlation_id")
        )
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        # A missing or caller-minted authority is not a default and not a
        # wildcard: it is refused before any scheduling work can happen.
        if not isinstance(self.membership, TrustedWorkspaceMembershipProjection):
            raise ContractError(
                "trigger requires a trusted workspace membership projection; "
                "caller-minted or absent membership is not permitted"
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "correlation_id": self.correlation_id,
            "workspace_id": self.workspace_id,
            "observed_at": _iso(self.observed_at),
            "membership_trusted": True,
            "membership_client_asserted": False,
        }


@dataclass(frozen=True, slots=True)
class ClawAutomationTriggerReceipt:
    """Bounded, non-secret evidence for exactly one handled trigger.

    Like the tick receipt it mirrors, this is not a user-facing execution
    report: it carries no output body, no proposal text, no recipient and no
    credential material. It answers only "which trigger observed what, and which
    canonical runs were claimed".
    """

    trigger_id: str
    correlation_id: str
    workspace_id: str
    observed_at: datetime
    due_count: int
    created_run_ids: tuple[str, ...]
    deduplicated_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_id", _safe_id(self.trigger_id, "trigger_id"))
        object.__setattr__(
            self, "correlation_id", _safe_id(self.correlation_id, "correlation_id")
        )
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        for field_name in ("due_count", "deduplicated_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractError(f"{field_name} must be a non-negative integer")
        if not isinstance(self.created_run_ids, tuple):
            raise ContractError("created_run_ids must be a tuple")
        norm_ids = tuple(_safe_id(run_id, "created_run_id") for run_id in self.created_run_ids)
        object.__setattr__(self, "created_run_ids", norm_ids)
        if len(norm_ids) != len(set(norm_ids)):
            raise ContractError("created_run_ids must not contain duplicates")
        if self.due_count < len(norm_ids):
            raise ContractError("due_count cannot be smaller than the created run count")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "correlation_id": self.correlation_id,
            "workspace_id": self.workspace_id,
            "observed_at": _iso(self.observed_at),
            "due_count": self.due_count,
            "created_run_ids": list(self.created_run_ids),
            "deduplicated_count": self.deduplicated_count,
            # Side-effect locks for this slice. They are constants, not claims:
            # the boundary has no path that could raise them.
            "provider_calls": 0,
            "external_sends": 0,
            "connector_writes": 0,
            "canonical_dispatches": 0,
            "sandbox_allocations": 0,
            "catch_up_occurrences": 0,
            "background_trigger_source": True,
            "production_scheduler": False,
            "canonical_dispatch": False,
            "client_asserted_authority": False,
        }

    @classmethod
    def from_tick_receipt(
        cls,
        *,
        trigger: ClawAutomationTrigger,
        tick: ClawAutomationTickReceipt,
    ) -> "ClawAutomationTriggerReceipt":
        if not isinstance(trigger, ClawAutomationTrigger):
            raise ContractError("trigger must be a ClawAutomationTrigger")
        if not isinstance(tick, ClawAutomationTickReceipt):
            raise ContractError("tick must be a ClawAutomationTickReceipt")
        return cls(
            trigger_id=trigger.trigger_id,
            correlation_id=trigger.correlation_id,
            workspace_id=tick.workspace_id,
            observed_at=tick.observed_at,
            due_count=tick.due_count,
            created_run_ids=tick.created_run_ids,
            deduplicated_count=tick.deduplicated_count,
        )


class ClawAutomationTriggerBoundary:
    """Trusted trigger -> existing tick kernel. No new scheduling authority.

    The boundary validates the trigger contract and then delegates to the
    pre-existing ``ClawAutomationTickRuntime``. It performs no scheduling, no
    occurrence math, no dedup bookkeeping and no store write of its own.
    """

    def __init__(self, runtime: ClawAutomationTickRuntime) -> None:
        if not isinstance(runtime, ClawAutomationTickRuntime):
            raise ContractError("trigger boundary requires a ClawAutomationTickRuntime")
        self._runtime = runtime

    def _validated(
        self, trigger: object
    ) -> TrustedWorkspaceMembershipProjection:
        """Shared trigger/membership validation for BOTH dispatch shapes.

        ``handle()`` and ``ahandle()`` refuse exactly the same inputs before any
        scheduling work can happen (#2995), so the async persistence seam can
        never become a weaker entrance to the same tick authority.
        """

        if not isinstance(trigger, ClawAutomationTrigger):
            raise ContractError("trigger boundary accepts a ClawAutomationTrigger only")
        membership = trigger.membership
        if not isinstance(membership, TrustedWorkspaceMembershipProjection):
            raise ContractError(
                "trigger requires a trusted workspace membership projection"
            )
        if membership.workspace_id != trigger.workspace_id:
            # A projection for another workspace is not a tenant-wide grant.
            raise ContractError("membership projection does not cover the trigger workspace")
        return membership

    def handle(self, trigger: ClawAutomationTrigger) -> ClawAutomationTriggerReceipt:
        """Process one trusted trigger for one workspace and return a receipt."""

        membership = self._validated(trigger)
        # Exactly the observed instant is evaluated: no backfill, no catch-up.
        tick = self._runtime.tick(
            workspace_id=trigger.workspace_id,
            current_time=trigger.observed_at,
            membership=membership,
        )
        return ClawAutomationTriggerReceipt.from_tick_receipt(trigger=trigger, tick=tick)

    async def ahandle(
        self, trigger: ClawAutomationTrigger
    ) -> ClawAutomationTriggerReceipt:
        """Process one trusted trigger through the SAME boundary, awaited (#2995).

        Identical validation, identical receipt type and identical tick
        authority as ``handle`` -- only the persistence application is awaited
        (``ClawAutomationTickRuntime.atick``), so a D1-shaped async store is
        served with no synchronous wrapper and no blocked event loop. One
        scheduling algorithm, two persistence shapes; this seam registers no
        cron trigger and activates no Production scheduler.
        """

        self._validated(trigger)
        tick = await self._runtime.atick(
            workspace_id=trigger.workspace_id,
            current_time=trigger.observed_at,
            membership=trigger.membership,
        )
        return ClawAutomationTriggerReceipt.from_tick_receipt(trigger=trigger, tick=tick)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "trusted_trigger_boundary": True,
            "one_trigger_one_workspace": True,
            "workspace_enumeration": False,
            "requires_trusted_membership": True,
            "membership_may_be_omitted": False,
            "reuses_tick_runtime": True,
            "async_persistence_seam": True,
            "new_scheduler_algorithm": False,
            "new_dedup_authority": False,
            "catch_up_policy": "none",
            "automatic_backfill": False,
            "unbounded_catch_up": False,
            "background_trigger_source": True,
            "production_scheduler_activation": False,
            "canonical_dispatch": False,
            "provider_calls": 0,
            "external_sends": 0,
            "sandbox_allocations": 0,
        }
