"""#2833 — where the Claw scheduler runs, that it really runs, and that it runs once.

실측 위치 (source truth, 2026-10-29):

- 트리거: Cloudflare Cron Trigger → `worker.py` 의 `Default.scheduled(event, env, ctx)`.
  `wrangler.toml` 에는 `[triggers] crons` 가 **없다** — 운영 크론 등록은 아직 꺼져 있고
  `PRODUCTION_CRON_ACTIVATION = False`,
  `PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED = "false"` 다.
- 실행: `worker.run_scheduled_automation_source(env)` → 워크스페이스 발견
  (`ClawAutomationDueWorkspaceDiscovery`) → 트리거 경계(`ClawAutomationTriggerBoundary`)
  → `compose_scheduled_automation_execution` (D1 클레임 → 실행 → 이력/Task-Alert 투영).
- 중복 방지 권한: `occurrence_key` + `PENDING -> RUNNING` 조건부 UPDATE 하나
  (`D1ClawAutomationStore.claim_execution`).

이 파일이 새로 고정하는 것 (기존 #2851/#2995 테스트가 비워 둔 부분):

1. 같은 발생(occurrence)에 대한 **두 번의 크론 틱**은 실행을 두 번 만들지 않는다 —
   스케줄러 진입점(`run_scheduled_automation_source`) 수준에서.
2. **동시에 시작된 두 클레임**은 정확히 하나만 이긴다.
3. `Default.scheduled` 가 실제로 그 체인을 호출한다 (소스 계약; 기존 테스트는
   `async def scheduled` 문자열의 존재만 확인했다).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from kagent.claw_automation import ClawScheduledRunStatus

from app.claw_automation_store import D1ClawAutomationStore
from test_claw_automation_async_composition_seam import (
    _load_worker,
    _route_db,
    _run_worker_source,
    _worker_env,
)
from test_claw_automation_background_execution import (
    NOW,
    WORKSPACE,
    OutcomeAdapter,
    RecordingHistoryStore,
    RecordingTaskAlertStore,
    make_rule,
    resolver,
)
import test_claw_automation_d1_store as d1mod

_CHAT = Path(__file__).resolve().parents[1]


def _d1_store() -> D1ClawAutomationStore:
    """The store's own D1 double, with the store's own fixtures."""
    binding = d1mod.SqliteD1Binding()
    d1mod._apply_migrations(binding)
    return D1ClawAutomationStore(binding)


async def test_two_cron_ticks_of_the_same_occurrence_execute_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 시각의 두 번째 크론 틱은 실행을 만들지 않는다 (스케줄러 레벨 중복 방지)."""
    db = _route_db()
    store = D1ClawAutomationStore(db)
    await store.save_rule(make_rule())
    adapter = OutcomeAdapter()

    first = await _run_worker_source(db, adapter, monkeypatch)
    second = await _run_worker_source(db, adapter, monkeypatch)

    assert first is not None and first.executions, "the first tick must really execute"
    assert len(adapter.calls) == 1, adapter.calls
    assert sum(len(receipt.terminal_run_ids) for receipt in first.executions) == 1

    # The second tick of the same instant claims nothing and dispatches nothing.
    assert second is not None
    for receipt in second.executions:
        assert receipt.newly_claimed_run_ids == ()
        assert receipt.execution_claimed_run_ids == ()
        assert receipt.terminal_run_ids == ()
        assert receipt.failed_before_dispatch_run_ids == ()
        assert receipt.dispatch_failed_run_ids == ()
    assert len(adapter.calls) == 1, adapter.calls

    rows = await store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.COMPLETED]
    assert len(rows) == 1


