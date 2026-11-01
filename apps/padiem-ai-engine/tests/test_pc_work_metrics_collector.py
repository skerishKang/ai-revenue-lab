"""Measure accepted handlers/dispatches without altering their execution."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.pc_work_metrics import (
    PcWorkMetricsCollector, current_pc_work_metrics, observe_pc_handler,
    observe_pc_transport, reset_pc_work_metrics, set_pc_work_metrics,
)
from padiem_ai_core.contracts import UsageMetadata
from padiem_ai_core.pc_work_metrics import PcWorkMetricsError, validate_pc_work_metrics


TURN = "pcturn_" + "a" * 64
TOOL = "claw.pc.read_file"


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    async def text(self):
        return json.dumps(self.data)


def request_factory(url, **kwargs):
    del url
    request = SimpleNamespace(**kwargs)
    request.js_object = request
    return request


def test_one_dispatch_is_one_pc_round_trip_regardless_of_polls_and_replay():
    async def scenario():
        collector = PcWorkMetricsCollector(TURN)
        token = set_pc_work_metrics(collector)
        calls = []

        class Service:
            async def fetch(self, request):
                body = json.loads(request.body)
                calls.append(body["mode"])
                return Response({"ok": True, "dispatch": {
                    "dispatch_id": "private-dispatch", "run_id": "private-run", "kind": "read",
                    "state": "done" if body["mode"] == "result" else "pending",
                }})

        service, factory = observe_pc_transport(Service(), request_factory)

        async def handler(arguments):
            for mode in ["context", "dispatch", "command_status", "command_status", "result"]:
                request = factory("https://test", body=json.dumps({
                    "mode": mode, "op": "read", "run_id": "private-run",
                    "dispatch_id": "private-dispatch", **arguments,
                }))
                response = await service.fetch(request.js_object)
                await response.text()
            return {"output": "private content", "content_bytes": 15}

        observed = observe_pc_handler(handler, tool_id=TOOL)
        try:
            await observed({"path": "private-path"})
            await observed({"path": "private-path"})
            collector.finish("completed", "completed")
            result = collector.snapshot()
        finally:
            reset_pc_work_metrics(token)
        assert len(calls) == 10
        assert result["calls"] == 2
        assert result["pc_round_trips"] == 1
        assert result["tool_calls"][TOOL]["pc_round_trips"] == 1
        assert "private" not in json.dumps(result)

    asyncio.run(scenario())


def test_denied_dispatch_and_context_are_not_round_trips():
    async def scenario():
        collector = PcWorkMetricsCollector(TURN)
        token = set_pc_work_metrics(collector)

        class Service:
            async def fetch(self, request):
                return Response({"ok": False, "dispatch": {
                    "dispatch_id": "not-admitted", "run_id": "run", "kind": "read"}})

        service, factory = observe_pc_transport(Service(), request_factory)

        async def handler(arguments):
            response = await service.fetch(factory("https://test", body=json.dumps({
                "mode": "dispatch", "op": "read", "run_id": "run"})).js_object)
            await response.text()
            return {"ok": False}

        try:
            await observe_pc_handler(handler, tool_id=TOOL)({})
            assert collector.snapshot()["pc_round_trips"] == 0
        finally:
            reset_pc_work_metrics(token)
    asyncio.run(scenario())


def test_known_and_unknown_truncation_are_separate_and_never_inferred_from_refusal():
    async def scenario():
        collector = PcWorkMetricsCollector(TURN)
        token = set_pc_work_metrics(collector)

        async def handler(value):
            return value

        observed = observe_pc_handler(handler, tool_id=TOOL)
        try:
            await observed({"truncated": True, "original_bytes": 200, "emitted_bytes": 80})
            await observed({"truncated": True, "content_bytes": 25})
            await observed({"termination": "output_too_large"})
            result = collector.snapshot()
        finally:
            reset_pc_work_metrics(token)
        assert result["calls"] == 3
        assert result["truncation_count"] == 2
        assert result["truncated_bytes_known"] == 120
        assert result["truncated_bytes_unknown_count"] == 1
        assert result["truncated_bytes"] is None
    asyncio.run(scenario())


def test_timeout_counted_once_and_cancel_is_distinct():
    async def scenario():
        collector = PcWorkMetricsCollector(TURN)
        token = set_pc_work_metrics(collector)

        class Service:
            async def fetch(self, request):
                raise TimeoutError("private endpoint diagnostics")

        service, factory = observe_pc_transport(Service(), request_factory)

        async def timeout(arguments):
            return await service.fetch(factory("https://test", body="{}").js_object)

        async def cancelled(arguments):
            raise asyncio.CancelledError()

        try:
            with pytest.raises(TimeoutError):
                await observe_pc_handler(timeout, tool_id=TOOL)({})
            with pytest.raises(asyncio.CancelledError):
                await observe_pc_handler(cancelled, tool_id=TOOL)({})
            assert collector.snapshot()["timeout_count"] == 1
            assert collector.snapshot()["calls"] == 2
        finally:
            reset_pc_work_metrics(token)
    asyncio.run(scenario())


def test_body_timeout_is_measured_before_signed_helper_converts_it():
    from app.claw_pc_query_step_driver import _pc_observing_handler
    from kagent.pc_query_adapter import signed_chat_call

    async def scenario():
        collector = PcWorkMetricsCollector(TURN)
        token = set_pc_work_metrics(collector)

        class BodyTimeout:
            status = 200

            async def text(self):
                raise TimeoutError("private response diagnostics")

        class Service:
            async def fetch(self, request):
                return BodyTimeout()

        service, factory = observe_pc_transport(Service(), request_factory)

        async def handler(arguments):
            return await signed_chat_call(
                service=service, request_factory=factory, secret="test-only-" * 4,
                subject_id="test-owner", run_id="test-run", mode="dispatch",
            )

        try:
            result = await _pc_observing_handler(handler, tool_id="claw.pc.query_drives")({})
            assert result["stage"] == "pc_query_unavailable"
            metrics = collector.snapshot()
            assert metrics["calls"] == 1
            assert metrics["pc_round_trips"] == 0
            assert metrics["timeout_count"] == 1
        finally:
            reset_pc_work_metrics(token)
    asyncio.run(scenario())


def test_model_estimates_share_basis_and_provider_usage_never_becomes_zero():
    collector = PcWorkMetricsCollector(TURN)
    observations = [{"output": "한글 private body"}]
    messages = [{"role": "user", "content": "data:" + json.dumps(observations, ensure_ascii=False)}]
    first = collector.model_start(messages=messages, tool_results=observations)
    collector.model_finish(first, usage=UsageMetadata(input_tokens=100))
    collector.model_finish(first, usage=UsageMetadata(input_tokens=999))
    collector.model_start(messages=messages, tool_results=observations)
    result = collector.snapshot()
    assert result["model_calls"] == 2
    assert result["model_input_tokens"] is None
    assert result["model_input_tokens_observed"] == 100
    assert result["model_input_tokens_missing_calls"] == 1
    assert result["tool_result_input_ratio"] == (
        result["tool_result_tokens_estimated"] / result["model_input_tokens_estimated"])
    assert "private" not in json.dumps(result)


def test_finalization_is_immutable_and_confirmation_is_normal_terminal():
    collector = PcWorkMetricsCollector(TURN)
    collector.mark_confirmation_required()
    collector.finish("completed", "completed")
    first = collector.snapshot()
    collector.finish("failed", "execution_failed")
    assert collector.snapshot() == first
    assert first["calls"] == first["pc_round_trips"] == 0
    assert first["outcome"] == "confirmation_required"


@pytest.mark.parametrize("reason", ["tool_failed", "tool_timeout", "model_failed", "model_timeout"])
def test_completed_terminal_retains_observed_failure_reason(reason):
    collector = PcWorkMetricsCollector(TURN)
    collector.mark_failure(reason)
    collector.finish("completed", "completed")
    assert collector.snapshot()["outcome"] == "completed"
    assert collector.snapshot()["outcome_reason"] == reason


def test_confirmation_and_noncompleted_terminals_keep_their_own_reason():
    collector = PcWorkMetricsCollector(TURN)
    collector.mark_failure("tool_timeout")
    collector.mark_confirmation_required()
    collector.finish("completed", "completed")
    assert collector.snapshot()["outcome"] == "confirmation_required"
    assert collector.snapshot()["outcome_reason"] == "confirmation_required"
    cancelled = PcWorkMetricsCollector(TURN)
    cancelled.mark_failure("tool_failed")
    cancelled.finish("cancelled", "cancelled")
    assert cancelled.snapshot()["outcome_reason"] == "cancelled"
    failed = PcWorkMetricsCollector(TURN)
    failed.mark_failure("model_timeout")
    failed.finish("failed", "execution_failed")
    assert failed.snapshot()["outcome_reason"] == "model_timeout"
    explicit = PcWorkMetricsCollector(TURN)
    explicit.mark_failure("model_timeout")
    explicit.finish("failed", "tool_failed")
    assert explicit.snapshot()["outcome_reason"] == "tool_failed"


def test_concurrent_turns_have_isolated_collectors_and_restore_parent():
    async def turn(digit, count):
        collector = PcWorkMetricsCollector("pcturn_" + digit * 64)
        token = set_pc_work_metrics(collector)

        async def handler(value):
            await asyncio.sleep(0)
            assert current_pc_work_metrics() is collector
            return value

        try:
            for _ in range(count):
                await observe_pc_handler(handler, tool_id=TOOL)({})
            return collector.snapshot()["calls"]
        finally:
            reset_pc_work_metrics(token)

    async def scenario():
        assert await asyncio.gather(turn("a", 1), turn("b", 3)) == [1, 3]
        assert current_pc_work_metrics() is None
    asyncio.run(scenario())


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(path="private-file"),
    lambda row: row.update(outcome_reason="private-error"),
    lambda row: row.update(calls=1),
    lambda row: row.update(model_input_tokens=False),
    lambda row: row.update(model_input_tokens_estimated=float("nan")),
    lambda row: row.update(tool_calls={"private-file": {}}),
    lambda row: row.update(turn_id="user@example.com"),
    lambda row: row.update(truncated_bytes=None),
])
def test_validator_rejects_private_fields_and_inconsistent_measurements(mutate):
    row = deepcopy(PcWorkMetricsCollector(TURN).snapshot())
    mutate(row)
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)


def test_lifecycle_events_deduplicate_per_turn_and_freeze_after_finish():
    collector = PcWorkMetricsCollector(TURN)
    for output in ("object-one", "object-one", "object-two", "", None):
        collector.mark_stored_output(output)
    for job in ("job-one", "job-one", "", None):
        collector.mark_background_job(job)
    collector.mark_compaction()
    collector.mark_compaction()
    collector.finish("completed", "completed")
    result = collector.snapshot()
    assert result["schema_version"] == 3
    assert result["stored_output_count"] == 2
    assert result["compaction_count"] == 2
    assert result["background_job_count"] == 1
    assert result["compaction_tokens_saved"] == 0.0
    assert "object-one" not in json.dumps(result)
    assert "job-one" not in json.dumps(result)
    collector.mark_stored_output("late-object")
    collector.mark_background_job("late-job")
    collector.mark_compaction()
    assert collector.snapshot() == result

    another = PcWorkMetricsCollector("pcturn_" + "b" * 64)
    another.mark_stored_output("object-one")
    another.mark_background_job("job-one")
    fresh = another.snapshot()
    assert fresh["stored_output_count"] == fresh["background_job_count"] == 1
    assert fresh["compaction_count"] == 0


def test_legacy_snapshot_remains_unmeasured_instead_of_zero_lifecycle_counters():
    row = PcWorkMetricsCollector(TURN).snapshot()
    row["schema_version"] = 1
    for key in ("stored_output_count", "compaction_count", "background_job_count",
                "compaction_input_tokens_before", "compaction_input_tokens_after",
                "compaction_tokens_saved"):
        row.pop(key)
    assert validate_pc_work_metrics(row) == row


@pytest.mark.parametrize("key", ["stored_output_count", "compaction_count", "background_job_count"])
@pytest.mark.parametrize("invalid", [-1, True, 1.5, "1", None])
def test_lifecycle_counter_schema_rejects_invalid_measurements(key, invalid):
    row = PcWorkMetricsCollector(TURN).snapshot()
    row[key] = invalid
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)


def test_v3_requires_lifecycle_and_compaction_token_counters():
    row = PcWorkMetricsCollector(TURN).snapshot()
    del row["compaction_count"]
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)
    row = PcWorkMetricsCollector(TURN).snapshot()
    row["schema_version"] = 1
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)
    row = PcWorkMetricsCollector(TURN).snapshot()
    del row["compaction_tokens_saved"]
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)


def test_compaction_token_evidence_is_measured_and_internally_consistent():
    collector = PcWorkMetricsCollector(TURN)
    collector.mark_compaction(tokens_before=12000, tokens_after=4200, count=2)
    result = collector.snapshot()
    assert result["compaction_count"] == 2
    assert result["compaction_input_tokens_before"] == 12000.0
    assert result["compaction_input_tokens_after"] == 4200.0
    assert result["compaction_tokens_saved"] == 7800.0
    row = deepcopy(result)
    row["compaction_tokens_saved"] = 1.0
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)
    row = deepcopy(result)
    row["compaction_input_tokens_after"] = 13000.0
    with pytest.raises(PcWorkMetricsError):
        validate_pc_work_metrics(row)


@pytest.mark.parametrize("tool_id", [
    "claw.pc.read_output", "claw.pc.search_output", "claw.pc.start_job",
    "claw.pc.job_status", "claw.pc.job_output", "claw.pc.batch", "claw.pc.recall_context",
])
def test_remote_context_and_job_tools_are_observed(tool_id):
    async def run():
        collector = PcWorkMetricsCollector(TURN)
        token = set_pc_work_metrics(collector)
        async def handler(arguments):
            return {"ok": True}
        try:
            await observe_pc_handler(handler, tool_id=tool_id)({})
            result = collector.snapshot()
        finally:
            reset_pc_work_metrics(token)
        assert result["calls"] == 1
        assert result["tool_calls"][tool_id]["calls"] == 1
    asyncio.run(run())
