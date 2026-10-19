#!/usr/bin/env python3
"""Bounded one-shot Production B66 E2E Saved Quote Skill provision helper (#3347)."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CHAT_ROOT = ROOT / "apps" / "padiem-chat"
if str(CHAT_ROOT) not in sys.path:
    sys.path.insert(0, str(CHAT_ROOT))

from app.b66_saved_quote_skill_store import (  # noqa: E402
    ApprovedSavedQuoteSkillArtifact,
    SavedQuoteSkillStoreError,
    canonicalize_approved_artifact,
)

TARGET_USER_ENV = "B62_B66_E2E_TARGET_USER_ID"
EXPECTED_SKILL_ID = "b66-e2e-canonical-v1"
EXPECTED_SKILL_VERSION = 1

_USER_RE = re.compile(r"^usr_[0-9A-Za-z._:-]{1,76}$")
_TENANT_RE = re.compile(r"^tenant_[0-9a-f]{32}$")
_ROW_RE = re.compile(r"^b66skill_[0-9a-f]{32}$")

_RESOLUTION_SQL = (
    "WITH workspaces AS ("
    "SELECT workspace_id FROM claw_approved_memory "
    "WHERE user_id=? AND workspace_id IS NOT NULL "
    "UNION "
    "SELECT workspace_id FROM claw_run_history "
    "WHERE user_id=? AND workspace_id IS NOT NULL"
    ") "
    "SELECT "
    "(SELECT COUNT(*) FROM users WHERE id=?) AS user_count, "
    "(SELECT COUNT(*) FROM control_plane_identity_shadow "
    " WHERE product_user_id=? AND session_state='active' AND session_expires_at>?) AS shadow_active_count, "
    "(SELECT COUNT(*) FROM workspaces) AS workspace_count, "
    "(SELECT MIN(workspace_id) FROM workspaces) AS workspace_id"
)

_EXISTING_SQL = (
    "SELECT id, skill_id, skill_name, skill_fingerprint, skill_version, skill_json, status "
    "FROM b66_saved_quote_skill "
    "WHERE user_id=? AND workspace_id=? AND skill_id=? AND skill_version=?"
)

_INSERT_SQL = (
    "INSERT INTO b66_saved_quote_skill "
    "(id, user_id, workspace_id, skill_id, skill_name, skill_fingerprint, "
    "skill_version, skill_json, status, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)"
)

_READBACK_SQL = (
    "SELECT id, skill_id, skill_name, skill_fingerprint, skill_version, skill_json, status "
    "FROM b66_saved_quote_skill "
    "WHERE id=? AND user_id=? AND workspace_id=?"
)

_DELETE_SQL = (
    "DELETE FROM b66_saved_quote_skill "
    "WHERE id=? AND user_id=? AND workspace_id=? AND skill_id=? AND skill_version=?"
)


class ProvisionError(RuntimeError):
    pass


def _target_user() -> str:
    value = os.environ.get(TARGET_USER_ENV, "").strip()
    if not _USER_RE.fullmatch(value):
        raise ProvisionError("protected target user is absent or invalid")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvisionError(f"invalid JSON evidence: {exc}") from exc


def _write_new(path: Path, payload: Any) -> None:
    if path.exists():
        raise ProvisionError("refusing to overwrite output")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _query_result(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ProvisionError("D1 API response is not successful")
    result = payload.get("result")
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise ProvisionError("D1 API result shape is invalid")
    entry = result[0]
    if entry.get("success") is not True:
        raise ProvisionError("D1 statement failed")
    rows = entry.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ProvisionError("D1 result rows are invalid")
    meta = entry.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    return list(rows), meta


def load_artifact(path: Path) -> ApprovedSavedQuoteSkillArtifact:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ProvisionError("Skill fixture must be an object")
    try:
        artifact = canonicalize_approved_artifact(
            skill_id=payload.get("id"),
            skill_name=payload.get("name"),
            fingerprint=payload.get("fingerprint"),
            version=EXPECTED_SKILL_VERSION,
            serialized_json=json.dumps(payload, ensure_ascii=False),
        )
    except SavedQuoteSkillStoreError as exc:
        raise ProvisionError(f"canonical Skill fixture rejected: {exc}") from exc
    if artifact.skill_id != EXPECTED_SKILL_ID or artifact.version != EXPECTED_SKILL_VERSION:
        raise ProvisionError("unexpected E2E Skill identity")
    return artifact


def build_resolution_query(output: Path) -> None:
    user_id = _target_user()
    now = _utc_now()
    _write_new(
        output,
        {"sql": _RESOLUTION_SQL, "params": [user_id, user_id, user_id, user_id, now]},
    )


def resolve_workspace(response: Path, output: Path) -> None:
    rows, _ = _query_result(_load_json(response))
    if len(rows) != 1:
        raise ProvisionError("target resolution must return exactly one row")
    row = rows[0]
    try:
        user_count = int(row.get("user_count", -1))
        shadow_count = int(row.get("shadow_active_count", -1))
        workspace_count = int(row.get("workspace_count", -1))
    except (TypeError, ValueError) as exc:
        raise ProvisionError("target resolution counts are invalid") from exc
    workspace = row.get("workspace_id")
    if user_count != 1:
        raise ProvisionError("target user is not uniquely present")
    if shadow_count != 1:
        raise ProvisionError("active identity shadow evidence is not unique")
    if workspace_count != 1 or not isinstance(workspace, str) or not _TENANT_RE.fullmatch(workspace):
        raise ProvisionError("server-derived canonical tenant workspace evidence is absent or ambiguous")
    if output.exists():
        raise ProvisionError("refusing to overwrite workspace evidence")
    output.write_text(workspace, encoding="utf-8")


def _workspace(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProvisionError("workspace evidence unavailable") from exc
    if not _TENANT_RE.fullmatch(value):
        raise ProvisionError("workspace evidence is invalid")
    return value


def build_existing_query(workspace: Path, artifact_path: Path, output: Path) -> None:
    user_id = _target_user()
    workspace_id = _workspace(workspace)
    artifact = load_artifact(artifact_path)
    _write_new(
        output,
        {
            "sql": _EXISTING_SQL,
            "params": [user_id, workspace_id, artifact.skill_id, artifact.version],
        },
    )


def _row_exact(row: dict[str, Any], artifact: ApprovedSavedQuoteSkillArtifact) -> bool:
    return (
        row.get("skill_id") == artifact.skill_id
        and row.get("skill_name") == artifact.skill_name
        and row.get("skill_fingerprint") == artifact.fingerprint
        and row.get("skill_version") == artifact.version
        and row.get("skill_json") == artifact.serialized_json
        and row.get("status") == "approved"
    )


def classify_existing(response: Path, artifact_path: Path) -> str:
    artifact = load_artifact(artifact_path)
    rows, _ = _query_result(_load_json(response))
    if not rows:
        return "missing"
    if len(rows) != 1:
        return "drift"
    return "exact" if _row_exact(rows[0], artifact) else "drift"


def _row_id(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProvisionError("row id evidence unavailable") from exc
    if not _ROW_RE.fullmatch(value):
        raise ProvisionError("row id evidence is invalid")
    return value


def build_insert_query(workspace: Path, artifact_path: Path, row_output: Path, output: Path) -> None:
    user_id = _target_user()
    workspace_id = _workspace(workspace)
    artifact = load_artifact(artifact_path)
    row_id = "b66skill_" + secrets.token_hex(16)
    if row_output.exists():
        raise ProvisionError("refusing to overwrite row evidence")
    row_output.write_text(row_id, encoding="utf-8")
    now = _utc_now()
    _write_new(
        output,
        {
            "sql": _INSERT_SQL,
            "params": [
                row_id,
                user_id,
                workspace_id,
                artifact.skill_id,
                artifact.skill_name,
                artifact.fingerprint,
                artifact.version,
                artifact.serialized_json,
                now,
                now,
            ],
        },
    )


def build_readback_query(
    workspace: Path,
    artifact_path: Path,
    row_file: Path,
    output: Path,
) -> None:
    user_id = _target_user()
    workspace_id = _workspace(workspace)
    load_artifact(artifact_path)
    row_id = _row_id(row_file)
    _write_new(output, {"sql": _READBACK_SQL, "params": [row_id, user_id, workspace_id]})


def build_delete_query(
    workspace: Path,
    artifact_path: Path,
    row_file: Path,
    output: Path,
) -> None:
    user_id = _target_user()
    workspace_id = _workspace(workspace)
    artifact = load_artifact(artifact_path)
    row_id = _row_id(row_file)
    _write_new(
        output,
        {
            "sql": _DELETE_SQL,
            "params": [row_id, user_id, workspace_id, artifact.skill_id, artifact.version],
        },
    )


def verify_mutation(response: Path) -> None:
    _, meta = _query_result(_load_json(response))
    try:
        changes = int(meta.get("changes", -1))
    except (TypeError, ValueError) as exc:
        raise ProvisionError("D1 mutation change count is invalid") from exc
    if changes != 1:
        raise ProvisionError("D1 mutation must affect exactly one row")


def verify_readback(response: Path, artifact_path: Path, row_file: Path) -> None:
    artifact = load_artifact(artifact_path)
    expected_id = _row_id(row_file)
    rows, _ = _query_result(_load_json(response))
    if len(rows) != 1 or rows[0].get("id") != expected_id or not _row_exact(rows[0], artifact):
        raise ProvisionError("post-provision readback is not exact")


def verify_absent(response: Path) -> None:
    rows, _ = _query_result(_load_json(response))
    if rows:
        raise ProvisionError("rollback readback still finds the inserted row")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate-artifact")
    p.add_argument("--artifact", required=True, type=Path)

    p = sub.add_parser("build-resolution-query")
    p.add_argument("--output", required=True, type=Path)

    p = sub.add_parser("resolve-workspace")
    p.add_argument("--response", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)

    p = sub.add_parser("build-existing-query")
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)

    p = sub.add_parser("classify-existing")
    p.add_argument("--response", required=True, type=Path)
    p.add_argument("--artifact", required=True, type=Path)

    p = sub.add_parser("build-insert-query")
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--row-output", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)

    p = sub.add_parser("build-readback-query")
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--row-file", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)

    p = sub.add_parser("build-delete-query")
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--row-file", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)

    p = sub.add_parser("verify-mutation")
    p.add_argument("--response", required=True, type=Path)

    p = sub.add_parser("verify-readback")
    p.add_argument("--response", required=True, type=Path)
    p.add_argument("--artifact", required=True, type=Path)
    p.add_argument("--row-file", required=True, type=Path)

    p = sub.add_parser("verify-absent")
    p.add_argument("--response", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "validate-artifact":
            load_artifact(args.artifact)
            print("B62_B66_E2E_ARTIFACT_VALIDATION=PASS")
        elif args.command == "build-resolution-query":
            build_resolution_query(args.output)
            print("B62_B66_E2E_RESOLUTION_QUERY=BUILT")
        elif args.command == "resolve-workspace":
            resolve_workspace(args.response, args.output)
            print("B62_B66_E2E_TARGET_RESOLUTION=PASS")
            print("CALLER_SUPPLIED_WORKSPACE=0")
            print("RAW_WORKSPACE_OUTPUT=0")
        elif args.command == "build-existing-query":
            build_existing_query(args.workspace, args.artifact, args.output)
            print("B62_B66_E2E_EXISTING_QUERY=BUILT")
        elif args.command == "classify-existing":
            state = classify_existing(args.response, args.artifact)
            print(f"B62_B66_E2E_SKILL_STATE={state}")
        elif args.command == "build-insert-query":
            build_insert_query(args.workspace, args.artifact, args.row_output, args.output)
            print("B62_B66_E2E_INSERT_QUERY=BUILT")
            print("D1_MUTATION_MAX_ROWS=1")
        elif args.command == "build-readback-query":
            build_readback_query(args.workspace, args.artifact, args.row_file, args.output)
            print("B62_B66_E2E_READBACK_QUERY=BUILT")
        elif args.command == "build-delete-query":
            build_delete_query(args.workspace, args.artifact, args.row_file, args.output)
            print("B62_B66_E2E_ROLLBACK_QUERY=BUILT")
        elif args.command == "verify-mutation":
            verify_mutation(args.response)
            print("B62_B66_E2E_D1_MUTATION_ROWS=1")
        elif args.command == "verify-readback":
            verify_readback(args.response, args.artifact, args.row_file)
            print("B62_B66_E2E_POST_READBACK=EXACT")
        elif args.command == "verify-absent":
            verify_absent(args.response)
            print("B62_B66_E2E_ROLLBACK_READBACK=ABSENT")
        else:
            raise ProvisionError("unsupported command")
        print("RAW_TARGET_USER_OUTPUT=0")
        return 0
    except ProvisionError as exc:
        print(f"B62_B66_E2E_PROVISION=FAIL\nREASON={exc}", file=sys.stderr)
        print("RAW_TARGET_USER_OUTPUT=0", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
