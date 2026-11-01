"""Turn-local PC measurements at the shared handler/transport boundary.

Accepted tool handlers are counted once. A PC round trip is a unique accepted
Mesh dispatch, not each context/status/result HTTP request. Post-action checks
inside the same PC command do not add a tool or dispatch. Measurements never
retain arguments, filenames, prompts, results, or exception messages.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
import json
from typing import Any

from padiem_ai_core.pc_work_metrics import (
    PC_METRIC_COUNTERS, PC_METRIC_OUTCOMES, PC_METRIC_REASONS, PC_METRIC_TOOL_IDS,
    validate_pc_work_metrics,
)

_CURRENT: ContextVar[Any] = ContextVar("pc_work_metrics", default=None)
_TOOL: ContextVar[Any] = ContextVar("pc_work_metrics_tool", default=None)


def current_pc_work_metrics():
    return _CURRENT.get()


def set_pc_work_metrics(collector):
    return _CURRENT.set(collector)


def reset_pc_work_metrics(token):
    _CURRENT.reset(token)


def _json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=dict).encode("utf-8"))


class PcWorkMetricsCollector:
    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.ledger_identity = None  # Server identity for the reporter, never in snapshot.
        self._tools: dict[str, dict[str, int]] = {}
        self._dispatches: set[str] = set()
        self._stored_outputs: set[str] = set()
        self._background_jobs: set[str] = set()
        self._batches = 0
        self._batch_steps = 0
        self._compactions = 0
        self._compaction_tokens_before = 0.0
        self._compaction_tokens_after = 0.0
        self._models: list[dict[str, Any]] = []
        self._confirmation = False
        self._failure_reason = None
        self._outcome, self._reason = "running", "in_progress"

    def _tool_start(self, tool_id):
        if self._outcome != "running" or tool_id not in PC_METRIC_TOOL_IDS:
            return None
        row = self._tools.setdefault(tool_id, {key: 0 for key in PC_METRIC_COUNTERS})
        row["calls"] += 1
        return _ToolMeasurement(self, row)

    def model_start(self, *, messages, tools=None, tool_results=None):
        """Count the actual call before dispatch; missing usage stays unknown.

        Both estimates use serialized UTF-8 bytes / 4. The numerator is the
        exact observation value placed in that model call, so repeated result
        context is counted again when it is sent again. Provider usage remains
        separate and is never replaced with this estimate.
        """
        if self._outcome != "running":
            return None
        input_bytes = _json_bytes({"messages": messages, "tools": tools})
        result_bytes = _json_bytes(tool_results) if tool_results else 0
        self._models.append({"input": input_bytes / 4, "results": result_bytes / 4,
                             "usage": None, "finished": False})
        return len(self._models) - 1

    def model_finish(self, call_id, *, usage=None):
        if (self._outcome != "running" or type(call_id) is not int
                or not 0 <= call_id < len(self._models)):
            return
        model = self._models[call_id]
        if model["finished"]:
            return
        model["finished"] = True
        if isinstance(usage, Mapping):
            count = usage.get("input_tokens", usage.get("prompt_tokens"))
        else:
            count = getattr(usage, "input_tokens", None)
        if type(count) is int and count >= 0:
            model["usage"] = count

    def mark_stored_output(self, output_id):
        """Count a successfully stored object once per turn; never report its ID."""
        if self._outcome == "running" and isinstance(output_id, str) and output_id:
            self._stored_outputs.add(output_id)

    def mark_compaction(self, *, tokens_before=None, tokens_after=None, count=1):
        """Called after actual context compaction succeeds.

        `count` is the number of passes that produced the measured before/after
        prompt sizes, so a multi-pass compaction still counts every pass while
        the token sums describe this one prepared turn.
        """
        if self._outcome != "running":
            return
        steps = count if type(count) is int and count > 0 else 1
        self._compactions += steps
        if (type(tokens_before) in {int, float} and type(tokens_after) in {int, float}
                and tokens_before >= 0 and tokens_after >= 0
                and tokens_before >= tokens_after):
            self._compaction_tokens_before += float(tokens_before)
            self._compaction_tokens_after += float(tokens_after)

    def mark_background_job(self, job_id):
        """Count accepted jobs, excluding repeated polling or replay of a job."""
        if self._outcome == "running" and isinstance(job_id, str) and job_id:
            self._background_jobs.add(job_id)

    def mark_batch(self, steps):
        """Count one accepted read batch and the steps it carried.

        The saving is a model turn, not a PC round trip: each step still travels
        to the PC as its own command until the agent understands batches.
        """
        if self._outcome != "running" or type(steps) is not int or steps < 1:
            return
        self._batches += 1
        self._batch_steps += steps

    def mark_confirmation_required(self):
        if self._outcome == "running":
            self._confirmation = True

    def mark_failure(self, reason):
        priorities = {"tool_failed": 1, "model_failed": 2, "tool_timeout": 3, "model_timeout": 4}
        if (self._outcome == "running" and reason in priorities
                and priorities[reason] > priorities.get(self._failure_reason, 0)):
            self._failure_reason = reason

    def finish(self, outcome: str, reason: str):
        if self._outcome != "running":
            return
        if outcome not in PC_METRIC_OUTCOMES or outcome == "running":
            outcome = "failed"
        if reason not in PC_METRIC_REASONS:
            reason = "execution_failed"
        if outcome == "completed" and self._confirmation:
            outcome, reason = "confirmation_required", "confirmation_required"
        elif outcome == "completed" and self._failure_reason is not None:
            # Completion is the structured Engine terminal. Keep an observed
            # failure visible even if a later model answer/retry completes.
            reason = self._failure_reason
        elif outcome == "failed" and reason == "execution_failed" and self._failure_reason is not None:
            reason = self._failure_reason
        self._outcome, self._reason = outcome, reason

    def snapshot(self):
        tools = {tool_id: dict(row) for tool_id, row in sorted(self._tools.items())}
        totals = {key: sum(row[key] for row in tools.values()) for key in PC_METRIC_COUNTERS}
        observed = sum(model["usage"] for model in self._models if model["usage"] is not None)
        missing = sum(model["usage"] is None for model in self._models)
        input_estimate = sum(model["input"] for model in self._models)
        result_estimate = sum(model["results"] for model in self._models)
        saved = self._compaction_tokens_before - self._compaction_tokens_after
        return validate_pc_work_metrics({
            "schema_version": 4, "turn_id": self.turn_id, "tool_calls": tools, **totals,
            "batch_count": self._batches, "batch_steps": self._batch_steps,
            "batch_model_turns_saved": self._batch_steps - self._batches,
            "stored_output_count": len(self._stored_outputs),
            "compaction_count": self._compactions,
            "compaction_input_tokens_before": self._compaction_tokens_before,
            "compaction_input_tokens_after": self._compaction_tokens_after,
            "compaction_tokens_saved": saved,
            "background_job_count": len(self._background_jobs),
            "truncated_bytes": None if totals["truncated_bytes_unknown_count"] else totals["truncated_bytes_known"],
            "model_calls": len(self._models), "model_input_tokens": None if missing else observed,
            "model_input_tokens_observed": observed, "model_input_tokens_missing_calls": missing,
            "model_input_tokens_estimated": input_estimate,
            "tool_result_tokens_estimated": result_estimate,
            "tool_result_input_ratio": result_estimate / input_estimate if input_estimate else None,
            "token_ratio_basis": "utf8_bytes_div4_estimate",
            "outcome": self._outcome, "outcome_reason": self._reason,
        })


@dataclass
class _ToolMeasurement:
    collector: PcWorkMetricsCollector
    row: dict[str, int]
    timed_out: bool = False
    truncated: bool = False

    def timeout(self):
        if self.collector._outcome == "running" and not self.timed_out:
            self.row["timeout_count"] += 1
            self.timed_out = True
            self.collector.mark_failure("tool_timeout")

    def accepted_dispatch(self, dispatch_id):
        if (self.collector._outcome == "running" and isinstance(dispatch_id, str)
                and dispatch_id and dispatch_id not in self.collector._dispatches):
            self.collector._dispatches.add(dispatch_id)
            self.row["pc_round_trips"] += 1

    def result(self, value):
        if self.collector._outcome != "running" or not isinstance(value, Mapping):
            return
        verification = value.get("action_verification")
        if (value.get("ok") is False or value.get("state") == "failed"
                or isinstance(verification, Mapping) and verification.get("status") in ("failed", "unavailable")):
            self.collector.mark_failure("tool_failed")
        if value.get("termination") == "timed_out" or value.get("stage") == "tool_timeout":
            self.timeout()
        # output_too_large may mean a whole result was refused, not cut. Only
        # an explicit truncation flag is evidence that bytes were discarded.
        if value.get("truncated") is not True or self.truncated:
            return
        self.truncated = True
        self.row["truncation_count"] += 1
        original = value.get("original_bytes")
        emitted = value.get("emitted_bytes", value.get("content_bytes"))
        if type(original) is int and type(emitted) is int and original >= emitted >= 0:
            self.row["truncated_bytes_known"] += original - emitted
        else:
            self.row["truncated_bytes_unknown_count"] += 1


def observe_pc_handler(handler, *, tool_id):
    """One shared wrapper around all PC handlers, after existing Core gates."""
    async def observed(arguments):
        collector = current_pc_work_metrics()
        measurement = collector._tool_start(tool_id) if collector is not None else None
        token = _TOOL.set(measurement)
        try:
            result = await handler(arguments)
            if measurement is not None:
                try:
                    measurement.result(result)
                except Exception:
                    pass
            return result
        except asyncio.TimeoutError:
            if measurement is not None:
                measurement.timeout()
            raise
        except Exception:
            if measurement is not None:
                measurement.collector.mark_failure("tool_failed")
            raise
        finally:
            _TOOL.reset(token)
    return observed


@dataclass
class _Request:
    original: Any
    metadata: dict[str, Any]

    @property
    def js_object(self):
        return self

    def __getattr__(self, key):
        return getattr(self.original, key)


class _Response:
    def __init__(self, original, metadata, measurement):
        self._original, self._metadata, self._measurement = original, metadata, measurement

    def __getattr__(self, key):
        return getattr(self._original, key)

    async def text(self):
        try:
            body = await self._original.text()
        except asyncio.TimeoutError:
            if self._measurement is not None:
                self._measurement.timeout()
            raise
        try:
            measurement = self._measurement
            if measurement is None:
                return body
            status = int(self._original.status)
            if status == 504:
                measurement.timeout()
            payload = json.loads(body)
            if status != 200 or not isinstance(payload, Mapping) or payload.get("ok") is not True:
                return body
            row = payload.get("dispatch")
            if (not isinstance(row, Mapping)
                    or row.get("run_id") != self._metadata.get("run_id")):
                return body
            if self._metadata.get("mode") == "dispatch":
                expected_kind = "read" if self._metadata.get("op") == "read" else "command"
                if row.get("kind") == expected_kind:
                    measurement.accepted_dispatch(row.get("dispatch_id"))
            elif row.get("dispatch_id") == self._metadata.get("dispatch_id"):
                measurement.result(row)
        except Exception:
            # Observation must never change a PC result or surface content.
            pass
        return body


def observe_pc_transport(service, request_factory):
    """Observe both drive and file signed transports at their common binding.

    Keep the native request untouched: the small envelope is unwrapped before
    fetch, and the response body is returned byte-for-byte after observation.
    """
    class ObservedService:
        def __getattr__(self, key):
            return getattr(service, key)

        async def fetch(self, request):
            if not isinstance(request, _Request):
                return await service.fetch(request)
            measurement = _TOOL.get()
            try:
                response = await service.fetch(request.original.js_object)
            except asyncio.TimeoutError:
                if measurement is not None:
                    measurement.timeout()
                raise
            return _Response(response, request.metadata, measurement)

    def observed_factory(*args, **kwargs):
        original = request_factory(*args, **kwargs)
        metadata = {}
        try:
            body = json.loads(kwargs.get("body", "{}"))
            if isinstance(body, Mapping):
                metadata = {key: body.get(key) for key in ("mode", "op", "run_id", "dispatch_id")}
        except (ValueError, TypeError):
            pass
        return _Request(original, metadata)

    return ObservedService(), observed_factory
