"""#6919: a PC answer no longer waits for its metrics row to be delivered.

Every PC turn on 2026-11-05 held its answer for the reporter's full 5 s window
while the ledger did not answer (``pc_work_metrics_delivery status=unavailable``
exactly 5.0 s after the handler finished). The answer now waits a short grace
and the delivery finishes in the background; a quick delivery still completes
before the answer leaves, and a failure is still logged without its text.
"""
from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy

import pytest

from app import orchestration_service as module
from app.orchestration_service import OrchestrationEngineService
from app.pc_work_metrics import current_pc_work_metrics
from tests.test_orchestration_service import MockEngineRuntime, _pc_turn_payload


def _service(report):
    return OrchestrationEngineService(
        runtime_factory=lambda _: MockEngineRuntime(), b14_service_bound=True,
        pc_work_metrics_reporter=report,
    )


@pytest.mark.asyncio
async def test_a_slow_delivery_does_not_hold_the_answer():
    reports: list = []

    async def slow_report(value):
        await asyncio.sleep(1.0)              # the ledger that answers late
        reports.append(deepcopy(value))

    service = _service(slow_report)
    started = time.monotonic()
    result = await service.orchestrate_payload(_pc_turn_payload())
    elapsed = time.monotonic() - started

    assert result.status_code == 200
    assert elapsed < 0.9, elapsed              # the answer left at the grace, not after 1 s
    assert reports == []                       # delivery still in flight
    assert current_pc_work_metrics() is None   # the request's collector is already reset
    await service.drain_pc_work_metrics()
    assert len(reports) == 1                   # and it still arrives, complete
    assert reports[0]["metrics"]["outcome"] == "completed"


@pytest.mark.asyncio
async def test_a_quick_delivery_still_completes_before_the_answer_leaves():
    reports: list = []

    async def report(value):
        reports.append(deepcopy(value))

    service = _service(report)
    result = await service.orchestrate_payload(_pc_turn_payload())
    assert result.status_code == 200
    assert len(reports) == 1
    assert not service._pc_work_metrics_tasks


@pytest.mark.asyncio
async def test_a_late_failure_is_logged_without_its_text(caplog):
    async def late_failure(value):
        await asyncio.sleep(0.6)
        raise RuntimeError("PRIVATE_METRICS_SENTINEL")

    service = _service(late_failure)
    caplog.set_level(logging.INFO)
    result = await service.orchestrate_payload(_pc_turn_payload())
    assert result.status_code == 200
    assert "pc_work_metrics_delivery_deferred" in caplog.text
    await service.drain_pc_work_metrics()
    assert "pc_work_metrics_report_failed" in caplog.text
    assert "PRIVATE_METRICS_SENTINEL" not in caplog.text
    assert not service._pc_work_metrics_tasks


def test_the_grace_is_short_against_both_ceilings():
    # The reporter's own window is 5 s; the answer must not inherit it.
    from app.pc_work_metrics_reporter import DELIVERY_SECONDS
    assert module.PC_WORK_METRICS_ANSWER_GRACE_SECONDS < 1.0 < DELIVERY_SECONDS
