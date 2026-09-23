"""#2833 S2F5B — execution-claim store authority tests.

Proves the smallest additive conditional execution claim on the EXISTING
automation store: ``PENDING -> RUNNING`` for exactly one caller, ``NOT_CLAIMED``
for every other state, no second lock table / claim token / lease / dedup
authority, and no DELETE on the loser path.

NETWORK_FREE: no scheduler, no provider call, no external send, no Production
mutation. Every claim is measured against the real in-memory and real SQLite
store, and the SQLite statement stream is captured so "one bounded conditional
update" is read off the wire rather than asserted from prose.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ContractError,
    InMemoryClawAutomationStore,
    SqliteClawAutomationStore,
    _derived_occurrence_id,
    occurrence_key,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace_a"
FOREIGN_WORKSPACE = "workspace_b"
RULE_ID = "rule_s2f5b_claim"
REVISION = "b" * 40
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily bounded check",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.REPORT,
        owner_ref="owner:opaque:provenance:1",
        execution_intent=ClawAutomationExecutionIntent(
            task="Produce the scheduled bounded report",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision=REVISION,
        ),
    )


def run_for(
    *,
    rule: ClawAutomationRule | None = None,
    workspace_id: str | None = None,
    rule_id: str | None = None,
    scheduled_time: datetime = NOW,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.PENDING,
) -> ClawScheduledRun:
    rule = rule or make_rule()
    workspace = workspace_id if workspace_id is not None else rule.workspace_id
    owning_rule = rule_id if rule_id is not None else rule.rule_id
    return ClawScheduledRun(
        run_id=_derived_occurrence_id("sched_run", workspace, owning_rule, scheduled_time),
        workspace_id=workspace,
        rule_id=owning_rule,
        status=status,
        scheduled_time=scheduled_time,
        started_at=scheduled_time,
        completed_at=None if status is ClawScheduledRunStatus.PENDING else scheduled_time,
    )


def seed(store, *, rule=None, row=None) -> tuple[ClawAutomationRule, ClawScheduledRun]:
    rule = rule or make_rule()
    row = row or run_for(rule=rule)
    store.save_rule(rule)
    store.record_run(row)
    return rule, row


def drop_occurrence_claim(store, row: ClawScheduledRun) -> None:
    """Remove the occurrence mapping, leaving an orphaned run row."""

    key = occurrence_key(row.workspace_id, row.rule_id, row.scheduled_time)
    if isinstance(store, InMemoryClawAutomationStore):
        store._occurrences.pop(key)
        return
    store._db.execute("DELETE FROM claw_occurrences WHERE occurrence_key = ?", (key,))


def table_names(store) -> list[str]:
    rows = store._db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


class RecordingConnection:
    """Delegating proxy that records statements and can inject one competing write.

    ``sqlite3.Connection.execute`` is a read-only C slot, so the proxy is a plain
    object whose ``execute`` is an instance attribute.
    """

    def __init__(self, inner, *, on_statement=None, match=None) -> None:
        self._inner = inner
        self.statements: list[str] = []
        self._on_statement = on_statement
        self._match = match

    def execute(self, sql, parameters=()):
        normalised = " ".join(str(sql).split())
        self.statements.append(normalised)
        if self._on_statement is not None and self._match and self._match in normalised:
            hook = self._on_statement
            self._on_statement = None
            hook()
        return self._inner.execute(sql, parameters)

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        return self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryClawAutomationStore()
    return SqliteClawAutomationStore(str(tmp_path / "execution_claim.db"))


def claim(store, row: ClawScheduledRun):
    return store.claim_execution(
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        rule_id=row.rule_id,
        scheduled_time=row.scheduled_time,
    )


# --- exactly one PENDING -> RUNNING transition ------------------------------


def test_pending_row_is_claimed_as_running_with_unchanged_identity(store):
    rule, row = seed(store)

    claimed = claim(store, row)

    assert claimed is not None
    assert claimed.run_id == row.run_id
    assert claimed.workspace_id == row.workspace_id
    assert claimed.rule_id == rule.rule_id
    assert claimed.status is ClawScheduledRunStatus.RUNNING
    assert claimed.scheduled_time == row.scheduled_time
    assert claimed.started_at == row.started_at
    assert claimed.completed_at is None
    assert claimed.output is None


def test_second_claim_is_not_claimed(store):
    _, row = seed(store)

    first = claim(store, row)
    second = claim(store, row)

    assert first is not None
    assert second is None
    assert store.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.RUNNING


@pytest.mark.parametrize(
    "status",
    [
        ClawScheduledRunStatus.RUNNING,
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    ],
)
def test_non_pending_row_is_never_claimed(store, status):
    rule = make_rule()
    row = run_for(rule=rule, status=status)
    store.save_rule(rule)
    store.record_run(row)

    assert claim(store, row) is None
    assert store.get_run(row.run_id, WORKSPACE).status is status


def test_claim_never_inserts_a_row_or_a_second_identity(store):
    rule, row = seed(store)
    before = [item.run_id for item in store.list_runs(WORKSPACE)]

    claim(store, row)

    after = [item.run_id for item in store.list_runs(WORKSPACE)]
    assert after == before == [row.run_id]


def test_claim_does_not_mutate_started_at_or_scheduled_time(store):
    rule, row = seed(store)

    claim(store, row)
    stored = store.get_run(row.run_id, WORKSPACE)

    assert stored.started_at == row.started_at
    assert stored.scheduled_time == row.scheduled_time


# --- fail-closed refusals ---------------------------------------------------


def test_missing_row_fails_closed(store):
    rule = make_rule()
    store.save_rule(rule)
    row = run_for(rule=rule)

    with pytest.raises(ContractError):
        claim(store, row)


def test_foreign_workspace_fails_closed(store):
    rule, row = seed(store)

    with pytest.raises(ContractError):
        store.claim_execution(
            run_id=row.run_id,
            workspace_id=FOREIGN_WORKSPACE,
            rule_id=row.rule_id,
            scheduled_time=row.scheduled_time,
        )
    assert store.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.PENDING


def test_rule_identity_mismatch_fails_closed(store):
    _, row = seed(store)

    with pytest.raises(ContractError):
        store.claim_execution(
            run_id=row.run_id,
            workspace_id=WORKSPACE,
            rule_id="rule_other",
            scheduled_time=row.scheduled_time,
        )
    assert store.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.PENDING


def test_scheduled_time_mismatch_fails_closed(store):
    _, row = seed(store)

    with pytest.raises(ContractError):
        store.claim_execution(
            run_id=row.run_id,
            workspace_id=WORKSPACE,
            rule_id=row.rule_id,
            scheduled_time=datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc),
        )
    assert store.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.PENDING


def test_row_without_its_occurrence_claim_fails_closed(store):
    rule, row = seed(store)
    drop_occurrence_claim(store, row)

    with pytest.raises(ContractError):
        claim(store, row)
    assert store.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.PENDING


# --- durable semantics ------------------------------------------------------


def test_sqlite_claim_is_durable_across_reopen(tmp_path):
    path = str(tmp_path / "durable_claim.db")
    store = SqliteClawAutomationStore(path)
    _, row = seed(store)

    assert claim(store, row) is not None

    reopened = SqliteClawAutomationStore(path)
    assert reopened.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.RUNNING
    assert claim(reopened, row) is None


def test_sqlite_claim_statement_carries_the_pending_guard(tmp_path):
    store = SqliteClawAutomationStore(str(tmp_path / "guard.db"))
    _, row = seed(store)
    proxy = RecordingConnection(store._db)
    store._db = proxy

    assert claim(store, row) is not None

    updates = [
        statement
        for statement in proxy.statements
        if statement.startswith("UPDATE claw_runs SET status=")
    ]
    assert len(updates) == 1
    assert updates[0].endswith("WHERE run_id=? AND status=? AND completed_at IS NULL")
    assert [s.split()[0].upper() for s in proxy.statements].count("COMMIT") == 1


def test_concurrent_second_claimant_loses_without_deleting_the_winner(tmp_path):
    store = SqliteClawAutomationStore(str(tmp_path / "race.db"))
    rule, row = seed(store)
    inner = store._db

    def competing_winner():
        inner.execute(
            "UPDATE claw_runs SET status=? WHERE run_id=?",
            (ClawScheduledRunStatus.RUNNING.value, row.run_id),
        )

    proxy = RecordingConnection(
        inner, on_statement=competing_winner, match="UPDATE claw_runs SET status="
    )
    store._db = proxy

    assert claim(store, row) is None

    keywords = [statement.split()[0].upper() for statement in proxy.statements]
    assert "DELETE" not in keywords
    assert keywords.count("COMMIT") == 1
    assert keywords.count("ROLLBACK") == 0
    assert store.get_run(row.run_id, WORKSPACE).status is ClawScheduledRunStatus.RUNNING
    assert len(store.list_runs(WORKSPACE)) == 1


def test_claim_introduces_no_new_table(tmp_path):
    store = SqliteClawAutomationStore(str(tmp_path / "schema.db"))
    _, row = seed(store)
    before = table_names(store)

    assert claim(store, row) is not None

    assert table_names(store) == before
    assert "claw_runs" in before


# --- no second authority in source -----------------------------------------


def test_module_declares_no_second_execution_authority():
    from kagent import claw_automation as module

    assert module.EXECUTION_CLAIM_AUTHORITY_REUSED is True
    assert module.EXECUTION_CLAIM_NEW_LOCK_TABLE is False
    assert module.EXECUTION_CLAIM_NEW_CLAIM_TOKEN is False
    assert module.EXECUTION_CLAIM_SECOND_DEDUP_AUTHORITY is False
    assert module.EXECUTION_CLAIM_SECOND_RUN_ID is False
    assert module.EXECUTION_CLAIM_REDISPATCHES_RUNNING is False
    assert module.EXECUTION_CLAIM_REDISPATCHES_TERMINAL is False
    assert module.EXECUTION_CLAIM_PERFORMS_PROVIDER_CALLS is False
    assert module.EXECUTION_CLAIM_ACTIVATES_PRODUCTION_SCHEDULER is False
