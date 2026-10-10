"""#3580: one atomic durable record for a *fixed* XLSX ToolRuntime pause.

Owner/file metadata is reauthorized independently by the Engine D1 scope
resolver at execution, then again by the existing handler after approval.
No model tool arguments, tokens, secrets, or workbook bytes are stored here.
"""
from __future__ import annotations

import inspect
import json
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from padiem_ai_core.agent_approval import ApprovalPause, tool_invocation_digest
from padiem_ai_core.tool_runtime import ToolInvocation
from app.continuation_d1 import _pause_from_json, _pause_json
from app.orchestration_continuation import ContinuationRecord
from app.service import ServiceContractError
from app.web_xlsx_p01_tool_binding import (
    APP_ID, AGENT_ID, CANONICAL_TOOL, RUNTIME_TOOL,
    TrustedWebXlsxSelectionScope, web_xlsx_p01_arguments,
)

_TABLE = "padiem_web_xlsx_tool_continuations"
_COLUMNS = ("app_id,continuation_ref,pause_id,pause_json,canonical_agent_id,"
            "canonical_tool_id,invocation_json,invocation_sha256,state,"
            "claim_token,created_at,expires_at")


def _fail(code="continuation_identity_mismatch", status=409):
    raise ServiceContractError(code, "Web XLSX approval continuation is unavailable.", status_code=status)


