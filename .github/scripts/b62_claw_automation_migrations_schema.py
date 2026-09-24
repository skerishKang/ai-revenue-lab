#!/usr/bin/env python3
"""Classify the #2833 automation D1 schema without reading application rows."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RULE_COLUMNS = (
    "rule_id",
    "workspace_id",
    "name",
    "schedule_kind",
    "schedule_expression",
    "schedule_timezone",
    "target_source",
    "output_type",
    "enabled",
    "notification_channels",
    "created_at",
    "updated_at",
)
RUN_COLUMNS = (
    "run_id",
    "workspace_id",
    "rule_id",
    "status",
    "scheduled_time",
    "started_at",
    "completed_at",
    "output",
    "error_message",
)
OCCURRENCE_COLUMNS = ("occurrence_key", "run_id", "workspace_id")
PROPOSAL_COLUMNS = (
    "proposal_id",
    "workspace_id",
    "rule_id",
    "channel",
    "title",
    "summary",
    "approval_required",
    "approval_reason",
    "suggested_action",
    "approved_by",
    "approved_at",
    "created_at",
)
TABLES = ("claw_rules", "claw_runs", "claw_occurrences", "claw_proposals")
INDEXES = (
    "idx_claw_rules_workspace",
    "idx_claw_runs_workspace_status",
    "idx_claw_occurrences_workspace",
    "idx_claw_proposals_workspace",
)
INDEX_COLUMNS = {
    "idx_claw_rules_workspace": ("workspace_id",),
    "idx_claw_runs_workspace_status": ("workspace_id", "status"),
    "idx_claw_occurrences_workspace": ("workspace_id",),
    "idx_claw_proposals_workspace": ("workspace_id",),
}


class AutomationSchemaError(RuntimeError):
    pass


def _results(entry: object) -> list[dict[str, object]]:
    if not isinstance(entry, dict) or entry.get("success") is not True:
        raise AutomationSchemaError("D1 schema result is not successful")
    rows = entry.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise AutomationSchemaError("D1 schema rows are malformed")
    return rows


def _columns(entry: object) -> tuple[str, ...]:
    return tuple(str(row.get("name", "")) for row in _results(entry))


def _normalized_sql(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def _payload_results(payload: object, count: int) -> list[list[dict[str, object]]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise AutomationSchemaError("D1 response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != count:
        raise AutomationSchemaError("unexpected automation schema result count")
    return [_results(item) for item in result]


def classify_migration_018(payload: object) -> str:
    (
        objects,
        rules,
        runs,
        occurrences,
        proposals,
        rules_index,
        runs_index,
        occurrences_index,
        proposals_index,
    ) = _payload_results(payload, 9)
    by_name = {row.get("name"): row for row in objects if isinstance(row.get("name"), str)}
    if not any((objects, rules, runs, occurrences, proposals, rules_index, runs_index, occurrences_index, proposals_index)):
        return "missing"
    if any(name not in by_name or by_name[name].get("type") != "table" for name in TABLES):
        return "drift"
    if any(name not in by_name or by_name[name].get("type") != "index" for name in INDEXES):
        return "drift"
    if _columns({"success": True, "results": rules}) != RULE_COLUMNS:
        return "drift"
    if _columns({"success": True, "results": runs}) != RUN_COLUMNS:
        return "drift"
    if _columns({"success": True, "results": occurrences}) != OCCURRENCE_COLUMNS:
        return "drift"
    if _columns({"success": True, "results": proposals}) != PROPOSAL_COLUMNS:
        return "drift"
    index_rows = {
        "idx_claw_rules_workspace": rules_index,
        "idx_claw_runs_workspace_status": runs_index,
        "idx_claw_occurrences_workspace": occurrences_index,
        "idx_claw_proposals_workspace": proposals_index,
    }
    for name, expected in INDEX_COLUMNS.items():
        if _columns({"success": True, "results": index_rows[name]}) != expected:
            return "drift"
    table_sql = " ".join(_normalized_sql(by_name[name].get("sql")) for name in TABLES)
    if "rule_id text primary key" not in table_sql or "occurrence_key text primary key" not in table_sql:
        return "drift"
    index_sql = " ".join(_normalized_sql(by_name[name].get("sql")) for name in INDEXES)
    for fragment in (
        "on claw_rules (workspace_id)",
        "on claw_runs (workspace_id, status)",
        "on claw_occurrences (workspace_id)",
        "on claw_proposals (workspace_id)",
    ):
        if fragment not in index_sql:
            return "drift"
    return "exact"


def classify_migration_019(payload: object) -> str:
    (columns,) = _payload_results(payload, 1)
    names = tuple(str(row.get("name", "")) for row in columns)
    if not names:
        return "missing"
    if names == RULE_COLUMNS:
        return "missing"
    if names != RULE_COLUMNS + ("canonical_subject_id",):
        return "drift"
    return "exact"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in {"018", "019"}:
        print("usage: b62_claw_automation_migrations_schema.py <018|019> <d1-query-response.json>", file=sys.stderr)
        return 2
    try:
        payload = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        state = classify_migration_018(payload) if args[0] == "018" else classify_migration_019(payload)
    except (OSError, json.JSONDecodeError, AutomationSchemaError) as exc:
        print(f"B62_CLAW_AUTOMATION_MIGRATION_{args[0]}_SCHEMA=FAIL\nREASON={exc}", file=sys.stderr)
        return 1
    print(f"B62_CLAW_AUTOMATION_MIGRATION_{args[0]}_SCHEMA={state.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
