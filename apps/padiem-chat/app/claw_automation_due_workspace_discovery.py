"""#2987 S2F6B — server-owned due-workspace discovery foundation.

COMPOSITION BOUNDARY ONLY. Everything this module needs already exists:

* the durable D1 automation store (#2983) owns rule/run/occurrence authority;
* ``ClawAutomationTriggerBoundary`` (#2894) owns the trusted single-workspace
  trigger path and the existing tick kernel;
* ``TrustedWorkspaceMembershipProjection`` owns membership authority; and
* ``ClawAutomationOwnerResolver`` owns the opaque-owner -> trusted-owner chain.

The composition now supplies the missing server-owned link from a bounded
candidate page to the canonical membership projection. A gated Worker
``scheduled()`` handler can use this path without accepting a workspace from a
caller.

Canonical path added here:

```text
server-side discovery pass (no caller, no workspace input)
        |
        v  existing D1 store: ONE bounded, cursor-ordered page    (#2983 read)
           of candidate workspaces that currently own an ENABLED rule
        |
        v  canonical membership authority is consulted per rule subject
           (injected; a rule without a current subject is skipped)
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
* SOURCE-ONLY WORKER HANDLER. The Worker handler is present but explicitly gated;
  no live Cron trigger is declared in the checked-in Worker configuration.

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

A caller therefore composes discovery with the synchronous durable store when
it uses the synchronous boundary. The async path uses the existing awaited
trigger/tick seam; neither path creates a scheduler-side execution authority.

What #2995 adds -- and nothing more. ``aadiscover_and_trigger`` runs the exact
same bounded pass and delegates each authorized workspace through
``ClawAutomationTriggerBoundary.ahandle()`` -> ``ClawAutomationTickRuntime.atick()``,
which awaits the very same schedule math, ``occurrence_key`` dedup and PENDING
claim the synchronous tick uses, against an async D1-shaped store. The Worker
handler calls this async path only behind its explicit source gate; no
Production activation comes from it.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Protocol

from kagent.claw_automation import (
    ClawAutomationRule,
    ClawAutomationRuleAuthority,
    ContractError,
    _safe_id,
    classify_rule_background_authority,
)
from kagent.claw_automation_trigger import (
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
    ClawAutomationTriggerReceipt,
)
from kagent.workspace_visibility import (
    TrustedWorkspaceMembershipProjection,
    WorkspaceRole,
)
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipState,
)

__all__ = [
    "SERVER_OWNED_DUE_WORKSPACE_DISCOVERY",
    "DueWorkspaceDiscoveryError",
    "DueWorkspaceDiscoveryCursor",
    "DueWorkspaceDiscoveryReceipt",
    "ClawAutomationDueWorkspaceDiscovery",
    "CanonicalAutomationMembershipAuthority",
    "compose_canonical_due_workspace_discovery",
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
WORKER_SCHEDULED_HANDLER = True
CRON_SOURCE_DECLARATION = False
BACKGROUND_SCHEDULER_SOURCE_READY = True
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
_CANONICAL_SUBJECT_ID_RE = r"^sub_[0-9a-f]{32}$"
_CANONICAL_MEMBERSHIP_PROJECTION_LIFETIME = timedelta(minutes=5)


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
    triggered_triggers: tuple[ClawAutomationTrigger, ...] = field(default=(), repr=False)

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
            "worker_scheduled_handler": True,
            "cron_source_declaration": False,
            "background_scheduler_source_ready": True,
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


class CanonicalSessionlessMembershipAuthority(Protocol):
    def resolve_active_tenant_membership(
        self, *, tenant_id: str, canonical_subject_id: str, now: datetime
    ) -> TenantMembership | Any: ...


class CanonicalAutomationMembershipAuthority:
    """Compose the existing sessionless resolver into the scheduler projection.

    The rule store supplies only server-persisted canonical provenance. The
    Control Plane resolver remains the sole source of tenant state, membership
    state, and role. A workspace with no single canonical subject, or with a
    legacy/roleless/inactive membership, produces no projection and therefore
    no trigger authority.
    """

    def __init__(
        self,
        *,
        rule_store: Any,
        control_plane_identity_authority: CanonicalSessionlessMembershipAuthority | None,
        projection_lifetime: timedelta = _CANONICAL_MEMBERSHIP_PROJECTION_LIFETIME,
    ) -> None:
        if not callable(getattr(rule_store, "list_rules", None)):
            raise DueWorkspaceDiscoveryError(
                "canonical membership composition requires a rule store with list_rules()"
            )
        if (
            not isinstance(projection_lifetime, timedelta)
            or projection_lifetime <= timedelta(0)
            or projection_lifetime > timedelta(hours=24)
        ):
            raise DueWorkspaceDiscoveryError(
                "membership projection lifetime must be positive and at most 24 hours"
            )
        self._rule_store = rule_store
        self._authority = control_plane_identity_authority
        self._projection_lifetime = projection_lifetime

    async def resolve_workspace_memberships(
        self, *, workspace_id: str, now: datetime
    ) -> tuple[TrustedWorkspaceMembershipProjection, ...]:
        if self._authority is None:
            return ()
        observed_at = self._aware(now)
        workspace = self._workspace(workspace_id)
        try:
            rules = await _call(self._rule_store.list_rules(workspace))
        except Exception:
            return ()
        if not isinstance(rules, (list, tuple)):
            return ()
        subjects: set[str] = set()
        for rule in rules:
            if not isinstance(rule, ClawAutomationRule) or not rule.enabled:
                continue
            if rule.workspace_id != workspace:
                continue
            if (
                classify_rule_background_authority(rule)
                is not ClawAutomationRuleAuthority.CANONICAL_BACKGROUND_ELIGIBLE
            ):
                continue
            subject = rule.canonical_subject_id
            if not isinstance(subject, str) or not re.fullmatch(
                _CANONICAL_SUBJECT_ID_RE, subject
            ):
                continue
            subjects.add(subject)
        projections: list[TrustedWorkspaceMembershipProjection] = []
        for subject in sorted(subjects):
            try:
                membership = await _call(
                    self._authority.resolve_active_tenant_membership(
                        tenant_id=workspace,
                        canonical_subject_id=subject,
                        now=observed_at,
                    )
                )
            except Exception:
                continue
            if not isinstance(membership, TenantMembership):
                continue
            if (
                membership.tenant_id != workspace
                or membership.canonical_subject_id != subject
                or membership.state is not TenantMembershipState.ACTIVE
                or membership.role is None
                or membership.created_at is None
                or membership.created_at > observed_at
            ):
                continue
            try:
                role = WorkspaceRole(membership.role.value)
            except (TypeError, ValueError):
                continue
            projections.append(
                TrustedWorkspaceMembershipProjection(
                    membership_id=f"membership_{workspace}_{subject}",
                    workspace_id=workspace,
                    principal_ref=subject,
                    role=role,
                    authority_ref="control_plane_sessionless_membership",
                    issued_at=observed_at,
                    expires_at=observed_at + self._projection_lifetime,
                )
            )
        return tuple(projections)

    async def resolve_workspace_membership(
        self, *, workspace_id: str, now: datetime
    ) -> TrustedWorkspaceMembershipProjection | None:
        projections = await self.resolve_workspace_memberships(
            workspace_id=workspace_id, now=now
        )
        return projections[0] if len(projections) == 1 else None

    def safe_dict(self) -> dict[str, Any]:
        return {
            "canonical_membership_projection": True,
            "per_rule_subject_isolation": True,
            "reuses_sessionless_resolver": True,
            "role_required": True,
            "default_role": False,
            "synthetic_membership": False,
            "legacy_workspace_alias": False,
            "second_membership_authority": False,
            "projection_lifetime_seconds": int(
                self._projection_lifetime.total_seconds()
            ),
        }

    @staticmethod
    def _aware(value: object) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise DueWorkspaceDiscoveryError("now must be a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _workspace(value: object) -> str:
        if not isinstance(value, str) or not value:
            raise DueWorkspaceDiscoveryError("workspace_id must be bounded text")
        return _safe_id(value, "workspace_id")


def compose_canonical_due_workspace_discovery(
    *,
    automation_store: Any,
    control_plane_identity_authority: CanonicalSessionlessMembershipAuthority | None,
    trigger_boundary: ClawAutomationTriggerBoundary,
) -> ClawAutomationDueWorkspaceDiscovery:
    membership_authority = CanonicalAutomationMembershipAuthority(
        rule_store=automation_store,
        control_plane_identity_authority=control_plane_identity_authority,
    )
    return ClawAutomationDueWorkspaceDiscovery(
        store=automation_store,
        membership_authority=membership_authority,
        trigger_boundary=trigger_boundary,
    )


class ClawAutomationDueWorkspaceDiscovery:
    """Server-owned, bounded, deterministic due-workspace discovery boundary.

    This class is the ONLY place in the Claw automation lane that looks across
    workspaces, and it does so on the server's own initiative: it accepts no
    caller workspace, no tenant and no owner. It pages through the bounded
    store read, proves canonical membership per rule subject through the injected
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
        """Run ONE bounded pass with the EXISTING synchronous dispatch (#2987).

        Delegates every authorized workspace to the synchronous
        ``ClawAutomationTriggerBoundary.handle()`` exactly as before; see
        ``aadiscover_and_trigger`` for the awaited persistence twin.
        """

        return await self._run_pass(
            now=now,
            page_size=page_size,
            max_workspaces=max_workspaces,
            trigger_id=trigger_id,
            continuation=continuation,
            async_dispatch=False,
        )

    async def aadiscover_and_trigger(
        self,
        *,
        now: datetime,
        page_size: int = _MAX_DISCOVERY_PAGE_SIZE,
        max_workspaces: int = _MAX_WORKSPACES_PER_PASS,
        trigger_id: str = "srv_due_discovery",
        continuation: DueWorkspaceDiscoveryCursor | None = None,
    ) -> DueWorkspaceDiscoveryReceipt:
        """Run the SAME bounded pass with awaited trigger dispatch (#2995).

        Byte-identical bounds, ordering, membership revalidation, continuation
        contract and receipt as ``discover_and_trigger``; the only difference is
        that each authorized workspace is delegated through
        ``ClawAutomationTriggerBoundary.ahandle()`` -> ``atick()``, so a
        D1-shaped async store is served end to end without blocking the event
        loop. One discovery algorithm, one tick authority, two persistence
        shapes -- and still no handler registration, no cron and no Production
        activation.
        """

        return await self._run_pass(
            now=now,
            page_size=page_size,
            max_workspaces=max_workspaces,
            trigger_id=trigger_id,
            continuation=continuation,
            async_dispatch=True,
        )

    async def _run_pass(
        self,
        *,
        now: datetime,
        page_size: int = _MAX_DISCOVERY_PAGE_SIZE,
        max_workspaces: int = _MAX_WORKSPACES_PER_PASS,
        trigger_id: str = "srv_due_discovery",
        continuation: DueWorkspaceDiscoveryCursor | None = None,
        async_dispatch: bool = False,
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

        A workspace with no currently authorized canonical subject is skipped and
        recorded in ``skipped_workspaces`` -- individual legacy or revoked rules
        are never executed or terminalized.
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
        triggers: list[ClawAutomationTrigger] = []
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
                memberships = await self._resolve_memberships(workspace, observed_at)
                if not memberships:
                    skipped.append(workspace)
                    if len(discovered) >= bounded_max:
                        truncated = True
                        break
                    continue
                authorized.append(workspace)
                trigger = ClawAutomationTrigger(
                    trigger_id=bounded_trigger_id,
                    correlation_id=self._correlation(workspace),
                    workspace_id=workspace,
                    observed_at=observed_at,
                    membership=memberships[0] if len(memberships) == 1 else None,
                    memberships=memberships,
                )
                if async_dispatch:
                    # #2995 async persistence seam: identical validation and
                    # tick authority, awaited store application only.
                    receipt = await self._trigger_boundary.ahandle(trigger)
                else:
                    receipt = self._trigger_boundary.handle(trigger)
                triggers.append(trigger)
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
            triggered_triggers=tuple(triggers),
        )

    # --- internals ----------------------------------------------------------

    async def _resolve_memberships(
        self, workspace_id: str, now: datetime
    ) -> tuple[TrustedWorkspaceMembershipProjection, ...]:
        """Prove all current per-subject memberships, or return an empty set."""

        try:
            plural = getattr(
                self._membership_authority, "resolve_workspace_memberships", None
            )
            if callable(plural):
                projections = await _call(
                    plural(workspace_id=workspace_id, now=now)
                )
            else:
                projection = await _call(
                    self._membership_authority.resolve_workspace_membership(
                        workspace_id=workspace_id,
                        now=now,
                    )
                )
                projections = (projection,) if projection is not None else ()
        except DueWorkspaceDiscoveryError:
            raise
        except Exception:
            return ()
        if not isinstance(projections, (list, tuple)):
            return ()
        valid: list[TrustedWorkspaceMembershipProjection] = []
        for projection in projections:
            if not isinstance(projection, TrustedWorkspaceMembershipProjection):
                continue
            if projection.workspace_id != workspace_id or not projection.valid_at(now):
                continue
            if projection not in valid:
                valid.append(projection)
        return tuple(valid)

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
            "worker_scheduled_handler": True,
            "cron_source_declaration": False,
            "background_scheduler_source_ready": True,
            "real_cloud_cron_registration": False,
            "production_scheduler_activation": False,
            "workflow_dispatch": False,
            "production_mutation": False,
            "provider_calls": 0,
            "external_sends": 0,
        }
