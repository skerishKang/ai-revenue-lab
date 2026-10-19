"""#4194 A/B: owner-scoped run control and expired-lease recovery.

Offline only: real SQLite SQL through the D1-shaped async adapter, the existing
trusted Agent/Skill fixture, no provider call, no Cloudflare deployment, no
900-second wait. These tests pin:

- owner-scoped status read and cancel of an already-issued run;
- other-app / other-owner / unknown-run refusal without existence disclosure;
- cancel vs completion races and idempotent retries;
- uncertainty honesty: a running run that may already have produced an external
  effect is fenced to ``needs_review``, never reported as a rolled-back cancel;
- the deployment-gated expired-lease sweep: expired ``running`` only, only the
  caller's owner scope, live leases/terminal states preserved, repeat-safe, and
  no Tool/provider re-execution.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3

import pytest

from app.agent_durable_d1 import D1AgentRunLedger
from padiem_ai_core.agent_durable_lease import AgentDurableLeaseError, AgentRunLease

from tests.test_4194_agent_durable_d1 import MIGRATION, Clock, SQLiteD1
from tests.test_agent_skill_service import AGENT_ID, APP_ID, SUBJECT_ID, Fixture

RUN_1 = "arun_" + "1" * 32
OWNER_SCOPE = "scope_" + hashlib.sha256((APP_ID + ":" + SUBJECT_ID).encode("utf-8")).hexdigest()
OTHER_OWNER_SCOPE = "scope_" + hashlib.sha256(b"other.app:user_9").hexdigest()
FP = "c" * 64
WORKER = "eng_" + "a" * 24


class Harness:
    """Real SQLite D1 adapter plus one shared fake clock for the whole test.

    Seed rows, the production ledger and the composed service must all read the
    same clock, otherwise a lease would look live to one and expired to another.
    """

    def __init__(self, db) -> None:
        self.db = db
        self.clock = Clock()

    def seed(
        self,
        *,
        run_id: str = RUN_1,
        owner_scope: str = OWNER_SCOPE,
        status: str = "running",
        lease_seconds: float = 120.0,
        uncertain: int = 0,
        checkpoint_step: int = 0,
        epoch: int = 1,
    ) -> None:
        now = self.clock.now.timestamp()
        self.db.execute(
            "INSERT INTO padiem_engine_agent_runs_v1 "
            "(run_id,owner_scope,request_fingerprint,status,worker_id,epoch,"
            "lease_until,heartbeat_at,checkpoint_step,side_effect_uncertain) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, owner_scope, FP, status, WORKER, epoch,
             now + lease_seconds, now - 30.0, checkpoint_step, uncertain),
        )

    def ledger(self) -> D1AgentRunLedger:
        return D1AgentRunLedger(SQLiteD1(self.db), clock=self.clock)

    def service(self, *, recovery_enabled: bool = False, fixture: Fixture | None = None) -> Fixture:
        fx = fixture or Fixture()
        fx.service._agent_run_ledger = self.ledger()
        fx.service._agent_run_recovery_enabled = recovery_enabled
        return fx

    def row(self, run_id: str) -> dict:
        return dict(self.db.execute(
            "SELECT status,epoch,checkpoint_step,side_effect_uncertain,heartbeat_at,lease_until "
            "FROM padiem_engine_agent_runs_v1 WHERE run_id=?", (run_id,),
        ).fetchone())


@pytest.fixture
def harness(tmp_path):
    path = tmp_path / "engine-d1.sqlite"
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    yield Harness(db)
    db.close()


def _control(*, run_id: str, app_id: str = APP_ID, agent_id: str = AGENT_ID, **extra) -> dict:
    payload = {"app_id": app_id, "agent_id": agent_id, "run_id": run_id}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# A. Status
# ---------------------------------------------------------------------------


async def test_status_reads_owner_scoped_state_for_an_issued_run(harness):
    harness.seed(uncertain=1, checkpoint_step=3, epoch=4)
    service = harness.service().service

    response = await service.status_payload(_control(run_id=RUN_1))

    assert response.status_code == 200, response.body
    run = response.body["run"]
    assert run["run_id"] == RUN_1
    assert run["state"] == "running"
    assert run["epoch"] == 4
    assert run["checkpoint_step"] == 3
    assert run["side_effect_uncertain"] is True
    assert run["lease_live"] is True
    assert run["dispatch_fenced"] is False
    assert run["requires_reconciliation"] is False
    assert run["heartbeat_age_seconds"] >= 30
    # No payload/identity disclosure: owner scope, fingerprint and worker stay out.
    joined = json.dumps(response.body)
    assert OWNER_SCOPE not in joined
    assert FP not in joined
    assert "eng_" not in joined


async def test_expired_live_lease_is_reported_as_fenced(harness):
    harness.seed(lease_seconds=-1.0)
    service = harness.service().service

    response = await service.status_payload(_control(run_id=RUN_1))

    assert response.status_code == 200
    assert response.body["run"]["lease_live"] is False
    assert response.body["run"]["dispatch_fenced"] is True
    assert response.body["run"]["state"] == "running"


@pytest.mark.parametrize(
    ("field", "value", "code", "status_code"),
    [
        ("app_id", "other.app", "agent_skill_runtime_unavailable", 503),
        ("agent_id", "PADIENT-NOT-CANONICAL", "invalid_agent_selection", 400),
        ("agent_id", "agent:acme:unknown@1", "tool_agent_not_bound", 403),
        ("run_id", "arun_not-hex", "invalid_agent_run_id", 400),
        ("run_id", "run-1", "invalid_agent_run_id", 400),
    ],
)
async def test_status_rejects_unauthorized_or_malformed_targets(
    harness, field, value, code, status_code
):
    harness.seed()
    service = harness.service().service
    payload = _control(run_id=RUN_1)
    payload[field] = value

    response = await service.status_payload(payload)

    assert response.status_code == status_code, response.body
    assert response.body["error"]["code"] == code


@pytest.mark.parametrize("extra", [{"subject_id": SUBJECT_ID}, {"authorization": {}}])
async def test_status_rejects_caller_supplied_authority(harness, extra):
    harness.seed()
    service = harness.service().service

    response = await service.status_payload(_control(run_id=RUN_1, **extra))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "caller_agent_authority_not_allowed"


async def test_foreign_owner_and_unknown_run_are_indistinguishable(harness):
    other = "arun_" + "2" * 32
    harness.seed(run_id=other, owner_scope=OTHER_OWNER_SCOPE)
    service = harness.service().service

    foreign = await service.status_payload(_control(run_id=other))
    missing = await service.status_payload(_control(run_id="arun_" + "3" * 32))
    foreign_cancel = await service.cancel_running_payload(_control(run_id=other))

    for response in (foreign, missing, foreign_cancel):
        assert response.status_code == 404
        assert response.body["error"]["code"] == "agent_run_not_found"
    assert harness.row(other)["status"] == "running"


async def test_status_requires_the_durable_ledger(harness):
    harness.seed()
    service = Fixture().service  # no D1 ledger composed

    response = await service.status_payload(_control(run_id=RUN_1))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_run_lease_unavailable"


# ---------------------------------------------------------------------------
# A. Cancel
# ---------------------------------------------------------------------------


async def test_cancel_before_any_side_effect_is_a_clean_cancel(harness):
    harness.seed(uncertain=0)
    service = harness.service().service

    response = await service.cancel_running_payload(
        _control(run_id=RUN_1, reason="user_cancelled")
    )

    assert response.status_code == 200, response.body
    run = response.body["run"]
    assert run["state"] == "cancelled"
    assert run["changed"] is True
    assert run["dispatch_fenced"] is True
    assert run["requires_reconciliation"] is False
    assert response.body["interrupt_signal"] == "dispatch_fence"
    assert response.body["reason"] == "user_cancelled"
    assert harness.row(RUN_1)["status"] == "cancelled"


async def test_cancel_of_a_running_uncertain_run_is_needs_review_not_rollback(harness):
    harness.seed(uncertain=1, checkpoint_step=1)
    ledger = harness.ledger()
    service = harness.service().service

    response = await service.cancel_running_payload(_control(run_id=RUN_1))

    assert response.status_code == 200, response.body
    run = response.body["run"]
    assert run["state"] == "needs_review"
    assert run["changed"] is True
    assert run["requires_reconciliation"] is True
    assert run["side_effect_uncertain"] is True
    row = harness.row(RUN_1)
    assert row["status"] == "needs_review"
    assert row["side_effect_uncertain"] == 1
    assert row["checkpoint_step"] == 1
    # The fence is real: the fenced worker can no longer claim a dispatch.
    handle = AgentRunLease(RUN_1, OWNER_SCOPE, FP, WORKER, 1)
    assert await ledger.is_active(handle) is False
    assert await ledger.begin_execution(handle) is False


async def test_cancel_keeps_awaiting_approval_semantics_used_by_pause_flow(harness):
    harness.seed(status="awaiting_approval", uncertain=1, checkpoint_step=1, epoch=2)
    service = harness.service().service

    response = await service.cancel_running_payload(_control(run_id=RUN_1))

    assert response.status_code == 200, response.body
    assert response.body["run"]["state"] == "cancelled"
    assert response.body["run"]["changed"] is True
    assert harness.row(RUN_1)["status"] == "cancelled"


async def test_cancel_retry_is_idempotent(harness):
    harness.seed(uncertain=0)
    service = harness.service().service

    first = await service.cancel_running_payload(_control(run_id=RUN_1))
    second = await service.cancel_running_payload(_control(run_id=RUN_1))

    assert (first.status_code, first.body["run"]["changed"]) == (200, True)
    assert second.status_code == 200, second.body
    assert second.body["run"]["state"] == "cancelled"
    assert second.body["run"]["changed"] is False
    assert harness.row(RUN_1)["epoch"] == 2  # exactly one fence increment


async def test_cancel_after_completion_does_not_overwrite_the_terminal_state(harness):
    harness.seed(uncertain=1, checkpoint_step=1)
    ledger = harness.ledger()
    handle = AgentRunLease(RUN_1, OWNER_SCOPE, FP, WORKER, 1)
    assert await ledger.finish(handle, state="completed")
    service = harness.service().service

    response = await service.cancel_running_payload(_control(run_id=RUN_1))

    assert response.status_code == 409, response.body
    assert response.body["error"]["code"] == "agent_run_already_terminal"
    assert response.body["error"]["metadata"]["run_state"] == "completed"
    assert harness.row(RUN_1)["status"] == "completed"


async def test_cancel_failure_fails_closed_without_a_false_claim(harness):
    harness.seed()
    service = harness.service().service
    # A D1 read failure must never be reported as a successful cancel.
    harness.db.execute("DROP TABLE padiem_engine_agent_runs_v1")

    response = await service.cancel_running_payload(_control(run_id=RUN_1))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_run_lease_unavailable"
    assert response.body["error"]["metadata"]["operation"] == "cancel"


# ---------------------------------------------------------------------------
# A. In-flight run: cancel reaches the real Core execution path
# ---------------------------------------------------------------------------


async def test_running_cancel_fences_the_inflight_run_with_a_truthful_response(harness):
    gate = asyncio.Event()
    fx = harness.service(fixture=Fixture(handler_gate=gate))

    run_task = asyncio.ensure_future(fx.service.run_payload(fx.payload()))
    # Let the run reach the parked external Tool: it is genuinely in flight and
    # has already crossed the pre-dispatch side-effect boundary.
    row = None
    for _ in range(500):
        await asyncio.sleep(0)
        row = harness.db.execute(
            "SELECT run_id,status,side_effect_uncertain FROM padiem_engine_agent_runs_v1"
        ).fetchone()
        if fx.handler_started and row is not None and row["side_effect_uncertain"] == 1:
            break
    assert fx.handler_started is True
    assert row is not None and row["side_effect_uncertain"] == 1
    assert fx.handler_calls == 0  # parked inside the Tool, not yet returned
    run_id = row["run_id"]

    cancelled = await fx.service.cancel_running_payload(_control(run_id=run_id))
    assert cancelled.status_code == 200, cancelled.body
    assert cancelled.body["run"]["state"] == "needs_review"
    assert cancelled.body["run"]["requires_reconciliation"] is True

    gate.set()
    result = await asyncio.wait_for(run_task, timeout=10)
    # The in-flight caller is told the truth: cancelled, not a successful run.
    assert result.status_code == 409, result.body
    assert result.body["error"]["code"] == "agent_run_cancelled"
    assert result.body["error"]["metadata"]["run_id"] == run_id
    assert fx.handler_calls == 1  # the already-dispatched Tool is never replayed
    assert fx.provider.calls == 0
    assert harness.row(run_id)["status"] == "needs_review"


async def test_completed_run_is_reported_completed_to_the_caller(harness):
    fx = harness.service()

    response = await fx.service.run_payload(fx.payload())

    assert response.status_code == 200, response.body
    run_id = dict(harness.db.execute(
        "SELECT run_id FROM padiem_engine_agent_runs_v1"
    ).fetchone())["run_id"]
    status_response = await fx.service.status_payload(_control(run_id=run_id))
    assert status_response.status_code == 200
    assert status_response.body["run"]["state"] == "completed"
    assert status_response.body["run"]["dispatch_fenced"] is True
    # A completed run is authoritative: no reconciliation is demanded.
    assert status_response.body["run"]["requires_reconciliation"] is False


# ---------------------------------------------------------------------------
# B. Expired-lease recovery
# ---------------------------------------------------------------------------


async def test_recovery_is_disabled_unless_the_deployment_gate_is_on(harness):
    harness.seed(lease_seconds=-1.0)
    service = harness.service(recovery_enabled=False).service

    response = await service.recovery_payload({"app_id": APP_ID, "agent_id": AGENT_ID})

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_run_recovery_unavailable"
    assert harness.row(RUN_1)["status"] == "running"


async def test_recovery_sweeps_only_expired_running_leases_in_owner_scope(harness):
    rows = {
        "1": ("running", -1.0, 1),      # expired running -> needs_review
        "2": ("running", 120.0, 0),     # live lease -> untouched
        "3": ("completed", -1.0, 1),    # terminal states -> untouched
        "4": ("cancelled", -1.0, 1),
        "5": ("failed", -1.0, 1),
        "6": ("needs_review", -1.0, 1),
    }
    for digit, (status, lease, uncertain) in rows.items():
        harness.seed(run_id="arun_" + digit * 32, status=status,
                     lease_seconds=lease, uncertain=uncertain)
    other = "arun_" + "8" * 32
    harness.seed(run_id=other, owner_scope=OTHER_OWNER_SCOPE, lease_seconds=-1.0)
    service = harness.service(recovery_enabled=True).service

    response = await service.recovery_payload({"app_id": APP_ID, "agent_id": AGENT_ID})

    assert response.status_code == 200, response.body
    assert response.body["recovery"] == {
        "mode": "expired_leases",
        "dry_run": False,
        "expired_seen": 1,
        "quarantined": 1,
        "limit": 500,
        "auto_replay": False,
        "tool_re_execution": False,
    }
    quarantined = harness.row("arun_" + "1" * 32)
    assert quarantined["status"] == "needs_review"
    assert quarantined["side_effect_uncertain"] == 1
    assert harness.row("arun_" + "2" * 32)["status"] == "running"
    assert harness.row("arun_" + "3" * 32)["status"] == "completed"
    assert harness.row("arun_" + "4" * 32)["status"] == "cancelled"
    assert harness.row("arun_" + "5" * 32)["status"] == "failed"
    assert harness.row("arun_" + "6" * 32)["status"] == "needs_review"
    # Another owner's expired run is never touched by this caller's sweep.
    assert harness.row(other)["status"] == "running"


async def test_recovery_dry_run_previews_without_mutating(harness):
    harness.seed(lease_seconds=-1.0)
    service = harness.service(recovery_enabled=True).service

    response = await service.recovery_payload(
        {"app_id": APP_ID, "agent_id": AGENT_ID, "dry_run": True}
    )

    assert response.status_code == 200, response.body
    assert response.body["recovery"]["dry_run"] is True
    assert response.body["recovery"]["expired_seen"] == 1
    assert response.body["recovery"]["quarantined"] == 0
    assert harness.row(RUN_1)["status"] == "running"


async def test_recovery_is_repeat_safe_and_never_touches_a_heartbeat_extension(harness):
    ledger = harness.ledger()
    live = "arun_" + "7" * 32
    handle = await ledger.start(
        run_id=live, owner_scope=OWNER_SCOPE, request_fingerprint=FP,
        worker_id=WORKER, lease_seconds=60,
    )
    harness.clock.tick(59)
    assert await ledger.heartbeat(handle, lease_seconds=60)  # race: renewed first
    harness.clock.tick(2)
    service = harness.service(recovery_enabled=True).service

    first = await service.recovery_payload({"app_id": APP_ID, "agent_id": AGENT_ID})
    second = await service.recovery_payload({"app_id": APP_ID, "agent_id": AGENT_ID})

    assert first.body["recovery"]["expired_seen"] == 0
    assert first.body["recovery"]["quarantined"] == 0
    assert second.body["recovery"]["quarantined"] == 0
    assert harness.row(live)["status"] == "running"
    assert await ledger.is_active(handle) is True


async def test_recovery_failure_is_a_bounded_error_not_a_silent_success(harness):
    harness.seed(lease_seconds=-1.0)
    service = harness.service(recovery_enabled=True).service
    harness.db.execute("DROP TABLE padiem_engine_agent_runs_v1")

    response = await service.recovery_payload({"app_id": APP_ID, "agent_id": AGENT_ID})

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_run_lease_unavailable"
    assert response.body["error"]["metadata"] == {
        "operation": "expired_lease_sweep",
        "reason": "d1_unavailable",
    }


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"app_id": APP_ID}, "invalid_request"),
        ({"app_id": APP_ID, "agent_id": AGENT_ID, "dry_run": "yes"}, "invalid_request"),
        ({"app_id": APP_ID, "agent_id": AGENT_ID, "limit": 5}, "invalid_request"),
        ({"app_id": "other.app", "agent_id": AGENT_ID}, "agent_skill_runtime_unavailable"),
    ],
)
async def test_recovery_rejects_unauthorized_or_malformed_requests(harness, payload, code):
    service = harness.service(recovery_enabled=True).service

    response = await service.recovery_payload(payload)

    assert response.status_code in (400, 503)
    assert response.body["error"]["code"] == code


async def test_recovery_never_dispatches_agent_or_provider_work(harness):
    harness.seed(lease_seconds=-1.0, uncertain=1)
    fx = harness.service(recovery_enabled=True)

    response = await fx.service.recovery_payload({"app_id": APP_ID, "agent_id": AGENT_ID})

    assert response.status_code == 200, response.body
    assert response.body["recovery"]["quarantined"] == 1
    assert fx.handler_calls == 0  # no Tool re-execution
    assert fx.provider.calls == 0  # no model/provider dispatch
    assert harness.row(RUN_1)["status"] == "needs_review"


async def test_sweep_limit_is_bounded(harness):
    ledger = harness.ledger()
    for limit in (0, -1, 2_001, True, 1.5):
        with pytest.raises(AgentDurableLeaseError):
            await ledger.quarantine_expired(limit=limit)
    with pytest.raises(AgentDurableLeaseError):
        await ledger.quarantine_expired(limit=1, owner_scope="not-a-trusted-scope")
