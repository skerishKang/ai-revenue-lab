"""#2987 S2F6B — server-owned due-workspace discovery foundation proofs.

Two layers are proven here, and they are deliberately kept separate so one kind
of evidence is never presented as another:

LAYER A — the bounded workspace PAGE read on the durable D1 store (#2983).
  Executed against a real SQLite statement double, so the page SQL runs rather
  than being mocked. Proves the read is bounded, cursor-ordered, deterministic
  and enabled-only, and that it never returns anything but workspace ids.

LAYER B — the discovery+trigger boundary against a SYNCHRONOUS durable store.
  The existing ``ClawAutomationTriggerBoundary.handle()`` is synchronous and
  drives the synchronous tick kernel, so it requires a synchronous store. Layer B
  therefore uses the kernel's own durable ``SqliteClawAutomationStore`` and proves
  the discovery pass composes with the EXISTING tick / dedup / claim path.

Nothing here activates a scheduler, registers cron, calls a provider or mutates
Production.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve()
_CHAT = _HERE.parent.parent
_REPO = _CHAT.parent.parent
_KAGENT_SRC = _REPO / "apps" / "korean-ai-code-agent" / "src"

# Prefer the kernel SOURCE tree when it is present, because a stale installed
# copy would silently exercise a different authority than the one under test.
# This is a PREFERENCE, never an assertion: CI legitimately resolves kagent from
# an installed distribution, and a hard assert there would fail collection for
# every unrelated job too (observed on run 35900029867).
if (_KAGENT_SRC / "kagent" / "__init__.py").exists():
    sys.path.insert(0, str(_KAGENT_SRC))

from kagent.claw_automation import (  # noqa: E402
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRunStatus,
    ContractError,
    InMemoryClawAutomationStore,
)
from kagent.claw_automation_trigger import (  # noqa: E402
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
)
from kagent.workspace_visibility import (  # noqa: E402
    TrustedWorkspaceMembershipProjection,
    WorkspaceRole,
)
from padiem_control_plane.tenants import (  # noqa: E402
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app import claw_automation_due_workspace_discovery as discovery_mod  # noqa: E402
from app import claw_automation_store as store_mod  # noqa: E402
from app.claw_automation_due_workspace_discovery import (  # noqa: E402
    CanonicalAutomationMembershipAuthority,
    ClawAutomationDueWorkspaceDiscovery,
    DueWorkspaceDiscoveryError,
    compose_canonical_due_workspace_discovery,
)
from app.claw_automation_store import D1ClawAutomationStore  # noqa: E402

MIGRATION_PATH = _CHAT / "migrations" / "018_claw_automation_durable_store.sql"
MIGRATION_019_PATH = _CHAT / "migrations" / "019_claw_automation_rule_provenance.sql"
NOW = datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc)


class PageStore:
    """A synchronous store exposing ONLY the bounded page read.

    Used to prove Layer B in isolation: the discovery boundary must not require
    any capability beyond ``list_candidate_workspace_page`` from the page source, and
    the trigger step is served by a separate synchronous store.
    """

    def __init__(self, pages: list[list[str]]) -> None:
        self._pages = pages
        self.calls: list[tuple[int, str | None]] = []

    def list_candidate_workspace_page(
        self, *, page_size: int, after_workspace_id: str | None = None
    ) -> list[str]:
        self.calls.append((page_size, after_workspace_id))
        if not self._pages:
            return []
        return self._pages.pop(0)


class ComposedStore(PageStore):
    def __init__(self, pages: list[list[str]], backing: Any) -> None:
        super().__init__(pages)
        self._backing = backing

    def list_rules(self, workspace_id: str) -> list[Any]:
        return self._backing.list_rules(workspace_id)

    def get_run_for_occurrence(self, key: str, workspace_id: str) -> Any:
        return self._backing.get_run_for_occurrence(key, workspace_id)

    def record_run(self, run: Any) -> Any:
        return self._backing.record_run(run)


# ---------------------------------------------------------------------------
# D1 statement double (same shape the #2983 store test uses)
# ---------------------------------------------------------------------------


class SqliteD1Statement:
    def __init__(self, conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.conn = conn
        self.sql = sql
        self.params = params

    def bind(self, *values: Any) -> "SqliteD1Statement":
        return SqliteD1Statement(self.conn, self.sql, values)

    async def run(self) -> dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        return {"success": True}

    async def first(self) -> dict[str, Any] | None:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    async def all(self) -> list[dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(self.sql, self.params)
        return [dict(r) for r in cursor.fetchall()]


class SqliteD1Binding:
    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self.conn = conn or sqlite3.connect(
            ":memory:", check_same_thread=False, isolation_level=None
        )
        self.conn.row_factory = sqlite3.Row

    def prepare(self, sql: str) -> SqliteD1Statement:
        return SqliteD1Statement(self.conn, sql)

    async def batch(self, statements: list[SqliteD1Statement]) -> list[Any]:
        from types import SimpleNamespace

        results: list[SimpleNamespace] = []
        for statement in statements:
            cursor = self.conn.cursor()
            cursor.execute(statement.sql, statement.params)
            try:
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                rows = []
            results.append(SimpleNamespace(results=[dict(r) for r in rows], success=True))
        return results


@pytest.fixture
def d1_db() -> SqliteD1Binding:
    binding = SqliteD1Binding()
    for path in (MIGRATION_PATH, MIGRATION_019_PATH):
        binding.conn.executescript(path.read_text(encoding="utf-8"))
    return binding


@pytest.fixture
def d1_store(d1_db: SqliteD1Binding) -> D1ClawAutomationStore:
    return D1ClawAutomationStore(d1_db)


@pytest.fixture
def sync_store() -> InMemoryClawAutomationStore:
    return InMemoryClawAutomationStore()


# ---------------------------------------------------------------------------
# membership authority doubles
# ---------------------------------------------------------------------------


class StaticMembershipAuthority:
    """Proves membership only for workspaces it was explicitly given."""

    def __init__(self, workspaces: dict[str, str] | None = None) -> None:
        self._workspaces = dict(workspaces or {})
        self.calls: list[str] = []

    def resolve_workspace_membership(
        self, *, workspace_id: str, now: datetime
    ) -> TrustedWorkspaceMembershipProjection | None:
        self.calls.append(workspace_id)
        principal = self._workspaces.get(workspace_id)
        if principal is None:
            return None
        return TrustedWorkspaceMembershipProjection(
            membership_id=f"mem_{workspace_id}",
            workspace_id=workspace_id,
            principal_ref=principal,
            role=WorkspaceRole.OWNER,
            authority_ref="auth_test",
            issued_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(hours=1),
        )


class ExplodingMembershipAuthority:
    def resolve_workspace_membership(self, *, workspace_id: str, now: datetime) -> Any:
        raise RuntimeError("authority unavailable")


class ForeignMembershipAuthority:
    """Always returns a projection for a DIFFERENT workspace."""

    def resolve_workspace_membership(
        self, *, workspace_id: str, now: datetime
    ) -> TrustedWorkspaceMembershipProjection:
        return TrustedWorkspaceMembershipProjection(
            membership_id="mem_other",
            workspace_id="ws_other",
            principal_ref="prin_other",
            role=WorkspaceRole.OWNER,
            authority_ref="auth_test",
            issued_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(hours=1),
        )


class DictMembershipAuthority:
    """A look-alike that is NOT a trusted projection."""

    def resolve_workspace_membership(self, *, workspace_id: str, now: datetime) -> Any:
        return {"workspace_id": workspace_id, "role": "owner"}


class ExpiredMembershipAuthority:
    def resolve_workspace_membership(
        self, *, workspace_id: str, now: datetime
    ) -> TrustedWorkspaceMembershipProjection:
        return TrustedWorkspaceMembershipProjection(
            membership_id="mem_a",
            workspace_id=workspace_id,
            principal_ref="prin_a",
            role=WorkspaceRole.OWNER,
            authority_ref="auth_test",
            issued_at=now - timedelta(hours=5),
            expires_at=now - timedelta(hours=1),
        )


CANONICAL_TENANT = "tenant_0123456789abcdef0123456789abcdef"
CANONICAL_SUBJECT = "sub_0123456789abcdef0123456789abcdef"


class CanonicalSessionlessAuthority:
    def __init__(
        self,
        membership: TenantMembership | None = None,
        *,
        memberships: dict[str, TenantMembership | None] | None = None,
    ) -> None:
        self.membership = membership
        self.memberships = dict(memberships or {})
        self.calls: list[dict[str, Any]] = []

    async def resolve_active_tenant_membership(
        self, *, tenant_id: str, canonical_subject_id: str, now: datetime
    ) -> TenantMembership | None:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "canonical_subject_id": canonical_subject_id,
                "now": now,
            }
        )
        return self.memberships.get(canonical_subject_id, self.membership)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _rule(
    workspace_id: str,
    rule_id: str,
    *,
    enabled: bool = True,
    kind: ClawScheduleKind = ClawScheduleKind.CRON,
    expression: str = "* * * * *",
    timezone_name: str = "UTC",
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=f"rule {rule_id}",
        schedule=ClawScheduleExpression(
            kind=kind, expression=expression, timezone=timezone_name
        ),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        owner_ref=f"own_{workspace_id}",
    )


def _discovery(
    page_store: Any, authority: Any, trigger_boundary: ClawAutomationTriggerBoundary
) -> ClawAutomationDueWorkspaceDiscovery:
    return ClawAutomationDueWorkspaceDiscovery(
        store=page_store,
        membership_authority=authority,
        trigger_boundary=trigger_boundary,
    )


def _canonical_membership(
    *,
    tenant_id: str = CANONICAL_TENANT,
    subject_id: str = CANONICAL_SUBJECT,
    role: TenantMembershipRole | None = TenantMembershipRole.OPERATOR,
    state: TenantMembershipState = TenantMembershipState.ACTIVE,
    created_at: datetime | None = None,
) -> TenantMembership:
    return TenantMembership(
        tenant_id=tenant_id,
        canonical_subject_id=subject_id,
        state=state,
        created_at=created_at or (NOW - timedelta(minutes=1)),
        role=role,
    )


def _membership_projection(
    subject_id: str,
    *,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> TrustedWorkspaceMembershipProjection:
    return TrustedWorkspaceMembershipProjection(
        membership_id=f"mem_{subject_id}",
        workspace_id=CANONICAL_TENANT,
        principal_ref=subject_id,
        role=WorkspaceRole.OPERATOR,
        authority_ref="test_authority",
        issued_at=issued_at or (NOW - timedelta(minutes=5)),
        expires_at=expires_at or (NOW + timedelta(hours=1)),
    )


def _sync_boundary(store: Any) -> ClawAutomationTriggerBoundary:
    return ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))


# ===========================================================================
# LAYER A — the bounded workspace page read on the durable D1 store
# ===========================================================================


def test_due_workspace_page_is_bounded_by_page_size(d1_store: D1ClawAutomationStore) -> None:
    for index in range(5):
        _run(d1_store.save_rule(_rule(f"ws_{index:02d}", f"r_{index}")))
    page = _run(d1_store.list_candidate_workspace_page(page_size=2))
    assert len(page) == 2


def test_due_workspace_page_ordering_is_deterministic(d1_store: D1ClawAutomationStore) -> None:
    for name in ("ws_c", "ws_a", "ws_b"):
        _run(d1_store.save_rule(_rule(name, f"r_{name}")))
    first = _run(d1_store.list_candidate_workspace_page(page_size=10))
    second = _run(d1_store.list_candidate_workspace_page(page_size=10))
    assert first == second == ["ws_a", "ws_b", "ws_c"]


def test_due_workspace_page_cursor_advances_without_gaps(
    d1_store: D1ClawAutomationStore,
) -> None:
    for index in range(5):
        _run(d1_store.save_rule(_rule(f"ws_{index:02d}", f"r_{index}")))
    collected: list[str] = []
    cursor: str | None = None
    while True:
        page = _run(d1_store.list_candidate_workspace_page(page_size=2, after_workspace_id=cursor))
        if not page:
            break
        collected.extend(page)
        cursor = page[-1]
    assert collected == [f"ws_{i:02d}" for i in range(5)]


def test_disabled_only_workspace_is_not_discovered(d1_store: D1ClawAutomationStore) -> None:
    _run(d1_store.save_rule(_rule("ws_enabled", "r1", enabled=True)))
    _run(d1_store.save_rule(_rule("ws_disabled", "r2", enabled=False)))
    page = _run(d1_store.list_candidate_workspace_page(page_size=50))
    assert page == ["ws_enabled"]


def test_page_size_bounds_are_enforced(d1_store: D1ClawAutomationStore) -> None:
    with pytest.raises(ContractError):
        _run(d1_store.list_candidate_workspace_page(page_size=0))
    with pytest.raises(ContractError):
        _run(
            d1_store.list_candidate_workspace_page(
                page_size=store_mod._MAX_CANDIDATE_WORKSPACE_PAGE_SIZE + 1
            )
        )
    with pytest.raises(ContractError):
        _run(d1_store.list_candidate_workspace_page(page_size=True))  # type: ignore[arg-type]


def test_page_returns_identifiers_only(d1_store: D1ClawAutomationStore) -> None:
    _run(d1_store.save_rule(_rule("ws_one", "r1")))
    page = _run(d1_store.list_candidate_workspace_page(page_size=10))
    assert page == ["ws_one"]
    assert all(isinstance(item, str) for item in page)


def test_workspace_scoped_lists_still_refuse_cross_tenant_reads(
    d1_store: D1ClawAutomationStore,
) -> None:
    _run(d1_store.save_rule(_rule("ws_a", "r_a")))
    _run(d1_store.save_rule(_rule("ws_b", "r_b")))
    assert [r.rule_id for r in _run(d1_store.list_rules("ws_a"))] == ["r_a"]
    assert [r.rule_id for r in _run(d1_store.list_rules("ws_b"))] == ["r_b"]


def test_d1_page_has_no_workspace_argument_beyond_the_cursor() -> None:
    import inspect as _inspect

    signature = _inspect.signature(D1ClawAutomationStore.list_candidate_workspace_page)
    assert set(signature.parameters) == {"self", "page_size", "after_workspace_id"}


# ===========================================================================
# LAYER B — discovery + existing trigger boundary (synchronous durable store)
# ===========================================================================


def test_discovery_requires_only_the_bounded_page_capability(sync_store: Any) -> None:
    """The page source must not need rule/run methods; the trigger store holds those."""

    for name in ("ws_a", "ws_b"):
        sync_store.save_rule(_rule(name, f"r_{name}"))
    page_store = PageStore([["ws_a", "ws_b"], []])
    authority = StaticMembershipAuthority({"ws_a": "prin_a", "ws_b": "prin_b"})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW, page_size=2
        )
    )
    assert receipt.discovered_workspaces == ("ws_a", "ws_b")
    assert receipt.authorized_workspaces == ("ws_a", "ws_b")
    assert receipt.skipped_workspaces == ()
    assert len(receipt.claimed_run_ids) == 2
    assert page_store.calls[0] == (2, None)


def test_discovery_triggers_all_authorized_workspaces(sync_store: Any) -> None:
    for index in range(3):
        sync_store.save_rule(_rule(f"ws_{index}", f"r_{index}"))
    page_store = PageStore([["ws_0", "ws_1", "ws_2"], []])
    authority = StaticMembershipAuthority({f"ws_{i}": f"prin_{i}" for i in range(3)})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW, page_size=3
        )
    )
    assert receipt.examined_count == 3
    assert receipt.truncated is False
    assert len(receipt.claimed_run_ids) == 3


def test_discovery_max_workspaces_truncates_instead_of_widening(sync_store: Any) -> None:
    for index in range(5):
        sync_store.save_rule(_rule(f"ws_{index:02d}", f"r_{index}"))
    page_store = PageStore([["ws_00", "ws_01", "ws_02", "ws_03", "ws_04"], []])
    authority = StaticMembershipAuthority({f"ws_{i:02d}": f"prin_{i}" for i in range(5)})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW, page_size=5, max_workspaces=3
        )
    )
    assert receipt.examined_count == 3
    assert receipt.truncated is True
    assert len(receipt.discovered_workspaces) == 3
    assert receipt.authorized_workspaces == ("ws_00", "ws_01", "ws_02")
    assert len(receipt.claimed_run_ids) == 3
    assert receipt.next_cursor is not None
    assert receipt.next_cursor.after_workspace_id == "ws_02"


def test_continuation_cursor_prevents_tail_starvation(sync_store: Any) -> None:
    for index in range(5):
        sync_store.save_rule(_rule(f"ws_{index:02d}", f"r_{index}"))
    authority = StaticMembershipAuthority({f"ws_{i:02d}": f"prin_{i}" for i in range(5)})
    page_store = PageStore([
        ["ws_00", "ws_01", "ws_02", "ws_03", "ws_04"],
        ["ws_03", "ws_04"],
        [],
    ])
    engine = _discovery(page_store, authority, _sync_boundary(sync_store))

    first = _run(engine.discover_and_trigger(now=NOW, page_size=5, max_workspaces=3))
    assert first.discovered_workspaces == ("ws_00", "ws_01", "ws_02")
    assert first.authorized_workspaces == ("ws_00", "ws_01", "ws_02")
    assert len(first.claimed_run_ids) == 3
    assert first.next_cursor is not None
    assert first.next_cursor.after_workspace_id == "ws_02"

    second = _run(
        engine.discover_and_trigger(
            now=NOW,
            page_size=5,
            max_workspaces=3,
            continuation=first.next_cursor,
        )
    )
    assert second.discovered_workspaces == ("ws_03", "ws_04")
    assert second.authorized_workspaces == ("ws_03", "ws_04")
    assert len(second.claimed_run_ids) == 2
    assert second.truncated is False
    assert second.next_cursor is None
    assert {r.rule_id for r in sync_store.list_runs("ws_03")} == {"r_3"}
    assert {r.rule_id for r in sync_store.list_runs("ws_04")} == {"r_4"}


def test_discovery_pages_until_exhausted(sync_store: Any) -> None:
    for index in range(4):
        sync_store.save_rule(_rule(f"ws_{index:02d}", f"r_{index}"))
    page_store = PageStore([["ws_00", "ws_01"], ["ws_02", "ws_03"], []])
    authority = StaticMembershipAuthority({f"ws_{i:02d}": f"prin_{i}" for i in range(4)})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW, page_size=2
        )
    )
    assert receipt.discovered_workspaces == ("ws_00", "ws_01", "ws_02", "ws_03")
    assert receipt.pages_read == 3


def test_discovery_stops_on_a_non_advancing_page(sync_store: Any) -> None:
    """A repeated page must not loop forever: the pass ends when it cannot advance."""

    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], ["ws_a"], ["ws_a"]])
    authority = StaticMembershipAuthority({"ws_a": "prin_a"})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW, page_size=1
        )
    )
    assert receipt.discovered_workspaces == ("ws_a",)
    assert receipt.pages_read <= 3


def test_discovery_page_size_and_max_are_validated(sync_store: Any) -> None:
    engine = _discovery(PageStore([]), StaticMembershipAuthority({}), _sync_boundary(sync_store))
    with pytest.raises(DueWorkspaceDiscoveryError):
        _run(engine.discover_and_trigger(now=NOW, page_size=0))
    with pytest.raises(DueWorkspaceDiscoveryError):
        _run(engine.discover_and_trigger(now=NOW, page_size=10**9))
    with pytest.raises(DueWorkspaceDiscoveryError):
        _run(engine.discover_and_trigger(now=NOW, max_workspaces=0))


def test_discovery_rejects_naive_now(sync_store: Any) -> None:
    engine = _discovery(PageStore([]), StaticMembershipAuthority({}), _sync_boundary(sync_store))
    with pytest.raises(DueWorkspaceDiscoveryError):
        _run(engine.discover_and_trigger(now=datetime(2026, 9, 24, 3, 0)))


# --- membership revalidation: skip, never grant, never execute -------------


def test_unresolvable_membership_is_skipped_not_executed(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_orphan", "r_orphan"))
    page_store = PageStore([["ws_orphan"], []])
    receipt = _run(
        _discovery(
            page_store, StaticMembershipAuthority({}), _sync_boundary(sync_store)
        ).discover_and_trigger(now=NOW)
    )
    assert receipt.skipped_workspaces == ("ws_orphan",)
    assert receipt.authorized_workspaces == ()
    assert receipt.claimed_run_ids == ()
    assert sync_store.list_runs("ws_orphan") == []


def test_authority_failure_is_a_skip_never_a_grant(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_err", "r_err"))
    page_store = PageStore([["ws_err"], []])
    receipt = _run(
        _discovery(
            page_store, ExplodingMembershipAuthority(), _sync_boundary(sync_store)
        ).discover_and_trigger(now=NOW)
    )
    assert receipt.authorized_workspaces == ()
    assert receipt.skipped_workspaces == ("ws_err",)
    assert receipt.claimed_run_ids == ()
    assert sync_store.list_runs("ws_err") == []


def test_foreign_membership_projection_is_refused(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], []])
    receipt = _run(
        _discovery(
            page_store, ForeignMembershipAuthority(), _sync_boundary(sync_store)
        ).discover_and_trigger(now=NOW)
    )
    assert receipt.authorized_workspaces == ()
    assert receipt.skipped_workspaces == ("ws_a",)
    assert receipt.claimed_run_ids == ()


def test_lookalike_membership_is_not_authority(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], []])
    receipt = _run(
        _discovery(
            page_store, DictMembershipAuthority(), _sync_boundary(sync_store)
        ).discover_and_trigger(now=NOW)
    )
    assert receipt.authorized_workspaces == ()
    assert receipt.skipped_workspaces == ("ws_a",)


def test_expired_membership_is_skipped(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], []])
    receipt = _run(
        _discovery(
            page_store, ExpiredMembershipAuthority(), _sync_boundary(sync_store)
        ).discover_and_trigger(now=NOW)
    )
    assert receipt.skipped_workspaces == ("ws_a",)
    assert receipt.claimed_run_ids == ()


def test_missing_membership_authority_refuses_the_whole_pass(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    engine = _discovery(PageStore([["ws_a"], []]), None, _sync_boundary(sync_store))
    with pytest.raises(DueWorkspaceDiscoveryError):
        _run(engine.discover_and_trigger(now=NOW))


# --- reuse of the existing tick / dedup / claim path -----------------------


def test_discovery_reuses_existing_tick_dedup_semantics(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], []])
    authority = StaticMembershipAuthority({"ws_a": "prin_a"})
    boundary = _sync_boundary(sync_store)
    engine = _discovery(page_store, authority, boundary)
    first = _run(engine.discover_and_trigger(now=NOW))
    assert len(first.claimed_run_ids) == 1
    second = _run(engine.discover_and_trigger(now=NOW))
    assert second.claimed_run_ids == ()
    assert len(sync_store.list_runs("ws_a")) == 1


def test_discovery_claims_pending_rows_never_running(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], []])
    authority = StaticMembershipAuthority({"ws_a": "prin_a"})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW
        )
    )
    runs = sync_store.list_runs("ws_a")
    assert len(runs) == 1
    assert runs[0].status is ClawScheduledRunStatus.PENDING
    assert runs[0].run_id in receipt.claimed_run_ids
    assert runs[0].output is None


def test_discovery_disabled_rule_never_triggers(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a", enabled=False))
    page_store = PageStore([["ws_a"], []])
    authority = StaticMembershipAuthority({"ws_a": "prin_a"})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW
        )
    )
    # The page source in this test is a stub, so the workspace is still visited;
    # the existing tick must still refuse to materialize a disabled rule.
    assert receipt.claimed_run_ids == ()
    assert sync_store.list_runs("ws_a") == []


def test_discovery_off_boundary_interval_rule_does_not_trigger(sync_store: Any) -> None:
    sync_store.save_rule(
        _rule("ws_a", "r_a", kind=ClawScheduleKind.INTERVAL, expression="1h")
    )
    page_store = PageStore([["ws_a"], []])
    authority = StaticMembershipAuthority({"ws_a": "prin_a"})
    off_boundary = datetime(2026, 9, 24, 3, 30, tzinfo=timezone.utc)
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=off_boundary
        )
    )
    assert receipt.claimed_run_ids == ()
    assert sync_store.list_runs("ws_a") == []


def test_discovery_does_not_enumerate_beyond_max_workspaces(sync_store: Any) -> None:
    page_store = PageStore([[f"ws_{i:02d}" for i in range(100)], []])
    authority = StaticMembershipAuthority({f"ws_{i:02d}": f"p_{i}" for i in range(100)})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW, page_size=100, max_workspaces=10
        )
    )
    assert receipt.examined_count == 10
    assert receipt.truncated is True


def test_canonical_membership_composition_reuses_rule_subject_and_role(sync_store: Any) -> None:
    subject_b = "sub_ffffffffffffffffffffffffffffffff"
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_canonical"),
            canonical_subject_id=CANONICAL_SUBJECT,
        )
    )
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_second"),
            canonical_subject_id=subject_b,
        )
    )
    authority = CanonicalSessionlessAuthority(
        memberships={
            CANONICAL_SUBJECT: _canonical_membership(),
            subject_b: _canonical_membership(subject_id=subject_b),
        }
    )
    membership = CanonicalAutomationMembershipAuthority(
        rule_store=sync_store,
        control_plane_identity_authority=authority,
    )

    projections = _run(
        membership.resolve_workspace_memberships(
            workspace_id=CANONICAL_TENANT, now=NOW
        )
    )

    assert {projection.principal_ref for projection in projections} == {
        CANONICAL_SUBJECT,
        subject_b,
    }
    assert all(projection.role is WorkspaceRole.OPERATOR for projection in projections)
    assert {call["canonical_subject_id"] for call in authority.calls} == {
        CANONICAL_SUBJECT,
        subject_b,
    }

    composed_store = ComposedStore([[CANONICAL_TENANT], []], sync_store)
    engine = compose_canonical_due_workspace_discovery(
        automation_store=composed_store,
        control_plane_identity_authority=authority,
        trigger_boundary=_sync_boundary(composed_store),
    )
    receipt = _run(engine.discover_and_trigger(now=NOW))
    assert receipt.authorized_workspaces == (CANONICAL_TENANT,)
    assert len(receipt.claimed_run_ids) == 2


def test_tick_runs_each_canonical_subject_independently_and_quarantines_legacy(
    sync_store: Any,
) -> None:
    subject_b = "sub_ffffffffffffffffffffffffffffffff"
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_subject_a"),
            canonical_subject_id=CANONICAL_SUBJECT,
        )
    )
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_subject_b"),
            canonical_subject_id=subject_b,
        )
    )
    sync_store.save_rule(_rule(CANONICAL_TENANT, "r_legacy"))
    trigger = ClawAutomationTrigger(
        trigger_id="trigger_subject_split",
        correlation_id="corr_subject_split",
        workspace_id=CANONICAL_TENANT,
        observed_at=NOW,
        membership=None,
        memberships=(
            _membership_projection(CANONICAL_SUBJECT),
            _membership_projection(subject_b),
        ),
    )

    receipt = ClawAutomationTriggerBoundary(
        ClawAutomationTickRuntime(sync_store)
    ).handle(trigger)

    assert len(receipt.created_run_ids) == 2
    assert not any(
        run.rule_id == "r_legacy" for run in sync_store.list_runs(CANONICAL_TENANT)
    )


def test_revoked_subject_is_skipped_without_blocking_other_subject(
    sync_store: Any,
) -> None:
    subject_b = "sub_ffffffffffffffffffffffffffffffff"
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_revoked_subject"),
            canonical_subject_id=CANONICAL_SUBJECT,
        )
    )
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_active_subject"),
            canonical_subject_id=subject_b,
        )
    )
    trigger = ClawAutomationTrigger(
        trigger_id="trigger_revoked_subject",
        correlation_id="corr_revoked_subject",
        workspace_id=CANONICAL_TENANT,
        observed_at=NOW,
        membership=None,
        memberships=(
            _membership_projection(
                CANONICAL_SUBJECT,
                issued_at=NOW - timedelta(hours=2),
                expires_at=NOW - timedelta(hours=1),
            ),
            _membership_projection(subject_b),
        ),
    )

    receipt = ClawAutomationTriggerBoundary(
        ClawAutomationTickRuntime(sync_store)
    ).handle(trigger)

    assert len(receipt.created_run_ids) == 1
    assert {run.rule_id for run in sync_store.list_runs(CANONICAL_TENANT)} == {
        "r_active_subject"
    }


def test_membership_cannot_authorize_a_different_canonical_subject(
    sync_store: Any,
) -> None:
    subject_b = "sub_ffffffffffffffffffffffffffffffff"
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_subject_a_only"),
            canonical_subject_id=CANONICAL_SUBJECT,
        )
    )
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_subject_b_only"),
            canonical_subject_id=subject_b,
        )
    )
    trigger = ClawAutomationTrigger(
        trigger_id="trigger_subject_mismatch",
        correlation_id="corr_subject_mismatch",
        workspace_id=CANONICAL_TENANT,
        observed_at=NOW,
        membership=_membership_projection(CANONICAL_SUBJECT),
    )

    receipt = ClawAutomationTriggerBoundary(
        ClawAutomationTickRuntime(sync_store)
    ).handle(trigger)

    assert len(receipt.created_run_ids) == 1
    assert {run.rule_id for run in sync_store.list_runs(CANONICAL_TENANT)} == {
        "r_subject_a_only"
    }


def test_canonical_membership_composition_fails_closed_for_ambiguous_or_legacy_rules(
    sync_store: Any,
) -> None:
    authority = CanonicalSessionlessAuthority(
        memberships={
            CANONICAL_SUBJECT: _canonical_membership(),
            "sub_ffffffffffffffffffffffffffffffff": _canonical_membership(
                subject_id="sub_ffffffffffffffffffffffffffffffff"
            ),
        }
    )
    membership = CanonicalAutomationMembershipAuthority(
        rule_store=sync_store,
        control_plane_identity_authority=authority,
    )
    sync_store.save_rule(_rule(CANONICAL_TENANT, "r_legacy"))
    assert _run(
        membership.resolve_workspace_memberships(
            workspace_id=CANONICAL_TENANT, now=NOW
        )
    ) == ()

    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_canonical"),
            canonical_subject_id=CANONICAL_SUBJECT,
        )
    )
    projections = _run(
        membership.resolve_workspace_memberships(
            workspace_id=CANONICAL_TENANT, now=NOW
        )
    )
    assert len(projections) == 1
    assert projections[0].principal_ref == CANONICAL_SUBJECT

    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_second_subject"),
            canonical_subject_id="sub_ffffffffffffffffffffffffffffffff",
        )
    )
    projections = _run(
        membership.resolve_workspace_memberships(
            workspace_id=CANONICAL_TENANT, now=NOW
        )
    )
    assert {projection.principal_ref for projection in projections} == {
        CANONICAL_SUBJECT,
        "sub_ffffffffffffffffffffffffffffffff",
    }


def test_canonical_membership_composition_rejects_missing_role_and_inactive_state(
    sync_store: Any,
) -> None:
    sync_store.save_rule(
        replace(
            _rule(CANONICAL_TENANT, "r_canonical"),
            canonical_subject_id=CANONICAL_SUBJECT,
        )
    )
    for membership in (
        _canonical_membership(role=None),
        _canonical_membership(state=TenantMembershipState.INACTIVE),
    ):
        authority = CanonicalSessionlessAuthority(membership)
        projection = CanonicalAutomationMembershipAuthority(
            rule_store=sync_store,
            control_plane_identity_authority=authority,
        )
        assert _run(
            projection.resolve_workspace_membership(
                workspace_id=CANONICAL_TENANT, now=NOW
            )
        ) is None


# ===========================================================================
# refused surfaces and refusal flags
# ===========================================================================


def test_module_refusal_flags_are_all_false() -> None:
    assert discovery_mod.CALLER_LIST_ALL_WORKSPACES is False
    assert discovery_mod.CALLER_SUPPLIED_TENANT_SCAN is False
    assert discovery_mod.SECOND_SCHEDULER_AUTHORITY is False
    assert discovery_mod.SECOND_RULE_AUTHORITY is False
    assert discovery_mod.SECOND_RUN_ID_AUTHORITY is False
    assert discovery_mod.SECOND_DEDUP_AUTHORITY is False
    assert discovery_mod.SYNTHETIC_MEMBERSHIP is False
    assert discovery_mod.WORKER_SCHEDULED_HANDLER is True
    assert discovery_mod.CRON_SOURCE_DECLARATION is False
    assert discovery_mod.BACKGROUND_SCHEDULER_SOURCE_READY is True
    assert discovery_mod.REAL_CLOUD_CRON_REGISTRATION is False
    assert discovery_mod.PRODUCTION_SCHEDULER_ACTIVATION is False
    assert discovery_mod.WORKFLOW_DISPATCH is False
    assert discovery_mod.PRODUCTION_MUTATION is False
    assert discovery_mod.PROVIDER_CALLS == 0
    assert discovery_mod.EXTERNAL_SEND == 0
    assert discovery_mod.DISABLED_RULE_DISCOVERY == 0
    assert discovery_mod.SERVER_OWNED_DUE_WORKSPACE_DISCOVERY is True


def test_store_module_keeps_caller_enumeration_refused() -> None:
    assert store_mod.CALLER_LIST_ALL_WORKSPACES is False
    assert store_mod.CALLER_LIST_ALL_RULES_ACROSS_TENANTS is False
    assert store_mod.SERVER_OWNED_DUE_WORKSPACE_DISCOVERY_READ is True
    assert store_mod.CALLER_SUPPLIED_WORKSPACE_FILTER is False


def test_discovery_takes_no_caller_workspace_argument() -> None:
    import inspect as _inspect

    signature = _inspect.signature(ClawAutomationDueWorkspaceDiscovery.discover_and_trigger)
    assert "workspace_id" not in signature.parameters
    assert "tenant" not in signature.parameters
    assert "owner_ref" not in signature.parameters
    assert "after_workspace_id" not in signature.parameters
    assert "continuation" in signature.parameters


def test_discovery_receipt_safe_dict_pins_refusals(sync_store: Any) -> None:
    sync_store.save_rule(_rule("ws_a", "r_a"))
    page_store = PageStore([["ws_a"], []])
    authority = StaticMembershipAuthority({"ws_a": "prin_a"})
    receipt = _run(
        _discovery(page_store, authority, _sync_boundary(sync_store)).discover_and_trigger(
            now=NOW
        )
    )
    payload = receipt.safe_dict()
    assert payload["caller_supplied_workspace"] is False
    assert payload["tenant_wide_enumeration_exposed"] is False
    assert payload["synthetic_membership"] is False
    assert payload["worker_scheduled_handler"] is True
    assert payload["cron_source_declaration"] is False
    assert payload["background_scheduler_source_ready"] is True
    assert payload["production_scheduler_activation"] is False
    assert payload["provider_calls"] == 0
    assert payload["external_sends"] == 0
    assert payload["production_mutation"] == 0
    assert payload["continuation_available"] is False
    # No rule body, run output or proposal text leaks into the receipt.
    assert "rule " not in repr(payload)


def test_discovery_engine_safe_dict_pins_refusals(sync_store: Any) -> None:
    engine = _discovery(PageStore([]), StaticMembershipAuthority({}), _sync_boundary(sync_store))
    payload = engine.safe_dict()
    assert payload["server_owned_due_workspace_discovery"] is True
    assert payload["bounded_scan"] is True
    assert payload["deterministic_order"] is True
    assert payload["membership_revalidation"] is True
    assert payload["caller_list_all_workspaces"] is False
    assert payload["second_scheduler_authority"] is False
    assert payload["worker_scheduled_handler"] is True
    assert payload["cron_source_declaration"] is False
    assert payload["background_scheduler_source_ready"] is True


def test_boundary_refuses_a_non_trigger_boundary(sync_store: Any) -> None:
    with pytest.raises(DueWorkspaceDiscoveryError):
        ClawAutomationDueWorkspaceDiscovery(
            store=PageStore([]),
            membership_authority=StaticMembershipAuthority({}),
            trigger_boundary=object(),  # type: ignore[arg-type]
        )


def test_boundary_refuses_a_store_without_the_bounded_page() -> None:
    """A page source that cannot answer the bounded page read is refused."""

    class NoPageStore:
        """A store the existing tick accepts, but that exposes no bounded page."""

        def list_rules(self, workspace_id: str) -> list[Any]:
            return []

        def get_run_for_occurrence(self, key: str, workspace_id: str) -> Any:
            return None

        def record_run(self, run: Any) -> Any:
            return run

    boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(NoPageStore()))
    with pytest.raises(DueWorkspaceDiscoveryError):
        ClawAutomationDueWorkspaceDiscovery(
            store=NoPageStore(),
            membership_authority=StaticMembershipAuthority({}),
            trigger_boundary=boundary,
        )


def test_empty_page_produces_an_empty_receipt(sync_store: Any) -> None:
    receipt = _run(
        _discovery(
            PageStore([[]]), StaticMembershipAuthority({}), _sync_boundary(sync_store)
        ).discover_and_trigger(now=NOW)
    )
    assert receipt.discovered_workspaces == ()
    assert receipt.pages_read >= 1
    assert receipt.truncated is False


def test_discovery_module_registers_cron_source_and_scheduled_handler() -> None:
    worker_source = (_CHAT / "worker.py").read_text(encoding="utf-8")
    wrangler_source = (_CHAT / "wrangler.toml").read_text(encoding="utf-8")
    discovery_source = (
        _CHAT / "app" / "claw_automation_due_workspace_discovery.py"
    ).read_text(encoding="utf-8")
    assert "async def scheduled" in worker_source
    assert "run_scheduled_automation_source" in worker_source
    assert "[triggers]" not in wrangler_source
    assert "crons" not in wrangler_source.lower()
    assert 'PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED = "false"' in wrangler_source
    assert "WORKER_SCHEDULED_HANDLER = True" in discovery_source
    assert "CRON_SOURCE_DECLARATION = False" in discovery_source
    assert "BACKGROUND_SCHEDULER_SOURCE_READY = True" in discovery_source
    assert "REAL_CLOUD_CRON_REGISTRATION = False" in discovery_source


def test_async_store_is_documented_as_out_of_scope_for_the_trigger_step() -> None:
    """The synchronous tick contract is pinned, not silently papered over."""

    source = (
        _CHAT / "app" / "claw_automation_due_workspace_discovery.py"
    ).read_text(encoding="utf-8")
    assert "SYNCHRONOUS store" in source
    assert "not something this slice may" in source