async def _maybe(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _row(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if callable(getattr(value, "to_py", None)):
        value = value.to_py()
    if isinstance(value, Mapping):
        return dict(value)
    try:
        return dict(value)
    except (ValueError, TypeError):
        _fail("continuation_store_unavailable", 503)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_invocation(invocation: ToolInvocation) -> str:
    if not isinstance(invocation, ToolInvocation) or invocation.tool_id != RUNTIME_TOOL:
        _fail("invalid_continuation", 503)
    args = invocation.arguments
    if not isinstance(args, Mapping):
        _fail("invalid_continuation", 503)
    try:
        scope = TrustedWebXlsxSelectionScope(
            owner_id=args["owner_id"], workspace_id=args["workspace_id"],
            run_id=args["run_id"], selection_ref=args["selection_ref"],
            document_id=args["document_id"], source_sha256=args["source_sha256"],
            original_immutable=True, source_active=True,
        )
        if dict(args) != web_xlsx_p01_arguments(scope):
            _fail("invalid_continuation", 503)
    except (KeyError, TypeError, ValueError):
        _fail("invalid_continuation", 503)
    encoded = json.dumps(dict(args), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 2048:
        _fail("invalid_continuation", 503)
    return encoded


class D1WebXlsxToolPendingStore:
    """CAS continuation + exact ToolInvocation in ONE D1 row, not isolate RAM.

    Scope is exclusively the new Engine XLSX app. It intentionally refuses the
    generic continuation `issue` API, and has no cancel lane yet.
    """

    def __init__(self, private_engine_d1: Any):
        if not callable(getattr(private_engine_d1, "prepare", None)):
            raise ValueError("private Engine continuation D1 required")
        self.db = private_engine_d1

    async def _first(self, sql: str, *params: Any) -> dict[str, Any] | None:
        return _row(await _maybe(self.db.prepare(sql).bind(*params).first()))

    async def issue(self, **_kwargs: Any) -> str:
        _fail("invalid_continuation", 503)

    async def issue_tool(self, *, app_id: str, pause: ApprovalPause,
                         canonical_agent_id: str, canonical_tool_id: str,
                         invocation: ToolInvocation) -> str:
        if (app_id != APP_ID or canonical_agent_id != AGENT_ID
                or canonical_tool_id != CANONICAL_TOOL
                or not isinstance(pause, ApprovalPause)
                or pause.tool_id != RUNTIME_TOOL
                or pause.invocation_sha256 != tool_invocation_digest(invocation)):
            _fail("invalid_continuation", 503)
        encoded = _validate_invocation(invocation)
        ref = "cont_" + secrets.token_urlsafe(32)
        stmt = self.db.prepare(
            f"INSERT INTO {_TABLE} (app_id,continuation_ref,pause_id,pause_json,"
            "canonical_agent_id,canonical_tool_id,invocation_json,"
            "invocation_sha256,state,claim_token,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?,?,'active',NULL,?,?)"
        ).bind(
            app_id, ref, pause.pause_id, _pause_json(pause), canonical_agent_id,
            canonical_tool_id, encoded, pause.invocation_sha256, _now(),
            pause.expires_at.isoformat(),
        )
        try:
            await _maybe(stmt.run())
        except Exception:
            _fail("continuation_store_unavailable", 503)
        return ref

    def _record(self, row: dict[str, Any]) -> ContinuationRecord:
        try:
            pause = _pause_from_json(row["pause_json"])
            invocation_args = json.loads(row["invocation_json"])
            invocation = ToolInvocation(tool_id=RUNTIME_TOOL, arguments=invocation_args)
            if (row["app_id"] != APP_ID or pause.pause_id != row["pause_id"]
                    or row["canonical_agent_id"] != AGENT_ID
                    or row["canonical_tool_id"] != CANONICAL_TOOL
                    or row["invocation_sha256"] != pause.invocation_sha256
                    or tool_invocation_digest(invocation) != pause.invocation_sha256
                    or _validate_invocation(invocation) != row["invocation_json"]):
                _fail("continuation_identity_mismatch")
            return ContinuationRecord(
                app_id=APP_ID, pause=pause,
                continuation_ref=row["continuation_ref"], plan_id=None,
                request_fingerprint="toolinv:" + pause.invocation_sha256,
                state=row["state"], claim_token=row["claim_token"],
            )
        except ServiceContractError:
            raise
        except (KeyError, TypeError, ValueError):
            _fail("continuation_identity_mismatch")

    async def _active(self, *, app_id: str, continuation_ref: str) -> dict[str, Any]:
        if app_id != APP_ID or not isinstance(continuation_ref, str):
            _fail()
        row = await self._first(
            f"SELECT {_COLUMNS} FROM {_TABLE} WHERE app_id=? AND continuation_ref=?",
            app_id, continuation_ref,
        )
        if row is None:
            _fail()
        assert row is not None
        state = row["state"]
        if state != "active" or row["expires_at"] <= _now():
            _fail("continuation_consumed" if state == "consumed" else "continuation_claim_failed")
        return row

    async def resolve(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        return self._record(await self._active(app_id=app_id, continuation_ref=continuation_ref))

    async def load_tool_pending(self, *, app_id: str, continuation_ref: str) -> dict[str, Any]:
        row = await self._active(app_id=app_id, continuation_ref=continuation_ref)
        self._record(row)  # validates source schema and exact invocation hash
        return {
            "app_id": row["app_id"],
            "canonical_agent_id": row["canonical_agent_id"],
            "canonical_tool_id": row["canonical_tool_id"],
            "arguments": json.loads(row["invocation_json"]),
            "tool_id": RUNTIME_TOOL,
        }

    async def claim(self, *, app_id: str, continuation_ref: str) -> ContinuationRecord:
        if app_id != APP_ID:
            _fail()
        token = "claim_" + secrets.token_urlsafe(24)
        row = await self._first(
            f"UPDATE {_TABLE} SET state='claimed',claim_token=? "
            "WHERE app_id=? AND continuation_ref=? AND state='active' "
            f"AND expires_at>? RETURNING {_COLUMNS}",
            token, app_id, continuation_ref, _now(),
        )
        if row is None:
            _fail("continuation_claim_failed")
        return self._record(row)

    async def commit(self, *, app_id: str, continuation_ref: str, claim_token: str) -> None:
        row = await self._first(
            f"UPDATE {_TABLE} SET state='consumed',claim_token=NULL "
            "WHERE app_id=? AND continuation_ref=? AND state='claimed' AND claim_token=? "
            f"RETURNING {_COLUMNS}", app_id, continuation_ref, claim_token,
        )
        if row is None:
            _fail("continuation_claim_failed")

    async def release(self, *, app_id: str, continuation_ref: str, claim_token: str) -> None:
        row = await self._first(
            f"UPDATE {_TABLE} SET state=CASE WHEN expires_at<=? THEN 'expired' ELSE 'active' END,"
            "claim_token=NULL WHERE app_id=? AND continuation_ref=? "
            f"AND state='claimed' AND claim_token=? RETURNING {_COLUMNS}",
            _now(), app_id, continuation_ref, claim_token,
        )
        if row is None:
            _fail("continuation_claim_failed")
