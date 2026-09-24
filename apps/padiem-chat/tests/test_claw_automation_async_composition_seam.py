"""#2995 S2F6C — Worker-safe async trigger/execution composition seam proofs.

NETWORK_FREE: no Worker handler, no cron registration, no Worker config change,
no provider call, no external send, no connector write, no Production mutation.
The chain is driven end to end against the REAL ``D1ClawAutomationStore`` on a
D1-interface SQLite double (async statements only), the REAL discovery boundary,
the REAL trusted trigger boundary through ``ahandle()``/``atick()`` and the REAL
background execution composition -- proving the async seam itself, not a stub.

Also pins this child's decision-gate outcome:
``WORKER_SCHEDULED_HANDLER_SOURCE=NOT_JUSTIFIED`` -- ``worker.py`` exposes no
``scheduled()`` handler, the Worker config declares no cron trigger, and the
discovery module keeps ``WORKER_SCHEDULED_HANDLER = False``, because no
existing Worker membership authority can feed #2987 discovery.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve()
_CHAT = _HERE.parent.parent
_REPO = _CHAT.parent.parent
_KAGENT_SRC = _REPO / "apps" / "korean-ai-code-agent" / "src"

# Prefer the kernel SOURCE tree when present (same policy the #2987 test uses):
# a stale installed copy would silently exercise a different authority than the
# one under test. PREFERENCE only, never an assertion, so CI that resolves
# kagent from an installed distribution still collects.
if (_KAGENT_SRC / "kagent" / "__init__.py").exists():
    sys.path.insert(0, str(_KAGENT_SRC))

from kagent.claw_automation import (  # noqa: E402
    ClawAutomationTickRuntime,
    ClawScheduledRunStatus,
)
from kagent.claw_automation_trigger import (  # noqa: E402
    ClawAutomationTrigger,
    ClawAutomationTriggerBoundary,
)

from app.claw_automation_background_execution import (  # noqa: E402
    BackgroundExecutionCompositionError,
    compose_background_execution,
)
from app.claw_automation_due_workspace_discovery import (  # noqa: E402
    ClawAutomationDueWorkspaceDiscovery,
    DueWorkspaceDiscoveryError,
)
from app.claw_automation_store import D1ClawAutomationStore  # noqa: E402

# Sibling contract modules reuse their proven doubles so the seam is tested
# against the SAME fixtures the sync contracts pin, not a drifted copy.
from test_claw_automation_background_execution import (  # noqa: E402
    NOW,
    WORKSPACE,
    OutcomeAdapter,
    RecordingHistoryStore,
    RecordingTaskAlertStore,
    make_rule,
    membership,
    resolver,
)
from test_claw_automation_due_workspace_discovery import (  # noqa: E402
    MIGRATION_019_PATH,
    MIGRATION_PATH,
    DictMembershipAuthority,
    ExplodingMembershipAuthority,
    SqliteD1Binding,
    StaticMembershipAuthority,
    _rule,
)

OTHER_WORKSPACE = "workspace_b"
WS_ONE = "ws_one"
WS_TWO = "ws_two"
WS_THREE = "ws_three"
WS_FOUR = "ws_four"


# ---------------------------------------------------------------------------
# D1-interface double + fixtures (same shape the #2983/#2987 tests use)
# ---------------------------------------------------------------------------


@pytest.fixture
def d1_db() -> SqliteD1Binding:
    binding = SqliteD1Binding()
    for path in (MIGRATION_PATH, MIGRATION_019_PATH):
        binding.conn.executescript(path.read_text(encoding="utf-8"))
    return binding


@pytest.fixture
def d1_store(d1_db: SqliteD1Binding) -> D1ClawAutomationStore:
    return D1ClawAutomationStore(d1_db)


def _discovery(store: Any, authority: Any, boundary: ClawAutomationTriggerBoundary):
    return ClawAutomationDueWorkspaceDiscovery(
        store=store,
        membership_authority=authority,
        trigger_boundary=boundary,
    )


def _async_boundary(store: Any) -> ClawAutomationTriggerBoundary:
    return ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))


def _authority(*workspaces: str) -> StaticMembershipAuthority:
    return StaticMembershipAuthority({ws: "principal:user" for ws in workspaces})


async def _compose(trigger, *, boundary, store, adapter, receipt, **kwargs):
    history = RecordingHistoryStore()
    task_alert = RecordingTaskAlertStore()
    bg = await compose_background_execution(
        trigger=trigger,
        boundary=boundary,
        store=store,
        adapter=adapter,
        owner_resolver=resolver(),
        history_store=history,
        task_alert_store=task_alert,
        completed_at=NOW,
        trigger_receipt=receipt,
        **kwargs,
    )
    return bg, history, task_alert


def _trigger_from(receipt, authority) -> ClawAutomationTrigger:
    return ClawAutomationTrigger(
        trigger_id=receipt.trigger_id,
        correlation_id=receipt.correlation_id,
        workspace_id=receipt.workspace_id,
        observed_at=NOW,
        membership=authority.resolve_workspace_membership(
            workspace_id=WORKSPACE, now=NOW
        ),
    )


# ---------------------------------------------------------------------------
# 1. async D1 end to end: discovery -> ahandle/atick -> composed execution
# ---------------------------------------------------------------------------


async def test_async_d1_end_to_end_claim_execute_and_project(d1_store):
    await d1_store.save_rule(make_rule())
    authority = _authority(WORKSPACE)
    boundary = _async_boundary(d1_store)
    engine = _discovery(d1_store, authority, boundary)

    disc = await engine.aadiscover_and_trigger(now=NOW)

    assert disc.discovered_workspaces == (WORKSPACE,)
    assert disc.authorized_workspaces == (WORKSPACE,)
    assert len(disc.triggered_receipts) == 1
    trigger_receipt = disc.triggered_receipts[0]
    assert trigger_receipt.created_run_ids
    assert disc.claimed_run_ids == trigger_receipt.created_run_ids
    # One observed instant per invocation, everywhere in the pass.
    assert {r.observed_at for r in disc.triggered_receipts} == {NOW}
    rows = await d1_store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.PENDING]

    # Compose execution with the PRECOMPUTED receipt: no second claim, no
    # re-run of the trigger, execution through the existing chain only.
    adapter = OutcomeAdapter()
    bg, history, task_alert = await _compose(
        _trigger_from(trigger_receipt, authority),
        boundary=boundary,
        store=d1_store,
        adapter=adapter,
        receipt=trigger_receipt,
    )

    assert bg.trigger_receipt_precomputed is True
    assert bg.newly_claimed_run_ids == trigger_receipt.created_run_ids
    run_id = trigger_receipt.created_run_ids[0]
    assert bg.execution_claimed_run_ids == (run_id,)
    assert bg.terminal_run_ids == (run_id,)
    assert len(adapter.calls) == 1
    assert history.rows  # CLAW_RUN_HISTORY_PROJECTION=YES
    assert task_alert.add_task_calls + task_alert.add_alert_calls >= 1  # TASK_ALERT_OUTPUT=YES
    rows = await d1_store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.COMPLETED]


async def test_precomputed_receipt_skips_the_synchronous_trigger(d1_store):
    await d1_store.save_rule(make_rule())
    authority = _authority(WORKSPACE)

    class _NoSyncHandle(ClawAutomationTriggerBoundary):
        def handle(self, trigger):  # pragma: no cover - must never run
            raise AssertionError("the trigger must not be re-run")

    runtime = ClawAutomationTickRuntime(d1_store)
    fail_boundary = _NoSyncHandle(runtime)
    # The receipt itself is produced through the async shape (ahandle)...
    engine = _discovery(d1_store, authority, _async_boundary(d1_store))
    disc = await engine.aadiscover_and_trigger(now=NOW)
    trigger_receipt = disc.triggered_receipts[0]

    # ...and composing with it never touches the synchronous dispatch.
    adapter = OutcomeAdapter()
    bg, _, _ = await _compose(
        _trigger_from(trigger_receipt, authority),
        boundary=fail_boundary,
        store=d1_store,
        adapter=adapter,
        receipt=trigger_receipt,
    )
    assert bg.trigger_receipt_precomputed is True
    assert len(adapter.calls) == 1

    # Default shape (no receipt) still re-runs the trigger, unchanged.
    with pytest.raises(AssertionError):
        await compose_background_execution(
            trigger=_trigger_from(trigger_receipt, authority),
            boundary=fail_boundary,
            store=d1_store,
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=RecordingHistoryStore(),
            task_alert_store=RecordingTaskAlertStore(),
            completed_at=NOW,
        )


async def test_precomputed_receipt_mismatch_fails_closed(d1_store):
    await d1_store.save_rule(make_rule())
    authority = _authority(WORKSPACE)
    boundary = _async_boundary(d1_store)
    engine = _discovery(d1_store, authority, boundary)
    disc = await engine.aadiscover_and_trigger(now=NOW)
    trigger_receipt = disc.triggered_receipts[0]

    adapter = OutcomeAdapter()
    foreign_instant = ClawAutomationTrigger(
        trigger_id=trigger_receipt.trigger_id,
        correlation_id=trigger_receipt.correlation_id,
        workspace_id=WORKSPACE,
        observed_at=NOW.replace(minute=1),
        membership=authority.resolve_workspace_membership(
            workspace_id=WORKSPACE, now=NOW
        ),
    )
    with pytest.raises(BackgroundExecutionCompositionError):
        await compose_background_execution(
            trigger=foreign_instant,
            boundary=boundary,
            store=d1_store,
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=RecordingHistoryStore(),
            task_alert_store=RecordingTaskAlertStore(),
            completed_at=NOW,
            trigger_receipt=trigger_receipt,
        )
    assert adapter.calls == []
    # The mismatched receipt claimed nothing: the row from the real pass is
    # still exactly where that pass left it, untouched.
    rows = await d1_store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.PENDING]

    foreign_source = ClawAutomationTrigger(
        trigger_id="trigger:other_source",
        correlation_id=trigger_receipt.correlation_id,
        workspace_id=WORKSPACE,
        observed_at=NOW,
        membership=authority.resolve_workspace_membership(
            workspace_id=WORKSPACE, now=NOW
        ),
    )
    with pytest.raises(BackgroundExecutionCompositionError):
        await compose_background_execution(
            trigger=foreign_source,
            boundary=boundary,
            store=d1_store,
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=RecordingHistoryStore(),
            task_alert_store=RecordingTaskAlertStore(),
            completed_at=NOW,
            trigger_receipt=trigger_receipt,
        )
    assert adapter.calls == []

    foreign_correlation = ClawAutomationTrigger(
        trigger_id=trigger_receipt.trigger_id,
        correlation_id="corr:other_delivery",
        workspace_id=WORKSPACE,
        observed_at=NOW,
        membership=authority.resolve_workspace_membership(
            workspace_id=WORKSPACE, now=NOW
        ),
    )
    with pytest.raises(BackgroundExecutionCompositionError):
        await compose_background_execution(
            trigger=foreign_correlation,
            boundary=boundary,
            store=d1_store,
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=RecordingHistoryStore(),
            task_alert_store=RecordingTaskAlertStore(),
            completed_at=NOW,
            trigger_receipt=trigger_receipt,
        )
    assert adapter.calls == []

    inactive_membership = ClawAutomationTrigger(
        trigger_id=trigger_receipt.trigger_id,
        correlation_id=trigger_receipt.correlation_id,
        workspace_id=WORKSPACE,
        observed_at=NOW,
        membership=membership(
            at=NOW,
            issued_offset_hours=-3,
            expires_offset_hours=-2,
        ),
    )
    with pytest.raises(BackgroundExecutionCompositionError):
        await compose_background_execution(
            trigger=inactive_membership,
            boundary=boundary,
            store=d1_store,
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=RecordingHistoryStore(),
            task_alert_store=RecordingTaskAlertStore(),
            completed_at=NOW,
            trigger_receipt=trigger_receipt,
        )
    assert adapter.calls == []

    rows = await d1_store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.PENDING]


async def test_retry_of_the_same_invocation_executes_exactly_once(d1_store):
    await d1_store.save_rule(make_rule())
    authority = _authority(WORKSPACE)
    boundary = _async_boundary(d1_store)
    engine = _discovery(d1_store, authority, boundary)
    disc = await engine.aadiscover_and_trigger(now=NOW)
    trigger_receipt = disc.triggered_receipts[0]
    trigger = _trigger_from(trigger_receipt, authority)

    adapter = OutcomeAdapter()
    first, history, _ = await _compose(
        trigger, boundary=boundary, store=d1_store, adapter=adapter,
        receipt=trigger_receipt,
    )
    assert len(adapter.calls) == 1

    # RETRY_DUPLICATE_EXECUTION=0: same receipt, same instant, second compose.
    second, history2, _ = await _compose(
        trigger, boundary=boundary, store=d1_store, adapter=adapter,
        receipt=trigger_receipt,
    )
    assert len(adapter.calls) == 1
    assert second.execution_claimed_run_ids == ()
    assert set(second.projection_only_run_ids) == set(first.terminal_run_ids)
    assert set(second.running_unresolved_run_ids) == set()
    # History stays one canonical row per (user, run): the projection authority
    # owns idempotency, and the second pass never re-executed P01.
    assert len(history.rows) == 1
    assert len(history2.rows) == 1
    rows = await d1_store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.COMPLETED]


# ---------------------------------------------------------------------------
# 2. bounded continuation across the workspace page bound (async store)
# ---------------------------------------------------------------------------


async def test_continuation_across_workspace_page_bound(d1_store):
    for index, ws in enumerate((WS_ONE, WS_TWO, WS_THREE, WS_FOUR), start=1):
        await d1_store.save_rule(_rule(ws, f"rule_cont_{index}"))
    authority = _authority(WS_ONE, WS_TWO, WS_THREE, WS_FOUR)
    engine = _discovery(d1_store, authority, _async_boundary(d1_store))

    first = await engine.aadiscover_and_trigger(now=NOW, page_size=2, max_workspaces=3)
    assert first.truncated is True
    assert first.next_cursor is not None
    assert len(first.discovered_workspaces) == 3
    assert first.examined_count == 3

    second = await engine.aadiscover_and_trigger(
        now=NOW,
        page_size=2,
        max_workspaces=3,
        continuation=first.next_cursor,
    )
    assert second.truncated is False
    assert second.next_cursor is None
    # The deterministic tail is reached: union of both passes covers all four.
    assert set(first.discovered_workspaces) | set(second.discovered_workspaces) == {
        WS_ONE,
        WS_TWO,
        WS_THREE,
        WS_FOUR,
    }
    # Each workspace's due occurrence was claimed exactly once across passes.
    for ws in (WS_ONE, WS_TWO, WS_THREE, WS_FOUR):
        rows = await d1_store.list_runs(ws)
        assert len(rows) == 1
        assert rows[0].status is ClawScheduledRunStatus.PENDING
    assert {r.observed_at for r in first.triggered_receipts + second.triggered_receipts} == {NOW}


# ---------------------------------------------------------------------------
# 3. membership: zero synthetic grants, skip never executes, absent fails closed
# ---------------------------------------------------------------------------


async def test_absent_membership_authority_fails_the_pass_closed(d1_store):
    await d1_store.save_rule(make_rule())
    engine = ClawAutomationDueWorkspaceDiscovery(
        store=d1_store,
        membership_authority=None,
        trigger_boundary=_async_boundary(d1_store),
    )
    with pytest.raises(DueWorkspaceDiscoveryError):
        await engine.aadiscover_and_trigger(now=NOW)
    assert await d1_store.list_runs(WORKSPACE) == []


async def test_unprovable_membership_is_skipped_never_executed(d1_store):
    await d1_store.save_rule(make_rule())
    # Authority proves NOTHING for this workspace: skip, never grant.
    engine = _discovery(d1_store, StaticMembershipAuthority({}), _async_boundary(d1_store))
    disc = await engine.aadiscover_and_trigger(now=NOW)
    assert disc.discovered_workspaces == (WORKSPACE,)
    assert disc.authorized_workspaces == ()
    assert disc.skipped_workspaces == (WORKSPACE,)
    assert disc.triggered_receipts == ()
    assert await d1_store.list_runs(WORKSPACE) == []


async def test_lookalike_membership_is_never_synthesized(d1_store):
    await d1_store.save_rule(make_rule())
    engine = _discovery(
        d1_store, DictMembershipAuthority(), _async_boundary(d1_store)
    )
    disc = await engine.aadiscover_and_trigger(now=NOW)
    assert disc.authorized_workspaces == ()
    assert disc.safe_dict()["synthetic_membership"] is False
    assert await d1_store.list_runs(WORKSPACE) == []


async def test_exploding_membership_authority_skips_instead_of_granting(d1_store):
    await d1_store.save_rule(make_rule())
    engine = _discovery(
        d1_store, ExplodingMembershipAuthority(), _async_boundary(d1_store)
    )
    disc = await engine.aadiscover_and_trigger(now=NOW)
    assert disc.skipped_workspaces == (WORKSPACE,)
    assert await d1_store.list_runs(WORKSPACE) == []


# ---------------------------------------------------------------------------
# 4. disabled / non-due rules never execute on the async path
# ---------------------------------------------------------------------------


async def test_disabled_only_workspace_is_never_discovered(d1_store):
    await d1_store.save_rule(_rule(WORKSPACE, "rule_disabled", enabled=False))
    engine = _discovery(d1_store, _authority(WORKSPACE), _async_boundary(d1_store))
    disc = await engine.aadiscover_and_trigger(now=NOW)
    assert disc.discovered_workspaces == ()
    assert disc.examined_count == 0
    assert disc.triggered_receipts == ()
    assert await d1_store.list_runs(WORKSPACE) == []


async def test_enabled_but_non_due_rule_claims_nothing(d1_store):
    await d1_store.save_rule(
        _rule(WORKSPACE, "rule_not_due", expression="30 8 * * *")
    )
    engine = _discovery(d1_store, _authority(WORKSPACE), _async_boundary(d1_store))
    disc = await engine.aadiscover_and_trigger(now=NOW)
    assert disc.authorized_workspaces == (WORKSPACE,)
    assert disc.triggered_receipts[0].created_run_ids == ()
    assert disc.claimed_run_ids == ()
    assert await d1_store.list_runs(WORKSPACE) == []


# ---------------------------------------------------------------------------
# 5. missing D1 fails closed with no partial claim
# ---------------------------------------------------------------------------


class _ExplodingAsyncPageStore:
    async def list_candidate_workspace_page(
        self, *, page_size: int, after_workspace_id: str | None = None
    ):
        raise RuntimeError("d1 unavailable")


async def test_missing_d1_fails_closed_before_any_claim(d1_store):
    boundary = _async_boundary(d1_store)
    engine = _discovery(
        _ExplodingAsyncPageStore(), _authority(WORKSPACE), boundary
    )
    with pytest.raises(RuntimeError):
        await engine.aadiscover_and_trigger(now=NOW)
    assert await d1_store.list_runs(WORKSPACE) == []


# ---------------------------------------------------------------------------
# 6. receipts pin every side effect shut
# ---------------------------------------------------------------------------


async def test_receipts_pin_no_external_side_effect(d1_store):
    await d1_store.save_rule(make_rule())
    authority = _authority(WORKSPACE)
    boundary = _async_boundary(d1_store)
    engine = _discovery(d1_store, authority, boundary)
    disc = await engine.aadiscover_and_trigger(now=NOW)
    trigger_receipt = disc.triggered_receipts[0]
    adapter = OutcomeAdapter()
    bg, _, _ = await _compose(
        _trigger_from(trigger_receipt, authority),
        boundary=boundary,
        store=d1_store,
        adapter=adapter,
        receipt=trigger_receipt,
    )

    trigger_payload = trigger_receipt.safe_dict()
    for marker in (
        "provider_calls",
        "external_sends",
        "connector_writes",
        "canonical_dispatches",
        "sandbox_allocations",
        "catch_up_occurrences",
    ):
        assert trigger_payload[marker] == 0, marker
    assert trigger_payload["production_scheduler"] is False

    discovery_payload = disc.safe_dict()
    for marker in (
        "provider_calls",
        "external_sends",
        "production_mutation",
        "synthetic_membership",
        "worker_scheduled_handler",
        "production_scheduler_activation",
    ):
        expected = False if marker in {
            "synthetic_membership",
            "worker_scheduled_handler",
            "production_scheduler_activation",
        } else 0
        assert discovery_payload[marker] is expected, marker

    bg_payload = bg.safe_dict()
    for marker in (
        "provider_calls",
        "external_sends",
        "connector_writes",
        "real_sandbox_allocations",
        "second_scheduler_authority",
        "second_run_id",
        "second_dedup_authority",
        "second_owner_authority",
        "second_p01_authority",
        "second_history_store",
        "second_session_authority",
        "second_task_alert_authority",
        "production_scheduler_activation",
        "production_mutation",
    ):
        assert bg_payload[marker] == 0, marker
    assert bg_payload["trigger_receipt_precomputed"] is True
    for marker in ("secret", "credential", "api_key"):
        assert marker not in repr(bg_payload)


# ---------------------------------------------------------------------------
# 7. decision gate: WORKER_SCHEDULED_HANDLER_SOURCE=NOT_JUSTIFIED is pinned
# ---------------------------------------------------------------------------


def test_worker_handler_and_cron_remain_absent_in_source():
    worker_source = (_CHAT / "worker.py").read_text(encoding="utf-8")
    assert "def scheduled" not in worker_source

    wrangler_source = (_CHAT / "wrangler.toml").read_text(encoding="utf-8")
    assert "[triggers]" not in wrangler_source
    assert "cron" not in wrangler_source.lower()

    discovery_source = (
        _CHAT / "app" / "claw_automation_due_workspace_discovery.py"
    ).read_text(encoding="utf-8")
    assert "WORKER_SCHEDULED_HANDLER = False" in discovery_source
    assert "REAL_CLOUD_CRON_REGISTRATION = False" in discovery_source
