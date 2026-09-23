"""#2987 S2F6B — server-owned due-workspace discovery foundation.

COMPOSITION BOUNDARY ONLY. Everything this module needs already exists:

* the durable D1 automation store (#2983) owns rule/run/occurrence authority;
* ``ClawAutomationTriggerBoundary`` (#2894) owns the trusted single-workspace
  trigger path and the existing tick kernel;
* ``TrustedWorkspaceMembershipProjection`` owns membership authority; and
* ``ClawAutomationOwnerResolver`` owns the opaque-owner -> trusted-owner chain.

The one thing that did NOT exist on main was a **server-owned** way to learn
which workspaces currently have enabled automation candidates without handing a
product caller a tenant-wide enumeration. A real Worker ``scheduled()`` handler
cannot be truthful until that boundary exists, because a cron tick arrives with
no caller and therefore with no workspace id.

Canonical path added here:

```text
server-side discovery pass (no caller, no workspace input)
        |
        v  existing D1 store: ONE bounded, cursor-ordered page    (#2983 read)
           of candidate workspaces that currently own an ENABLED rule
        |
        v  canonical membership authority is consulted per workspace
           (injected; a workspace whose membership cannot be proven is skipped)
        |
        v  existing ClawAutomationTriggerBoundary.handle()        (#2894)
           -> existing tick kernel -> existing occurrence claim    (#2940)
        |
        v  bounded discovery receipt (identifiers + counts only)
```

Why this is not a second scheduler, and not a caller enumeration:

* NO CALLER ENUMERATION. The boundary takes **no** workspace, tenant or owner
  argument. It is the server that walks pages; a product caller has no
  supported way to obtain the workspace list from this module.
* NO SECOND SCHEDULER AUTHORITY. All schedule math, occurrence identity,
  dedup and claiming stay with ``ClawAutomationTickRuntime`` /
  ``occurrence_key``. This module computes no occurrence and mints no run id.
* NO SECOND RULE/RUN/DEDUP AUTHORITY. The only new read is the bounded page;
  the only new write is none at all -- the existing trigger boundary performs
  the claim.
* BOUNDED AND DETERMINISTIC. A page is capped by an explicit page size and the
  ordering is the store's ``workspace_id`` order, so two runs observe the same
  page sequence. The total number of workspaces examined in one pass is capped
  by ``max_workspaces``; the pass never scans without an upper bound.
* MEMBERSHIP REVALIDATED BEFORE ANY EXECUTION. A workspace whose canonical
  membership cannot be proven current is skipped, never executed and never
  terminalized, so a stale or revoked workspace simply produces no work.
* NO WORKER SCHEDULED HANDLER. ``SERVER_OWNED_DUE_WORKSPACE_DISCOVERY`` is a
  source contract. Registering a cron trigger, activating a Production
  scheduler or dispatching a workflow is explicitly NOT part of this slice.

Deliberately refused here:

* synthetic membership (a workspace id alone is never treated as a member);
* a caller-supplied workspace scan window or tenant filter;
* executing disabled rules (the candidate read filters to ``enabled = 1``);
* treating a discovery failure as an execution success.

Why the trigger step needs a SYNCHRONOUS store, stated honestly. The existing
``ClawAutomationTriggerBoundary.handle()`` (#2894) is synchronous and drives the
synchronous ``ClawAutomationTickRuntime`` / ``FakeClawScheduler`` chain, which
calls ``store.list_rules()`` / ``store.get_run_for_occurrence()`` /
``store.record_run()`` positionally and without awaiting. That is a real
structural property of the existing tick path -- not something this slice may
silently paper over -- so:

* the BOUNDED WORKSPACE PAGE read is tolerant of both shapes (``_call``), which
  is why the D1 store (#2983) can serve discovery from a Worker; and
* the TRIGGER step is delegated to the existing boundary unchanged, so it
  requires the store handed to that boundary to satisfy the existing synchronous
  tick contract.

A caller therefore composes discovery with the synchronous durable store when it
intends to actually claim runs, and uses the D1 read only to learn candidate
workspaces. Bridging an async store to the synchronous tick is explicitly NOT
this slice's job: doing it here would mean inventing a scheduler-side execution
authority, which this foundation refuses. This limitation is pinned by tests so
no consumer can mistake discovery for a working async tick.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from kagent.claw_automation import ContractError, _safe_id
from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
    ClawAutomationTriggerReceipt,
)
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection

__all__ = [
    "SERVER_OWNED_DUE_WORKSPACE_DISCOVERY",
    "DueWorkspaceDiscoveryError",
    "DueWorkspaceDiscoveryCursor",
    "DueWorkspaceDiscoveryReceipt",
    "ClawAutomationDueWorkspaceDiscovery",
]

# --- readiness and refusal flags -------------------------------------------
# Constants, not claims. No code path in this module can raise a False value to
# True, and no consumer may read this composition boundary as an activated
# scheduler.
SERVER_OWNED_DUE_WORKSPACE_DISCOVERY = True
CALLER_LIST_ALL_WORKSPACES = False
CALLER_SUPPLIED_TENANT_SCAN = False
SECOND_SCHEDULER_AUTHORITY = False
SECOND_RULE_AUTHORITY = False
SECOND_RUN_ID_AUTHORITY = False
SECOND_DEDUP_AUTHORITY = False
SYNTHETIC_MEMBERSHIP = False
WORKER_SCHEDULED_HANDLER = False
REAL_CLOUD_CRON_REGISTRATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
WORKFLOW_DISPATCH = False
PRODUCTION_MUTATION = False
PROVIDER_CALLS = 0
EXTERNAL_SEND = 0
DISABLED_RULE_DISCOVERY = 0
FUTURE_RULE_EXECUTION = 0
CANDIDATE_DISCOVERY_MAY_INCLUDE_NOT_YET_DUE_RULES = True

# One pass can never examine more workspaces than this, regardless of how many
# exist. The bound is a module constant so no caller can widen it.
_MAX_WORKSPACES_PER_PASS = 1000
_MAX_DISCOVERY_PAGE_SIZE = 200
_MIN_DISCOVERY_PAGE_SIZE = 1


class DueWorkspaceDiscoveryError(RuntimeError):
    """Raised when the discovery boundary is misconfigured or refuses a pass."""


class _CandidateWorkspacePageStore(Protocol):
    """The ONE store capability this boundary needs: a bounded workspace page."""

    def list_candidate_workspace_page(
        self,
        *,
        page_size: int,
        after_workspace_id: str | None = None,
    ) -> Any: ...


class MembershipAuthority(Protocol):
    """Trusted authority that proves current membership for one workspace.

    Mirrors the shape the trigger contract already requires: the authority is
    injected, it is never derived from the workspace id, and ``None`` means
    "cannot prove membership" -- which is a skip, never a grant.
    """

    def resolve_workspace_membership(
        self,
        *,
        workspace_id: str,
        now: datetime,
    ) -> TrustedWorkspaceMembershipProjection | None: ...


@dataclass(frozen=True, slots=True)
class DueWorkspaceDiscoveryCursor:
    """Opaque server-side continuation for the next bounded discovery pass.

    This is pagination state only. It grants no workspace membership, tenant
    scope, schedule authority or execution authority. Product callers are not
    given a raw workspace scan parameter; a continuation can only advance the
    deterministic candidate ordering.
    """

    after_workspace_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.after_workspace_id, str) or not self.after_workspace_id:
            raise DueWorkspaceDiscoveryError("continuation cursor must contain bounded text")
        _safe_id(self.after_workspace_id, "workspace_id")


@dataclass(frozen=True, slots=True)
class DueWorkspaceDiscoveryReceipt:
    """Bounded, non-secret evidence for ONE server-owned discovery pass.

    Carries identifiers and counts only: no rule body, no run output, no
    proposal text, no recipient and no credential material. It answers only
    "which workspaces were examined, which were authorized, and which canonical
    runs the existing trigger path claimed".
    """

    discovered_workspaces: tuple[str, ...]
    examined_count: int
    authorized_workspaces: tuple[str, ...]
    skipped_workspaces: tuple[str, ...]
    triggered_receipts: tuple[ClawAutomationTriggerReceipt, ...]
    claimed_run_ids: tuple[str, ...]
    page_size: int
    pages_read: int
    truncated: bool
    next_cursor: DueWorkspaceDiscoveryCursor | None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "discovered_workspaces": list(self.discovered_workspaces),
            "examined_count": self.examined_count,
            "authorized_workspaces": list(self.authorized_workspaces),
            "skipped_workspaces": list(self.skipped_workspaces),
            "claimed_run_ids": list(self.claimed_run_ids),
            "triggered_count": len(self.triggered_receipts),
            "page_size": self.page_size,
            "pages_read": self.pages_read,
            "truncated": self.truncated,
            "continuation_available": self.next_cursor is not None,
            # Refusals are pinned here so no consumer can misread this receipt
            # as a caller-visible enumeration or as a scheduler activation.
            "caller_supplied_workspace": False,
            "tenant_wide_enumeration_exposed": False,
            "synthetic_membership": False,
            "worker_scheduled_handler": False,
            "production_scheduler_activation": False,
            "provider_calls": 0,
            "external_sends": 0,
            "production_mutation": 0,
        }


def _bounded_page_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DueWorkspaceDiscoveryError("page_size must be an integer")
    if value < _MIN_DISCOVERY_PAGE_SIZE or value > _MAX_DISCOVERY_PAGE_SIZE:
        raise DueWorkspaceDiscoveryError(
            f"page_size must be between {_MIN_DISCOVERY_PAGE_SIZE} "
            f"and {_MAX_DISCOVERY_PAGE_SIZE}"
        )
    return value


def _bounded_max_workspaces(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DueWorkspaceDiscoveryError("max_workspaces must be an integer")
    if value < 1 or value > _MAX_WORKSPACES_PER_PASS:
        raise DueWorkspaceDiscoveryError(
            f"max_workspaces must be between 1 and {_MAX_WORKSPACES_PER_PASS}"
        )
    return value


async def _call(value: Any) -> Any:
    """Resolve one store result whether it is sync or awaitable.

    The durable SQLite reference answers synchronously while the D1 store can
    only answer through awaited statements. Resolving both here keeps ONE store
    contract and lets either implementation be injected. It never wraps a
    coroutine in ``asyncio.run`` and never blocks the event loop.
    """

    if inspect.isawaitable(value):
        return await value
    return value


class ClawAutomationDueWorkspaceDiscovery:
    """Server-owned, bounded, deterministic due-workspace discovery boundary.

    This class is the ONLY place in the Claw automation lane that looks across
    workspaces, and it does so on the server's own initiative: it accepts no
    caller workspace, no tenant and no owner. It pages through the bounded
    store read, proves canonical membership per workspace through the injected
    authority, and delegates each authorized workspace to the EXISTING trusted
    trigger boundary.

    It builds no trigger ids of its own invention beyond a bounded
    server-derived correlation prefix, computes no occurrence, mints no run id,
    keeps no state and owns no store.
    """

    def __init__(
        self,
        *,
        store: _CandidateWorkspacePageStore,
        membership_authority: MembershipAuthority | None,
        trigger_boundary: ClawAutomationTriggerBoundary,
    ) -> None:
        for required in ("list_candidate_workspace_page",):
            if not callable(getattr(store, required, None)):
                raise DueWorkspaceDiscoveryError(
                    f"discovery store must provide {required}()"
                )
        if not isinstance(trigger_boundary, ClawAutomationTriggerBoundary):
            raise DueWorkspaceDiscoveryError(
                "the existing trusted trigger boundary is required; "
                "no scheduler authority is created here"
            )
        self._store = store
        self._membership_authority = membership_authority
        self._trigger_boundary = trigger_boundary

    async def discover_and_trigger(
        self,
        *,
        now: datetime,
        page_size: int = _MAX_DISCOVERY_PAGE_SIZE,
        max_workspaces: int = _MAX_WORKSPACES_PER_PASS,
        trigger_id: str = "srv_due_discovery",
        continuation: DueWorkspaceDiscoveryCursor | None = None,
    ) -> DueWorkspaceDiscoveryReceipt:
        """Run ONE bounded, server-owned discovery pass.

        ``now`` is the single observation instant handed to every workspace's
        trigger, so the pass evaluates exactly one instant and performs no
        catch-up. ``page_size`` and ``max_workspaces`` are explicit bounds.
        When the pass reaches ``max_workspaces``, every workspace counted as
        examined has already completed membership revalidation and trigger
        delegation. The receipt returns a server-side continuation cursor so a
        later bounded pass can resume strictly after the last processed
        workspace instead of starving the deterministic tail.

        A workspace whose canonical membership cannot be proven is skipped and
        recorded in ``skipped_workspaces`` -- it is never executed and never
        terminalized, so a revoked membership simply produces no work.
        """

        if self._membership_authority is None:
            raise DueWorkspaceDiscoveryError(
                "trusted membership authority is unavailable; a workspace id alone "
                "is not membership and no synthetic membership is permitted"
            )
        observed_at = self._aware(now)
        bounded_page = _bounded_page_size(page_size)
        bounded_max = _bounded_max_workspaces(max_workspaces)
        bounded_trigger_id = _safe_id(trigger_id, "trigger_id")

        discovered: list[str] = []
        authorized: list[str] = []
        skipped: list[str] = []
        receipts: list[ClawAutomationTriggerReceipt] = []
        claimed: list[str] = []
        seen: set[str] = set()
        cursor: str | None = (
            continuation.after_workspace_id if continuation is not None else None
        )
        pages = 0
        truncated = False

        while True:
            page = await _call(
                self._store.list_candidate_workspace_page(
                    page_size=bounded_page,
                    after_workspace_id=cursor,
                )
            )
            pages += 1
            if not page:
                break
            advanced = False
            for raw_workspace in page:
                workspace = self._workspace(raw_workspace)
                if workspace in seen:
                    continue
                seen.add(workspace)
                advanced = True
                if len(discovered) >= bounded_max:
                    truncated = True
                    break
                discovered.append(workspace)
                membership = await self._resolve_membership(workspace, observed_at)
                if membership is None:
                    # Cannot prove membership: skip. No execution, no
                    # terminalization, no synthetic grant.
                    skipped.append(workspace)
                    if len(discovered) >= bounded_max:
                        truncated = True
                        break
                    continue
                authorized.append(workspace)
                receipt = self._trigger_boundary.handle(
                    ClawAutomationTrigger(
                        trigger_id=bounded_trigger_id,
                        correlation_id=self._correlation(workspace),
                        workspace_id=workspace,
                        observed_at=observed_at,
                        membership=membership,
                    )
                )
                receipts.append(receipt)
                for run_id in receipt.created_run_ids:
                    if run_id not in claimed:
                        claimed.append(run_id)
                if len(discovered) >= bounded_max:
                    truncated = True
                    break
            if truncated or not advanced:
                break
            cursor = discovered[-1] if discovered else None
            if cursor is None:
                break

        return DueWorkspaceDiscoveryReceipt(
            discovered_workspaces=tuple(discovered),
            examined_count=len(discovered),
            authorized_workspaces=tuple(authorized),
            skipped_workspaces=tuple(skipped),
            triggered_receipts=tuple(receipts),
            claimed_run_ids=tuple(sorted(claimed)),
            page_size=bounded_page,
            pages_read=pages,
            truncated=truncated,
            next_cursor=(
                DueWorkspaceDiscoveryCursor(discovered[-1])
                if truncated and discovered
                else None
            ),
        )

    # --- internals ----------------------------------------------------------

    async def _resolve_membership(
        self, workspace_id: str, now: datetime
    ) -> TrustedWorkspaceMembershipProjection | None:
        """Prove canonical membership, or return ``None`` (skip, never grant)."""

        try:
            projection = await _call(
                self._membership_authority.resolve_workspace_membership(
                    workspace_id=workspace_id,
                    now=now,
                )
            )
        except DueWorkspaceDiscoveryError:
            raise
        except Exception:
            # An authority failure must never be read as a grant. Skip the
            # workspace instead of inventing a membership for it.
            return None
        if not isinstance(projection, TrustedWorkspaceMembershipProjection):
            return None
        if projection.workspace_id != workspace_id:
            return None
        if not projection.valid_at(now):
            return None
        return projection

    @staticmethod
    def _workspace(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise ContractError("discovery read returned a non-text workspace id")
        return _safe_id(value, "workspace_id")

    @staticmethod
    def _correlation(workspace_id: str) -> str:
        """A bounded, server-derived correlation id. Never caller-supplied."""

        return _safe_id(f"due_{workspace_id}", "correlation_id")

    @staticmethod
    def _aware(value: object) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise DueWorkspaceDiscoveryError("now must be a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "server_owned_due_workspace_discovery": True,
            "caller_list_all_workspaces": False,
            "caller_supplied_tenant_scan": False,
            "second_scheduler_authority": False,
            "second_rule_authority": False,
            "second_run_id_authority": False,
            "second_dedup_authority": False,
            "synthetic_membership": False,
            "bounded_scan": True,
            "deterministic_order": True,
            "membership_revalidation": True,
            "worker_scheduled_handler": False,
            "real_cloud_cron_registration": False,
            "production_scheduler_activation": False,
            "workflow_dispatch": False,
            "production_mutation": False,
            "provider_calls": 0,
            "external_sends": 0,
        }