async def test_the_scheduled_lane_runs_the_whole_existing_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 번의 크론 틱이 실행·이력·Task-Alert 투영까지 실제로 만든다."""
    db = _route_db()
    store = D1ClawAutomationStore(db)
    await store.save_rule(make_rule())
    adapter = OutcomeAdapter()
    history = RecordingHistoryStore()
    task_alert = RecordingTaskAlertStore()

    module = _load_worker(monkeypatch)
    receipt = await module.run_scheduled_automation_source(
        _worker_env(db),
        now=NOW,
        execution_ports=SimpleNamespace(
            adapter=adapter,
            owner_resolver=resolver(),
            history_store=history,
            task_alert_store=task_alert,
        ),
    )

    assert receipt is not None
    assert len(adapter.calls) == 1
    assert len(receipt.executions) == 1
    execution = receipt.executions[0]
    assert len(execution.terminal_run_ids) == 1
    public = execution.safe_dict()
    assert public["provider_calls"] == 0
    assert public["external_sends"] == 0
    assert public["connector_writes"] == 0
    assert public["production_mutation"] == 0
    assert history.rows, "the run must be projected into Claw run history"
    assert len(await store.list_runs(WORKSPACE)) == 1


async def test_concurrent_claims_let_exactly_one_win() -> None:
    """동시에 시작된 두 클레임 중 정확히 하나만 RUNNING 을 얻는다."""
    store = _d1_store()
    await store.save_rule(d1mod.make_rule())
    run = d1mod.scheduled_run()
    await store.record_run(run)

    async def claim():
        return await store.claim_execution(
            run_id=run.run_id,
            workspace_id=d1mod.WORKSPACE,
            rule_id=d1mod.RULE_ID,
            scheduled_time=d1mod.NOW,
        )

    pair = await asyncio.gather(claim(), claim())

    winners = [item for item in pair if item is not None]
    assert len(winners) == 1, pair
    assert winners[0].status is ClawScheduledRunStatus.RUNNING
    reread = await store.get_run(run.run_id, d1mod.WORKSPACE)
    assert reread is not None and reread.status is ClawScheduledRunStatus.RUNNING


# --------------------------------------------------------------------------
# #2833 — store / identity / discovery 주입 seam
#
# 스케줄러 진입점이 Worker 바인딩을 직접 읽는 탓에, 한 번 실행·중복 방지를 다른
# store·identity 구현으로 확인하려면 env 전체를 흔들어야 했다. 이제 세 가지를
# 키워드로 주입할 수 있고, 주입하지 않으면 예전 그대로 바인딩에서 만든다.
# --------------------------------------------------------------------------


class _CountingDiscovery:
    """An injected discovery: the real one, plus a call counter.

    The seam's point is that the caller's object runs — and that the claim and
    dedup authority underneath it does not move.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0

    async def aadiscover_and_trigger(self, *, now):
        self.calls += 1
        return await self._inner.aadiscover_and_trigger(now=now)


class _IdentityBindingDouble:
    """인증 평면 대역. 주입된 identity authority가 이것을 읽는다."""

    def __init__(self) -> None:
        self.calls = 0

    async def resolve_active_tenant_membership(self, payload: dict):
        self.calls += 1
        return {
            "ok": True,
            "membership": {
                "tenant_id": payload["tenant_id"],
                "canonical_subject_id": payload["canonical_subject_id"],
                "state": "active",
                "created_at": "2025-01-01T00:00:00+00:00",
                "role": "owner",
            },
        }


def _injected_tick(db, monkeypatch: pytest.MonkeyPatch):
    """Only the enable flag in env: store, identity and discovery are injected."""
    from app.claw_automation_due_workspace_discovery import (
        compose_canonical_due_workspace_discovery,
    )
    from kagent.claw_automation_trigger import (
        ClawAutomationTickRuntime,
        ClawAutomationTriggerBoundary,
    )

    from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority

    store = D1ClawAutomationStore(db)
    identity_binding = _IdentityBindingDouble()
    identity = CloudflareControlPlaneIdentityAuthority(identity_binding)
    boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))
    discovery = _CountingDiscovery(
        compose_canonical_due_workspace_discovery(
            automation_store=store,
            control_plane_identity_authority=identity,
            trigger_boundary=boundary,
        )
    )
    adapter = OutcomeAdapter()
    history = RecordingHistoryStore()

    async def tick():
        module = _load_worker(monkeypatch)
        return await module.run_scheduled_automation_source(
            SimpleNamespace(**{"PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": True}),
            now=NOW,
            execution_ports=SimpleNamespace(
                adapter=adapter,
                owner_resolver=resolver(),
                history_store=history,
                task_alert_store=RecordingTaskAlertStore(),
            ),
            automation_store=store,
            identity_authority=identity,
            discovery=discovery,
        )

    return store, identity_binding, discovery, adapter, history, tick


