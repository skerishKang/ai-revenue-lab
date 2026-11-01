"""Authenticated PC-turn annotations and recent-turn summaries on B14's ledger.

The Engine reports measured counters after the PC turn ends. B14 records them
as Engine-reported evidence on an existing model call; it never rewrites the
provider-observed token/cost fields, dispatches a model or stores tool content.
"""
from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Router

from padiem_ai_core.pc_work_metrics import PcWorkMetricsError
from app.pilot.call_ledger import CallLedgerError
from app.pilot.call_ledger_admin import _denial, _query, _resolve_store

REPORT_PATH = "/v1/internal/pc-turn-metrics"
RECENT_PATH = "/v1/admin/model-calls/pc-turns"
_COUNTERS = (
    "pc_round_trips", "calls", "truncation_count", "truncated_bytes",
    "truncated_bytes_known", "truncated_bytes_unknown_count", "timeout_count",
    "model_calls", "model_input_tokens", "model_input_tokens_observed",
    "model_input_tokens_missing_calls", "model_input_tokens_estimated",
    "tool_result_tokens_estimated", "tool_result_input_ratio",
    "stored_output_count", "compaction_count", "background_job_count",
    "compaction_input_tokens_before", "compaction_input_tokens_after",
    "compaction_tokens_saved",
)
_TOOL_COUNTERS = (
    "calls", "pc_round_trips", "truncation_count", "truncated_bytes_known",
    "truncated_bytes_unknown_count", "timeout_count",
)


def _reply(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _error(code: str, status: int) -> JSONResponse:
    return _reply({"error": {"code": code}}, status)


async def report_pc_work_metrics(request: Request) -> JSONResponse:
    denial = await _denial(request)
    if denial is not None:
        return denial
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        return _error("invalid_pc_work_metrics", 422)
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeError):
        return _error("invalid_pc_work_metrics", 422)
    if not isinstance(body, dict) or set(body) != {"product", "subject_ref", "session_ref", "metrics"}:
        return _error("invalid_pc_work_metrics", 422)
    store = _resolve_store(request)
    if store is None:
        return _error("call_ledger_unavailable", 503)
    try:
        result = await store.annotate_pc_work_metrics(**body)
    except (CallLedgerError, PcWorkMetricsError, TypeError, ValueError):
        return _error("invalid_pc_work_metrics", 422)
    except Exception:
        return _error("call_ledger_unavailable", 502)
    if result["status"] in {"ledger_pending", "metrics_conflict"}:
        return _error(result["status"], 409)
    return _reply({"ok": True, **result})


def summarize_pc_work_metrics(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise the actual recent rows, retaining missing and estimated values."""
    metrics = [row["metrics"] for row in turns if row["metrics"] is not None]
    unfinished = len(turns) - len(metrics)
    counters = {}
    for key in _COUNTERS:
        values = [row[key] for row in metrics if row.get(key) is not None]
        counters[key] = {
            "average": sum(values) / len(values) if values else None,
            "max": max(values) if values else None,
            "observed_turns": len(values), "missing_turns": len(turns) - len(values),
        }
    outcomes: dict[str, int] = {}
    reasons: dict[str, int] = {}
    if unfinished:
        outcomes["not_finalized"] = unfinished
        reasons["not_finalized"] = unfinished
    tools: dict[str, dict[str, Any]] = {}
    for row in metrics:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
        reasons[row["outcome_reason"]] = reasons.get(row["outcome_reason"], 0) + 1
        for tool_id, counts in row["tool_calls"].items():
            target = tools.setdefault(tool_id, {"tool_id": tool_id,
                                              **{key: 0 for key in _TOOL_COUNTERS}})
            for key in _TOOL_COUNTERS:
                target[key] += counts[key]
    return {
        "turn_count": len(turns), "measured_turn_count": len(metrics),
        "outcomes": outcomes, "outcome_reasons": reasons,
        "counters": counters,
        "tools": sorted(tools.values(), key=lambda tool: (-tool["pc_round_trips"],
                                                         -tool["calls"], tool["tool_id"])),
        "truncation_ranking": sorted(tools.values(), key=lambda tool: (
            -tool["truncation_count"], tool["tool_id"])),
        "timeout_ranking": sorted(tools.values(), key=lambda tool: (
            -tool["timeout_count"], tool["tool_id"])),
        "token_ratio_basis": "utf8_bytes_div4_estimate",
        "metrics_source": "engine_reported",
    }


async def recent_pc_work_metrics(request: Request) -> JSONResponse:
    denial = await _denial(request)
    if denial is not None:
        return denial
    store = _resolve_store(request)
    if store is None:
        return _error("call_ledger_unavailable", 503)
    try:
        filters, since, until, limit, group_by = _query(request)
        if group_by is not None:
            return _error("invalid_query", 422)
        turns = await store.recent_pc_work_metrics(filters=filters, since=since, until=until,
                                                 limit=limit)
        summary = summarize_pc_work_metrics(turns)
    except CallLedgerError:
        return _error("invalid_query", 422)
    except Exception:
        return _error("call_ledger_unavailable", 502)
    return _reply({"turns": turns, "summary": summary, "limit": limit,
                   "unit": "pc_turn", "storage_state": "bound"})


router = Router(routes=[
    Route(REPORT_PATH, report_pc_work_metrics, methods=["POST"]),
    Route(RECENT_PATH, recent_pc_work_metrics, methods=["GET"]),
])
