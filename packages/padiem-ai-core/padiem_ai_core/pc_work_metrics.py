"""Closed, content-free metrics for one remote PC turn (#6460).

The shared wire contains counters only. Paths, arguments, output, subjects and
credentials cannot be smuggled into tool names, reasons, or extra fields.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
import re
from typing import Any

PC_METRIC_TOOL_IDS = frozenset({
    "claw.pc.query_drives", "claw.pc.list_files", "claw.pc.read_file",
    "claw.pc.write_file", "claw.pc.move_file", "claw.pc.delete_file",
    "claw.pc.search_files", "claw.pc.search_contents", "claw.pc.read_file_chunk",
    "claw.pc.read_output", "claw.pc.search_output", "claw.pc.start_job",
    "claw.pc.job_status", "claw.pc.job_output", "claw.pc.batch", "claw.pc.recall_context",
    "claw.pc.browser_open", "claw.pc.browser_read", "claw.pc.browser_screenshot", "claw.pc.browser_act",
})
PC_METRIC_COUNTERS = (
    "calls", "pc_round_trips", "truncation_count", "truncated_bytes_known",
    "truncated_bytes_unknown_count", "timeout_count",
)
# Version 2 counts successful lifecycle events separately from tool invocations.
PC_METRIC_LIFECYCLE_COUNTERS = (
    "stored_output_count", "compaction_count", "background_job_count",
)
PC_METRIC_OUTCOMES = frozenset({
    "running", "completed", "failed", "cancelled", "abandoned", "confirmation_required",
})
PC_METRIC_REASONS = frozenset({
    "in_progress", "completed", "confirmation_required", "tool_timeout", "model_timeout",
    "tool_failed", "model_failed", "execution_failed", "cancelled", "client_disconnected",
    "abandoned",
})
PC_METRIC_KEYS_V1 = frozenset(PC_METRIC_COUNTERS) | {
    "schema_version", "turn_id", "tool_calls", "truncated_bytes", "model_calls",
    "model_input_tokens", "model_input_tokens_observed", "model_input_tokens_missing_calls",
    "model_input_tokens_estimated", "tool_result_tokens_estimated", "tool_result_input_ratio",
    "token_ratio_basis", "outcome", "outcome_reason",
}

PC_METRIC_KEYS = PC_METRIC_KEYS_V1 | frozenset(PC_METRIC_LIFECYCLE_COUNTERS)
# Version 3 adds the measured prompt-size change of the compactions above.
PC_METRIC_COMPACTION_TOKEN_KEYS = (
    "compaction_input_tokens_before", "compaction_input_tokens_after",
    "compaction_tokens_saved",
)
PC_METRIC_KEYS_V3 = PC_METRIC_KEYS | frozenset(PC_METRIC_COMPACTION_TOKEN_KEYS)
# Version 4 measures the read-family batch (#6460-5): how many steps one batch
# carried and how many separate model turns it replaced. A batch still travels to
# the PC as one command per step, so no PC round trip is claimed as saved here.
PC_METRIC_BATCH_COUNTERS = ("batch_count", "batch_steps", "batch_model_turns_saved")
PC_METRIC_KEYS_V4 = PC_METRIC_KEYS_V3 | frozenset(PC_METRIC_BATCH_COUNTERS)


class PcWorkMetricsError(ValueError):
    """Closed metrics contract failure; never echoes the rejected data."""


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise PcWorkMetricsError("invalid PC metric counter")
    return value


def _number(value: Any) -> float:
    try:
        valid = type(value) in {int, float} and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise PcWorkMetricsError("invalid PC metric estimate")
    return float(value)


def validate_pc_work_metrics(value: Any) -> dict[str, Any]:
    """Return a normalized snapshot after exact-field and total validation."""
    if not isinstance(value, Mapping):
        raise PcWorkMetricsError("invalid PC metric fields")
    version = value.get("schema_version")
    if type(version) is not int or version not in {1, 2, 3, 4}:
        raise PcWorkMetricsError("invalid PC metric version")
    expected_keys = (PC_METRIC_KEYS_V1 if version == 1
                     else PC_METRIC_KEYS if version == 2
                     else PC_METRIC_KEYS_V3 if version == 3 else PC_METRIC_KEYS_V4)
    if set(value) != expected_keys:
        raise PcWorkMetricsError("invalid PC metric fields")
    turn_id = value["turn_id"]
    if not isinstance(turn_id, str) or not re.fullmatch(r"pcturn_[a-f0-9]{64}", turn_id):
        raise PcWorkMetricsError("invalid PC turn reference")
    tools = value["tool_calls"]
    if not isinstance(tools, Mapping) or not set(tools) <= PC_METRIC_TOOL_IDS:
        raise PcWorkMetricsError("invalid PC metric tools")
    normalized_tools = {}
    for tool_id, counters in tools.items():
        if not isinstance(counters, Mapping) or set(counters) != set(PC_METRIC_COUNTERS):
            raise PcWorkMetricsError("invalid PC tool counters")
        row = {key: _count(counters[key]) for key in PC_METRIC_COUNTERS}
        if (row["truncated_bytes_unknown_count"] > row["truncation_count"]
                or row["truncation_count"] > row["calls"] or row["timeout_count"] > row["calls"]):
            raise PcWorkMetricsError("inconsistent PC tool counters")
        normalized_tools[tool_id] = row
    result = dict(value)
    # Keep v1 evidence unchanged: an unmeasured lifecycle counter is not zero.
    if version >= 2:
        for key in PC_METRIC_LIFECYCLE_COUNTERS:
            result[key] = _count(value[key])
    if version >= 4:
        for key in PC_METRIC_BATCH_COUNTERS:
            result[key] = _count(value[key])
        if result["batch_steps"] < result["batch_count"]:
            raise PcWorkMetricsError("inconsistent PC batch evidence")
        if result["batch_model_turns_saved"] != result["batch_steps"] - result["batch_count"]:
            raise PcWorkMetricsError("inconsistent PC batch evidence")
    if version >= 3:
        for key in PC_METRIC_COMPACTION_TOKEN_KEYS:
            result[key] = _number(value[key])
        before = result["compaction_input_tokens_before"]
        after = result["compaction_input_tokens_after"]
        if after > before or not math.isclose(
                result["compaction_tokens_saved"], before - after,
                rel_tol=1e-9, abs_tol=1e-9):
            raise PcWorkMetricsError("inconsistent PC compaction token evidence")
    result["tool_calls"] = normalized_tools
    for key in PC_METRIC_COUNTERS:
        result[key] = _count(value[key])
        if result[key] != sum(row[key] for row in normalized_tools.values()):
            raise PcWorkMetricsError("inconsistent PC metric totals")
    expected_bytes = None if result["truncated_bytes_unknown_count"] else result["truncated_bytes_known"]
    if value["truncated_bytes"] is not None:
        _count(value["truncated_bytes"])
    if value["truncated_bytes"] != expected_bytes:
        raise PcWorkMetricsError("inconsistent PC truncation evidence")
    for key in ("model_calls", "model_input_tokens_observed", "model_input_tokens_missing_calls"):
        result[key] = _count(value[key])
    if result["model_input_tokens_missing_calls"] > result["model_calls"]:
        raise PcWorkMetricsError("inconsistent PC token observations")
    expected_tokens = None if result["model_input_tokens_missing_calls"] else result["model_input_tokens_observed"]
    if value["model_input_tokens"] is not None:
        _count(value["model_input_tokens"])
    if value["model_input_tokens"] != expected_tokens:
        raise PcWorkMetricsError("inconsistent PC token observations")
    for key in ("model_input_tokens_estimated", "tool_result_tokens_estimated"):
        result[key] = _number(value[key])
    denominator, numerator = result["model_input_tokens_estimated"], result["tool_result_tokens_estimated"]
    if numerator > denominator:
        raise PcWorkMetricsError("inconsistent PC token estimates")
    if denominator == 0:
        if value["tool_result_input_ratio"] is not None:
            raise PcWorkMetricsError("invalid PC token ratio")
    else:
        ratio = _number(value["tool_result_input_ratio"])
        if not math.isclose(ratio, numerator / denominator, rel_tol=1e-9, abs_tol=1e-12):
            raise PcWorkMetricsError("inconsistent PC token ratio")
        result["tool_result_input_ratio"] = ratio
    if value["token_ratio_basis"] != "utf8_bytes_div4_estimate":
        raise PcWorkMetricsError("invalid PC token ratio basis")
    if not isinstance(value["outcome"], str) or value["outcome"] not in PC_METRIC_OUTCOMES:
        raise PcWorkMetricsError("invalid PC metric outcome")
    if not isinstance(value["outcome_reason"], str) or value["outcome_reason"] not in PC_METRIC_REASONS:
        raise PcWorkMetricsError("invalid PC metric outcome reason")
    return result