async def test_injected_store_and_identity_run_the_lane_without_worker_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _route_db()
    store, identity_binding, discovery, adapter, history, tick = _injected_tick(db, monkeypatch)
    await store.save_rule(make_rule())

    receipt = await tick()

    assert receipt is not None, "the injected tick must run, not fall back to None"
    assert discovery.calls == 1, "the injected discovery is the one that ran"
    assert identity_binding.calls >= 1, "the injected identity authority answered membership"
    assert len(adapter.calls) == 1, adapter.calls
    assert len(receipt.executions) == 1
    assert len(receipt.executions[0].terminal_run_ids) == 1
    assert history.rows, "the run is still projected into Claw run history"
    rows = await store.list_runs(WORKSPACE)
    assert [row.status for row in rows] == [ClawScheduledRunStatus.COMPLETED]


async def test_the_injected_tick_does_not_double_run_the_same_occurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _route_db()
    store, _identity_binding, discovery, adapter, _history, tick = _injected_tick(db, monkeypatch)
    await store.save_rule(make_rule())

    first = await tick()
    second = await tick()

    assert first is not None and len(first.executions) == 1
    assert second is not None
    # The second tick of the same instant claims nothing: dedup stayed with the
    # store's occurrence claim, not with the injected objects.
    for receipt in second.executions:
        assert receipt.newly_claimed_run_ids == ()
        assert receipt.execution_claimed_run_ids == ()
        assert receipt.terminal_run_ids == ()
    assert discovery.calls == 2, "both ticks reached the injected discovery"
    assert len(adapter.calls) == 1, adapter.calls
    assert len(await store.list_runs(WORKSPACE)) == 1


async def test_the_enable_flag_still_gates_an_injected_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _route_db()
    store, _identity_binding, discovery, adapter, _history, _tick = _injected_tick(db, monkeypatch)
    await store.save_rule(make_rule())

    module = _load_worker(monkeypatch)
    from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority

    off = await module.run_scheduled_automation_source(
        SimpleNamespace(**{"PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "false"}),
        now=NOW,
        automation_store=store,
        identity_authority=CloudflareControlPlaneIdentityAuthority(_IdentityBindingDouble()),
        discovery=discovery,
    )

    assert off is None, "the switch still decides whether the lane runs at all"
    assert discovery.calls == 0
    assert adapter.calls == []


async def test_without_injection_the_lane_still_needs_the_worker_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기본 경로는 그대로다: 바인딩도 주입도 없으면 아무 것도 하지 않는다."""

    module = _load_worker(monkeypatch)
    receipt = await module.run_scheduled_automation_source(
        SimpleNamespace(**{"PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": True}),
        now=NOW,
    )

    assert receipt is None


def test_the_cron_entrypoint_calls_the_automation_lane() -> None:
    """`Default.scheduled` 가 그 체인을 호출한다는 소스 계약 (문자열 존재보다 강하게)."""
    source = (_CHAT / "worker.py").read_text(encoding="utf-8")
    start = source.index("class Default(WorkerEntrypoint):")
    end = source.index("async def fetch", start)
    scheduled_body = source[start:end]

    assert "async def scheduled" in scheduled_body
    assert "run_scheduled_automation_source(env)" in scheduled_body
    assert "await" in scheduled_body

    # The platform trigger is not registered in this repository's configuration.
    wrangler = (_CHAT / "wrangler.toml").read_text(encoding="utf-8")
    assert "[triggers]" not in wrangler
    assert "crons" not in wrangler.lower()
