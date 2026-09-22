"""#2833 S2F2 lifecycle bridge foundation tests.

The bridge is the same-run-id identity between a scheduled occurrence and the
canonical ``ClawRun`` state machine, plus a bounded projection-update path that
never claims, never inserts, and never mutates the occurrence identity.

Nothing here dispatches: no P01 helper is called, owner resolution is not
wired, and History/Task/Alert stores are never written. The existing
dry-run/tick behaviour is asserted unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import tempfile

import pytest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationStore,
    ClawAutomationTarget,
    ClawAutomationTickRuntime,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ClawScheduleExpression,
    ClawScheduleKind,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    canonical_claw_run_for_occurrence,
    canonical_task_intent_for_occurrence,
    occurrence_key,
    project_canonical_status,
    _derived_occurrence_id,
)
from kagent.contracts import ClawRunStatus, ExecutionMode
from kagent.runs import InMemoryRunStore, RunStateError
from kagent.workspace_visibility import TrustedWorkspaceMembershipProjection, WorkspaceRole

NOW = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
SCHED = NOW.replace(second=0, microsecond=0)
WORKSPACE = "workspace_a"
OTHER_WORKSPACE = "workspace_b"
RULE_ID = "rule_bridge_1"
REVISION = "a" * 40
INTENT_TASK = "Summarize the queued alerts for the on-call rotation"
REPO = "repo:padiem/ai-revenue-lab"
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")
MEMBERSHIP = TrustedWorkspaceMembershipProjection(
    membership_id="membership:owner",
    workspace_id=WORKSPACE,
    principal_ref="principal:user",
    role=WorkspaceRole.OWNER,
    authority_ref="control-plane:membership",
    issued_at=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=1),
)


def make_rule(*, rule_id=RULE_ID, workspace_id=WORKSPACE, execution_intent=None, enabled=True):
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Bridge rule display label",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=enabled,
        execution_intent=execution_intent,
    )


def execution_intent() -> ClawAutomationExecutionIntent:
    return ClawAutomationExecutionIntent(
        task=INTENT_TASK,
        repository_ref=REPO,
        exact_revision=REVISION,
    )


def derived_run_id(*, workspace_id=WORKSPACE, rule_id=RULE_ID, scheduled=SCHED) -> str:
    return _derived_occurrence_id("sched_run", workspace_id, rule_id, scheduled)


def projection_row(
    *,
    run_id=None,
    workspace_id=WORKSPACE,
    rule_id=RULE_ID,
    scheduled=SCHED,
    status=ClawScheduledRunStatus.COMPLETED,
) -> ClawScheduledRun:
    return ClawScheduledRun(
        run_id=run_id or derived_run_id(workspace_id=workspace_id, rule_id=rule_id),
        workspace_id=workspace_id,
        rule_id=rule_id,
        status=status,
        scheduled_time=scheduled,
        started_at=scheduled,  # STARTED_AT_LEGACY_SLOT_MARKER
        completed_at=scheduled if status in (ClawScheduledRunStatus.COMPLETED,) else None,
    )


class SqliteFactory:
    def __init__(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self._dir, "lifecycle_bridge.db")

    def __call__(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def reopen(self) -> SqliteClawAutomationStore:
        return SqliteClawAutomationStore(self.db_path)

    def cleanup(self) -> None:
        for path in (self.db_path, f"{self.db_path}-wal", f"{self.db_path}-shm"):
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(self._dir)
        except OSError:
            pass


class _CtxStore:
    """The stores are not context managers; adapt the factory so tests can use ``with``."""

    def __init__(self, factory) -> None:
        self._factory = factory

    def __call__(self):
        return self

    def __enter__(self):
        self._store = self._factory()
        return self._store

    def __exit__(self, *exc) -> bool:
        return False


def store_factories():
    yield (_CtxStore(lambda: InMemoryClawAutomationStore()), False)
    factory = SqliteFactory()
    yield (_CtxStore(factory), True)
    factory.cleanup()


# --- canonical task intent ---------------------------------------------------


def test_canonical_intent_maps_only_the_execution_intent() -> None:
    rule = make_rule(execution_intent=execution_intent())
    intent = canonical_task_intent_for_occurrence(rule, SCHED)

    assert intent.task == INTENT_TASK
    assert intent.repository_ref == REPO
    assert intent.execution_mode == ExecutionMode.CLOUD
    assert intent.requested_revision == REVISION
    assert intent.source_surface == "automation"
    # Display labels and closed enums are never reinterpreted as instructions.
    assert intent.task != rule.name


def test_canonical_task_id_is_deterministic_and_bounded() -> None:
    rule = make_rule(execution_intent=execution_intent())
    first = canonical_task_intent_for_occurrence(rule, SCHED)
    second = canonical_task_intent_for_occurrence(rule, SCHED)

    assert first.task_id == second.task_id
    assert first.task_id.startswith("task_")
    assert len(first.task_id) <= 128
    # Deterministic from the occurrence identity: another rule/instant differs.
    other_instant = canonical_task_intent_for_occurrence(rule, SCHED + timedelta(minutes=1))
    assert other_instant.task_id != first.task_id
    other_rule = make_rule(rule_id="rule_bridge_2", execution_intent=execution_intent())
    assert canonical_task_intent_for_occurrence(other_rule, SCHED).task_id != first.task_id


def test_canonical_task_id_is_not_a_dedup_authority() -> None:
    rule = make_rule(execution_intent=execution_intent())
    intent = canonical_task_intent_for_occurrence(rule, SCHED)

    key = occurrence_key(WORKSPACE, RULE_ID, SCHED)
    assert intent.task_id != key
    assert intent.task_id != derived_run_id()


def test_legacy_rule_without_intent_fails_closed() -> None:
    rule = make_rule(execution_intent=None)
    with pytest.raises(Exception) as raised:
        canonical_task_intent_for_occurrence(rule, SCHED)
    assert "execution intent" in str(raised.value)


# --- SAME run id -------------------------------------------------------------


def test_canonical_run_reuses_the_scheduled_run_id() -> None:
    rule = make_rule(execution_intent=execution_intent())
    run, intent = canonical_claw_run_for_occurrence(rule, SCHED)

    expected = derived_run_id()
    assert run.run_id == expected
    assert intent.task_id != run.run_id
    # One logical occurrence owns exactly one id: no second, random, run id.
    assert not run.run_id.startswith("run_") or run.run_id == expected
    assert run.run_id.startswith("sched_run_")


def test_canonical_run_container_is_queued_and_carries_the_intent() -> None:
    run, intent = canonical_claw_run_for_occurrence(make_rule(execution_intent=execution_intent()), SCHED)
    from kagent.claw_automation import ClawRun

    assert isinstance(run, ClawRun)
    assert run.status == ClawRunStatus.QUEUED
    assert run.intent.task_id == intent.task_id
    assert run.intent.execution_mode == ExecutionMode.CLOUD


def test_two_calls_never_invent_a_second_run_id() -> None:
    rule = make_rule(execution_intent=execution_intent())
    first_run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
    second_run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
    assert first_run.run_id == second_run.run_id == derived_run_id()


# --- status mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    ("canonical", "projected"),
    [
        (ClawRunStatus.QUEUED, ClawScheduledRunStatus.PENDING),
        (ClawRunStatus.PREPARING, ClawScheduledRunStatus.RUNNING),
        (ClawRunStatus.RUNNING, ClawScheduledRunStatus.RUNNING),
        (ClawRunStatus.WAITING_APPROVAL, ClawScheduledRunStatus.RUNNING),
        (ClawRunStatus.COMPLETED, ClawScheduledRunStatus.COMPLETED),
        (ClawRunStatus.FAILED, ClawScheduledRunStatus.FAILED),
        (ClawRunStatus.CANCELLED, ClawScheduledRunStatus.CANCELLED),
    ],
)
def test_status_mapping_table(canonical, projected) -> None:
    assert project_canonical_status(canonical) is projected


def test_status_mapping_refuses_unknown_values() -> None:
    with pytest.raises(Exception) as raised:
        project_canonical_status("not-a-status")
    assert "status" in str(raised.value)


# --- projection update: happy paths (both backends) --------------------------


@pytest.mark.parametrize("status", [ClawScheduledRunStatus.PENDING, ClawScheduledRunStatus.RUNNING])
def test_non_terminal_update_clears_completed_at(status) -> None:
    for make_store, _ in store_factories():
        with make_store() as store:
            store.record_run(projection_row())
            updated = store.update_run_projection(
                run_id=derived_run_id(),
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=SCHED,
                status=status,
                completed_at=None,
            )
            assert updated.status == status
            assert updated.completed_at is None


@pytest.mark.parametrize(
    ("canonical", "projected"),
    [
        (ClawRunStatus.COMPLETED, ClawScheduledRunStatus.COMPLETED),
        (ClawRunStatus.FAILED, ClawScheduledRunStatus.FAILED),
        (ClawRunStatus.CANCELLED, ClawScheduledRunStatus.CANCELLED),
    ],
)
def test_terminal_update_sets_completed_at(canonical, projected) -> None:
    terminal_at = SCHED + timedelta(minutes=10)
    for make_store, _ in store_factories():
        with make_store() as store:
            store.record_run(projection_row())
            updated = store.update_run_projection(
                run_id=derived_run_id(),
                workspace_id=WORKSPACE,
                rule_id=RULE_ID,
                scheduled_time=SCHED,
                status=projected,
                completed_at=terminal_at,
            )
            assert updated.status == projected
            assert updated.completed_at == terminal_at


def test_failed_update_redacts_and_bounds_error_message() -> None:
    credential_laden = "boom: token=sk-live-abcdef0123456789"
    store = InMemoryClawAutomationStore()
    store.record_run(projection_row())
    updated = store.update_run_projection(
        run_id=derived_run_id(),
        workspace_id=WORKSPACE,
        rule_id=RULE_ID,
        scheduled_time=SCHED,
        status=ClawScheduledRunStatus.FAILED,
        completed_at=SCHED + timedelta(minutes=5),
        error_message=credential_laden,
    )
    assert updated.status == ClawScheduledRunStatus.FAILED
    assert len(updated.error_message) <= 1024
    assert "sk-live-abcdef0123456789" not in updated.error_message


def test_over_long_error_message_is_refused() -> None:
    store = InMemoryClawAutomationStore()
    store.record_run(projection_row())
    with pytest.raises(Exception) as raised:
        store.update_run_projection(
            run_id=derived_run_id(),
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=SCHED,
            status=ClawScheduledRunStatus.FAILED,
            completed_at=SCHED + timedelta(minutes=5),
            error_message="x" * 1200,
        )
    assert "exceeds" in str(raised.value)


def test_error_message_on_non_failed_update_is_refused() -> None:
    store = InMemoryClawAutomationStore()
    store.record_run(projection_row())
    with pytest.raises(Exception) as raised:
        store.update_run_projection(
            run_id=derived_run_id(),
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=SCHED,
            status=ClawScheduledRunStatus.RUNNING,
            error_message="nope",
        )
    assert "error_message" in str(raised.value)


def test_completed_at_on_non_terminal_update_is_refused() -> None:
    store = InMemoryClawAutomationStore()
    store.record_run(projection_row())
    with pytest.raises(Exception) as raised:
        store.update_run_projection(
            run_id=derived_run_id(),
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=SCHED,
            status=ClawScheduledRunStatus.PENDING,
            completed_at=SCHED + timedelta(minutes=3),
        )
    assert "completed_at" in str(raised.value)


# --- projection update: fail-closed guards -----------------------------------


def test_update_missing_run_never_inserts() -> None:
    for make_store, _ in store_factories():
        with make_store() as store:
            with pytest.raises(Exception) as raised:
                store.update_run_projection(
                    run_id=derived_run_id(),
                    workspace_id=WORKSPACE,
                    rule_id=RULE_ID,
                    scheduled_time=SCHED,
                    status=ClawScheduledRunStatus.RUNNING,
                )
            assert "existing scheduled run" in str(raised.value)
            assert store.list_runs(WORKSPACE) == []


def test_update_cannot_mutate_identity() -> None:
    for make_store, _ in store_factories():
        with make_store() as store:
            store.record_run(projection_row())
            original = store.get_run(derived_run_id(), WORKSPACE)
            cases = [
                {"workspace_id": OTHER_WORKSPACE},
                {"rule_id": "rule_bridge_2"},
                {"scheduled_time": SCHED + timedelta(minutes=1)},
            ]
            for case in cases:
                with pytest.raises(Exception) as raised:
                    store.update_run_projection(
                        run_id=derived_run_id(),
                        workspace_id=case.get("workspace_id", WORKSPACE),
                        rule_id=case.get("rule_id", RULE_ID),
                        scheduled_time=case.get("scheduled_time", SCHED),
                        status=ClawScheduledRunStatus.RUNNING,
                    )
                assert "projection update" in str(raised.value)
            # The stored row is byte-for-byte the original.
            assert store.get_run(derived_run_id(), WORKSPACE) == original


def test_update_cannot_claim_a_new_occurrence() -> None:
    store = InMemoryClawAutomationStore()
    store.record_run(projection_row())
    before = dict(store._occurrences)
    # A projection update naming an occurrence that was never claimed must fail
    # closed rather than silently minting the claim.
    with pytest.raises(Exception):
        store.update_run_projection(
            run_id=derived_run_id(workspace_id=OTHER_WORKSPACE, rule_id="rule_bridge_2"),
            workspace_id=OTHER_WORKSPACE,
            rule_id="rule_bridge_2",
            scheduled_time=SCHED,
            status=ClawScheduledRunStatus.RUNNING,
        )
    assert store._occurrences == before


def test_sqlite_reopen_keeps_the_updated_projection() -> None:
    factory = SqliteFactory()
    try:
        store = factory()
        store.record_run(projection_row())
        store.update_run_projection(
            run_id=derived_run_id(),
            workspace_id=WORKSPACE,
            rule_id=RULE_ID,
            scheduled_time=SCHED,
            status=ClawScheduledRunStatus.FAILED,
            completed_at=SCHED + timedelta(minutes=7),
            error_message="boom",
        )
        reopened = factory.reopen()
        reopened_run = reopened.get_run(derived_run_id(), WORKSPACE)
        assert reopened_run.status == ClawScheduledRunStatus.FAILED
        assert reopened_run.completed_at == SCHED + timedelta(minutes=7)
        assert reopened_run.error_message == "boom"
    finally:
        factory.cleanup()


# --- record_run remains the occurrence-claim authority -----------------------


def test_record_run_claims_once_and_never_clones() -> None:
    rule = make_rule(execution_intent=execution_intent())
    scheduled_run = projection_row()
    for make_store, _ in store_factories():
        with make_store() as store:
            first = store.record_run(scheduled_run)
            again = store.record_run(projection_row(status=ClawScheduledRunStatus.RUNNING))
            assert first.run_id == again.run_id == derived_run_id()
            # record_run stays the claim authority: re-recording the same occurrence
            # returns the stored row instead of overwriting it with newer input.
            assert again.status == ClawScheduledRunStatus.COMPLETED
            assert len(store.list_runs(WORKSPACE)) == 1
            # The claim maps this logical occurrence to exactly one canonical id.
            assert store.get_run_for_occurrence(occurrence_key(WORKSPACE, RULE_ID, SCHED), WORKSPACE).run_id == derived_run_id()


def test_duplicate_occurrence_creates_one_row_and_one_run_id() -> None:
    rule = make_rule(execution_intent=execution_intent())
    for make_store, _ in store_factories():
        with make_store() as store:
            run, _ = canonical_claw_run_for_occurrence(rule, SCHED)
            store.record_run(projection_row(run_id=run.run_id))
            # A second tick re-runs the same dry-run for the same occurrence and
            # must land on the same single row, not a second one.
            again = store.record_run(projection_row(run_id=run.run_id, status=ClawScheduledRunStatus.RUNNING))
            assert again.run_id == run.run_id
            assert len(store.list_runs(WORKSPACE)) == 1


def test_inmemory_run_store_refuses_a_second_container_for_the_same_id() -> None:
    rule = make_rule(execution_intent=execution_intent())
    run, intent = canonical_claw_run_for_occurrence(rule, SCHED)
    store = InMemoryRunStore()
    store.add(run)
    duplicate, _ = canonical_claw_run_for_occurrence(rule, SCHED)
    with pytest.raises(RunStateError):
        store.add(duplicate)
    assert len(store) == 1
    assert store.get(run.run_id).run_id == run.run_id


# --- legacy dry-run / tick behaviour unchanged --------------------------------


def test_legacy_dry_run_is_still_terminal_at_birth() -> None:
    store = InMemoryClawAutomationStore()
    scheduler_store = InMemoryClawAutomationStore()
    from kagent.claw_automation import FakeClawScheduler

    scheduler = FakeClawScheduler(scheduler_store)
    legacy = make_rule(execution_intent=None)
    run = scheduler.execute_rule_dry_run(legacy, SCHED, None)
    assert run.status == ClawScheduledRunStatus.COMPLETED
    assert run.started_at == run.scheduled_time == SCHED
    assert run.completed_at == SCHED


def test_tick_behaviour_is_unchanged() -> None:
    scheduler_store = InMemoryClawAutomationStore()
    from kagent.claw_automation import FakeClawScheduler

    runtime = ClawAutomationTickRuntime(scheduler_store)
    rule = make_rule(execution_intent=execution_intent())
    scheduler_store.save_rule(rule)

    receipt = runtime.tick(workspace_id=WORKSPACE, current_time=SCHED, membership=MEMBERSHIP)
    assert receipt.due_count == 1
    assert len(receipt.created_run_ids) == 1
    # The tick still records the scheduled projection, not a canonical container.
    assert scheduler_store.get_run(receipt.created_run_ids[0], WORKSPACE).run_id == receipt.created_run_ids[0]
    # A second tick for the same occurrence is deduplicated by the claim authority.
    second = runtime.tick(workspace_id=WORKSPACE, current_time=SCHED, membership=MEMBERSHIP)
    assert second.created_run_ids == ()
    assert len(scheduler_store.list_runs(WORKSPACE)) == 1


# --- no P01 / no owner / no history-task-alert surface ------------------------


def test_s2f2_section_introduces_no_dispatch_or_owner_surface() -> None:
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath(
        "src/kagent/claw_automation.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "create_claw_run(",
        "execute_p01_claw_task(",
        "run_p01_task(",
        "resolve_owner",
        "BackgroundDispatchRequest",
        "record_claw_run(",
    ):
        assert forbidden not in source, forbidden


def test_bridge_contract_is_part_of_the_store_protocol() -> None:
    # The protocol exposes the bounded update path so future consumers cannot
    # invent a second projection authority.
    for store in (InMemoryClawAutomationStore(), SqliteClawAutomationStore(":memory:")):
        assert hasattr(store, "update_run_projection")
        assert callable(store.update_run_projection)
        assert hasattr(store, "record_run")
