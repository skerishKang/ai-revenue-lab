"""#2924 S2F4D terminal scheduled-run → Claw run-history/session behavior tests."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
from pathlib import Path

import pytest

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutput,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawScheduledRun,
    ClawScheduledRunStatus,
)
from kagent.contracts import ContractError

from app import claw_automation_history_bridge as bridge_module
from app.claw_automation_execution_bridge import AutomationExecutionBridgeError
from app.claw_automation_history_bridge import (
    ScheduledHistoryProjectionError,
    project_terminal_scheduled_run_to_history,
)
from app.claw_automation_owner_resolution import ResolvedAutomationOwner
from app.history import _run_history_public, validate_conversation_id

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)
_AUTO = object()
_UNSET = object()
WORKSPACE = "workspace_a"
OWNER_WORKSPACE = WORKSPACE
RULE_ID = "rule_s2f4d_1"
REVISION = "b" * 40
SCHEDULE = ClawScheduleExpression(ClawScheduleKind.CRON, "0 9 * * *", "UTC")
OWNER_USER = "usr_" + "7" * 32
FOREIGN_USER = "usr_" + "f" * 32
OWNED_CONVERSATION_ID = "chat_" + "a1" * 16
FOREIGN_CONVERSATION_ID = "chat_" + "b2" * 16
MALFORMED_CONVERSATION_ID = "chat_zzz"


def make_rule(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    output_type: ClawAutomationOutputType = ClawAutomationOutputType.REPORT,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="Daily bounded report",
        schedule=SCHEDULE,
        target_source=ClawAutomationTarget.TASKS,
        output_type=output_type,
        execution_intent=ClawAutomationExecutionIntent(
            task="Produce the scheduled bounded report",
            repository_ref="repo:padiem/ai-revenue-lab",
            exact_revision=REVISION,
        ),
    )


def scheduled_run(
    *,
    workspace_id: str = WORKSPACE,
    rule_id: str = RULE_ID,
    status: ClawScheduledRunStatus = ClawScheduledRunStatus.COMPLETED,
    output=_AUTO,
    error_message: str | None = None,
) -> ClawScheduledRun:
    from kagent.claw_automation import _derived_occurrence_id

    derived = _derived_occurrence_id("sched_run", workspace_id, rule_id, NOW)
    terminal = status in {
        ClawScheduledRunStatus.COMPLETED,
        ClawScheduledRunStatus.FAILED,
        ClawScheduledRunStatus.CANCELLED,
    }
    if output is _AUTO:
        output = (
            ClawAutomationOutput(
                output_id="scheduled_output_abc",
                workspace_id=workspace_id,
                output_type=ClawAutomationOutputType.REPORT,
                title="Daily bounded report",
                content="bounded report body",
            )
            if status is ClawScheduledRunStatus.COMPLETED
            else None
        )
    return ClawScheduledRun(
        run_id=derived,
        workspace_id=workspace_id,
        rule_id=rule_id,
        status=status,
        scheduled_time=NOW,
        started_at=NOW,
        completed_at=NOW if terminal else None,
        output=output,
        error_message=error_message
        if status is ClawScheduledRunStatus.FAILED
        else None,
    )


def make_owner(*, workspace_id: str = OWNER_WORKSPACE) -> ResolvedAutomationOwner:
    return ResolvedAutomationOwner(
        workspace_id=workspace_id,
        owner_ref="owner:opaque:0001",
        product_user_id=OWNER_USER,
        member_id="member_0001",
        canonical_subject_id="subject:padiem:user:123",
    )


class FakeHistoryStore:
    """Contract double mirroring the D1 (user_id, run_id) upsert semantics."""

    def __init__(self, *, conversations: dict | None = None) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.record_calls: list[dict] = []
        self.get_calls: list[tuple[str, str]] = []
        self.conversations = conversations or {
            OWNED_CONVERSATION_ID: {
                "id": OWNED_CONVERSATION_ID,
                "user_id": OWNER_USER,
            }
        }
        self.raise_on_record = False
        self.raise_on_get = False

    async def record_claw_run(self, **kwargs) -> None:
        if self.raise_on_record:
            raise RuntimeError("history write failed")
        self.record_calls.append(kwargs)
        key = (kwargs["user_id"], kwargs["run_id"])
        if key in self.rows:
            self.rows[key].update(kwargs)
        else:
            self.rows[key] = dict(kwargs)

    async def get_conversation(self, user_id: str, conversation_id: str):
        self.get_calls.append((user_id, conversation_id))
        if self.raise_on_get:
            raise RuntimeError("conversation authority read failed")
        stored = self.conversations.get(conversation_id)
        if stored is None or stored.get("user_id") != user_id:
            return None
        return dict(stored)

    def public_rows(self) -> list[dict]:
        return [_run_history_public(row) for row in self.rows.values()]


async def _project(
    store,
    *,
    rule=None,
    row=None,
    owner=_UNSET,
    conversation_id=None,
):
    return await project_terminal_scheduled_run_to_history(
        rule=rule or make_rule(),
        scheduled_run=row or scheduled_run(),
        owner=make_owner() if owner is _UNSET else owner,
        store=store,
        conversation_id=conversation_id,
    )


# ── truthful terminal projection ────────────────────────────────────────────


async def test_completed_row_projects_one_bounded_history_record():
    store = FakeHistoryStore()
    row = scheduled_run()

    result = await _project(store, row=row)

    assert result.run_id == row.run_id
    assert result.status is ClawScheduledRunStatus.COMPLETED
    assert result.conversation_id is None
    assert store.record_calls == [
        {
            "user_id": OWNER_USER,
            "run_id": row.run_id,
            "channel": "claw_automation",
            "action": "report",
            "title": "Daily bounded report",
            "status": "completed",
            "result_summary": "bounded report body",
            "conversation_id": None,
            "workspace_id": WORKSPACE,
        }
    ]
    assert len(store.rows) == 1


async def test_failed_row_projects_truthful_failure_summary():
    store = FakeHistoryStore()
    row = scheduled_run(
        status=ClawScheduledRunStatus.FAILED,
        error_message="P01 execution failed before a safe terminal output was available.",
    )

    result = await _project(store, row=row)

    assert result.status is ClawScheduledRunStatus.FAILED
    call = store.record_calls[0]
    assert call["status"] == "failed"
    assert call["result_summary"] == row.error_message
    assert call["title"] == "Daily bounded report"
    assert call["conversation_id"] is None


async def test_cancelled_row_projects_truthful_cancellation_without_summary():
    store = FakeHistoryStore()
    row = scheduled_run(status=ClawScheduledRunStatus.CANCELLED)

    result = await _project(store, row=row)

    assert result.status is ClawScheduledRunStatus.CANCELLED
    call = store.record_calls[0]
    assert call["status"] == "cancelled"
    assert call["result_summary"] is None


async def test_completed_row_without_output_keeps_null_summary():
    store = FakeHistoryStore()
    row = scheduled_run(status=ClawScheduledRunStatus.COMPLETED, output=None)

    await _project(store, row=row)

    call = store.record_calls[0]
    assert call["status"] == "completed"
    assert call["result_summary"] is None
    assert call["title"] == "Daily bounded report"


@pytest.mark.parametrize(
    "status",
    [ClawScheduledRunStatus.PENDING, ClawScheduledRunStatus.RUNNING],
)
async def test_non_terminal_row_fails_closed_without_history_write(status):
    store = FakeHistoryStore()
    row = scheduled_run(status=status)

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, row=row)
    assert store.record_calls == []
    assert store.rows == {}


# ── canonical session/conversation authority reuse ─────────────────────────


async def test_owned_conversation_is_resolved_and_persisted():
    store = FakeHistoryStore()

    result = await _project(store, conversation_id=OWNED_CONVERSATION_ID)

    assert result.conversation_id == OWNED_CONVERSATION_ID
    assert store.get_calls == [(OWNER_USER, OWNED_CONVERSATION_ID)]
    assert store.record_calls[0]["conversation_id"] == OWNED_CONVERSATION_ID
    public = store.public_rows()[0]
    assert public["session"] == {"conversation_id": OWNED_CONVERSATION_ID}


async def test_foreign_conversation_fails_closed_before_any_history_write():
    store = FakeHistoryStore(
        conversations={
            FOREIGN_CONVERSATION_ID: {
                "id": FOREIGN_CONVERSATION_ID,
                "user_id": FOREIGN_USER,
            }
        }
    )

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, conversation_id=FOREIGN_CONVERSATION_ID)
    assert store.record_calls == []
    assert store.rows == {}


async def test_missing_conversation_fails_closed_before_any_history_write():
    store = FakeHistoryStore()

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, conversation_id="chat_" + "c3" * 16)
    assert store.record_calls == []
    assert store.rows == {}


@pytest.mark.parametrize(
    "bad", [MALFORMED_CONVERSATION_ID, "", OWNER_USER, 123, {"id": OWNED_CONVERSATION_ID}]
)
async def test_malformed_conversation_fails_closed_before_authority_lookup(bad):
    store = FakeHistoryStore()

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, conversation_id=bad)
    assert store.get_calls == []
    assert store.record_calls == []


async def test_conversation_authority_failure_fails_closed_without_write():
    store = FakeHistoryStore()
    store.raise_on_get = True

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, conversation_id=OWNED_CONVERSATION_ID)
    assert store.record_calls == []


async def test_absent_conversation_keeps_legacy_null_session_and_reads_back():
    store = FakeHistoryStore()

    await _project(store, conversation_id=None)

    assert store.get_calls == []
    assert store.record_calls[0]["conversation_id"] is None
    public = store.public_rows()[0]
    assert public["session"] is None
    # The public projection never leaks the owner id or raw storage keys.
    assert "user_id" not in public
    assert OWNER_USER not in str(public)


# ── identity / scope correlation ───────────────────────────────────────────


async def test_exact_retry_is_idempotent_on_one_history_row():
    store = FakeHistoryStore()
    row = scheduled_run()

    first = await _project(store, row=row)
    second = await _project(store, row=row)

    assert first == second
    assert len(store.rows) == 1
    assert len(store.record_calls) == 2
    assert store.record_calls[0] == store.record_calls[1]


async def test_foreign_workspace_owner_fails_closed_without_write():
    store = FakeHistoryStore()
    foreign_owner = make_owner(workspace_id="workspace_b")

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, owner=foreign_owner)
    assert store.record_calls == []


@pytest.mark.parametrize("bad_owner", [None, {}, "usr_" + "7" * 32, object()])
async def test_unresolved_owner_is_never_accepted(bad_owner):
    store = FakeHistoryStore()

    with pytest.raises(ScheduledHistoryProjectionError):
        await _project(store, owner=bad_owner)
    assert store.record_calls == []


async def test_foreign_rule_identity_fails_closed_without_write():
    store = FakeHistoryStore()
    foreign_rule = make_rule(workspace_id="workspace_b", rule_id="other_rule")

    with pytest.raises(
        (ScheduledHistoryProjectionError, AutomationExecutionBridgeError, ContractError)
    ):
        await _project(store, rule=foreign_rule)
    assert store.record_calls == []


async def test_history_store_without_record_capability_fails_closed():
    class PresenceOnly:
        async def get_user(self, user_id):
            return None

    with pytest.raises(ScheduledHistoryProjectionError):
        await project_terminal_scheduled_run_to_history(
            rule=make_rule(),
            scheduled_run=scheduled_run(),
            owner=make_owner(),
            store=PresenceOnly(),
        )


# ── boundary + source contract ─────────────────────────────────────────────


def test_projection_is_async_and_validation_helpers_are_sync():
    assert inspect.iscoroutinefunction(project_terminal_scheduled_run_to_history)
    assert not inspect.iscoroutinefunction(bridge_module._require_terminal)
    assert not inspect.iscoroutinefunction(bridge_module._history_fields)


def test_conversation_validator_reused_not_reimplemented():
    # The exact canonical shape validator is the only grammar in play.
    assert validate_conversation_id(OWNED_CONVERSATION_ID) == OWNED_CONVERSATION_ID
    with pytest.raises(ValueError):
        validate_conversation_id(MALFORMED_CONVERSATION_ID)
    assert validate_conversation_id(None) is None


def test_source_contains_no_new_authority_or_side_effect_surface():
    source = Path(bridge_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "record_run(",
        "create_claw_run(",
        "occurrence_key(",
        "ClawAutomationTickRuntime",
        "FakeClawScheduler",
        "resolve_owner",
        "ClawAutomationOwnerResolver",
        "AutomationOwnerAuthority",
        ".owner_ref",
        "project_scheduled_run_output(",
        "TaskAlert",
        "D1ClawTaskAlertStore",
        "add_task(",
        "add_alert(",
        "append_exchange(",
        "record_password",
        "upsert_google_user",
        "SandboxLeasePort",
        "execute_scheduled_occurrence(",
        "update_run_projection(",
        "asyncio.run(",
        "urllib",
        "httpx",
        "PadiemAiEngineClient",
        "active_route_for",
        "model_policy",
    ):
        assert forbidden not in source

    assert source.count('"record_claw_run"') == 1
    assert source.count("await record(") == 1
    assert source.count("get_conversation(") == 1
    assert source.count("validate_conversation_id(") == 1
    assert source.count("plan_canonical_scheduled_execution(") == 1
