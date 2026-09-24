"""#2995 S2F6C — Worker-safe async trigger/execution composition seam proofs.

NETWORK_FREE: no provider call, no external send, no connector write, no
Production mutation, and no live Worker cron registration.
The chain is driven end to end against the REAL ``D1ClawAutomationStore`` on a
D1-interface SQLite double (async statements only), the REAL discovery boundary,
the REAL trusted trigger boundary through ``ahandle()``/``atick()`` and the REAL
background execution composition -- proving the async seam itself, not a stub.

Also pins this child's decision-gate outcome:
``WORKER_SCHEDULED_HANDLER_SOURCE=READY_GATED`` -- the canonical sessionless
membership composition feeds #2987/#2995, ``worker.py`` exposes a gated
``scheduled()`` handler, and the live Worker config declares no Cron trigger.
"""

from __future__ import annotations

import sys
from datetime import timedelta
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
from app.claw_automation_scheduled_execution import (  # noqa: E402
    compose_scheduled_automation_execution,
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
    _membership_projection,
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
    return StaticMembershipAuthority(
        {
            ws: (
                membership(workspace_id=ws).principal_ref
                if ws.startswith("tenant_")
                else "principal:user"
            )
            for ws in workspaces
        }
    )


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


async def test_scheduled_execution_composition_runs_full_existing_path(d1_store):
    await d1_store.save_rule(make_rule())
    authority = _authority(WORKSPACE)
    boundary = _async_boundary(d1_store)
    discovery = _discovery(d1_store, authority, boundary)
    history = RecordingHistoryStore()
    task_alert = RecordingTaskAlertStore()

    receipt = await compose_scheduled_automation_execution(
        discovery=discovery,
        boundary=boundary,
        store=d1_store,
        adapter=OutcomeAdapter(),
        owner_resolver=resolver(),
        history_store=history,
        task_alert_store=task_alert,
        now=NOW,
        completed_at=NOW,
    )

    assert len(receipt.executions) == 1
    assert receipt.executions[0].terminal_run_ids
    assert history.rows
    assert task_alert.add_task_calls + task_alert.add_alert_calls >= 1
    payload = receipt.safe_dict()
    assert payload["downstream_side_effects_observed"] is False
    assert payload["production_config_mutation"] == 0
    assert payload["production_migration_mutation"] == 0
    assert payload["workflow_dispatch"] == 0
    for unobserved in (
        "provider_calls",
        "external_send",
        "external_write",
        "connector_write",
        "production_mutation",
        "production_d1_mutation",
    ):
        assert unobserved not in payload


async def test_async_tick_isolates_subjects_and_quarantines_legacy(d1_store):
    subject_b = "sub_ffffffffffffffffffffffffffffffff"
    await d1_store.save_rule(make_rule(rule_id="rule_subject_a"))
    await d1_store.save_rule(
        make_rule(rule_id="rule_subject_b", canonical_subject_id=subject_b)
    )
    await d1_store.save_rule(
        make_rule(rule_id="rule_legacy", canonical_subject_id=None)
    )
    trigger = ClawAutomationTrigger(
        trigger_id="trigger_async_subjects",
        correlation_id="corr_async_subjects",
        workspace_id=WORKSPACE,
        observed_at=NOW,
        membership=None,
        memberships=(
            membership(workspace_id=WORKSPACE),
            _membership_projection(
                subject_b,
                issued_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(hours=1),
            ),
        ),
    )

    receipt = await ClawAutomationTriggerBoundary(
        ClawAutomationTickRuntime(d1_store)
    ).ahandle(trigger)

    assert len(receipt.created_run_ids) == 2
    rows = await d1_store.list_runs(WORKSPACE)
    assert {row.rule_id for row in rows} == {"rule_subject_a", "rule_subject_b"}


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