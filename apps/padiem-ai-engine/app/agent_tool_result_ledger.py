"""#4379: the Engine's durable owner of settled Agent tool results.

The Agent runtime keeps only a small reference per settled tool result. The
payload lives in D1, so a long run does not retain every tool output in the
Worker and no step copies the whole history again.

The reference is server-minted and bound to one run and owner scope. A result
is never truncated: the stored payload is the exact original result, and the
digest proves it on the way back.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
from typing import Any

from padiem_ai_core.agent_tool_result_ledger import (
    ToolResultLedgerError,
    ToolResultRef,
    decode_tool_result,
    encode_tool_result,
    tool_result_digest,
)
from padiem_ai_core.tool_runtime import ToolExecutionResult

TOOL_RESULT_RETENTION_SECONDS = 24 * 60 * 60
_INSERT = (
    "INSERT INTO padiem_engine_tool_results_v1 ("
    "result_ref, run_id, owner_scope, step_index, ordinal, tool_id, "
    "payload_json, payload_sha256, created_at, expires_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_SELECT = (
    "SELECT payload_json, payload_sha256 FROM padiem_engine_tool_results_v1 "
    "WHERE result_ref = ? AND owner_scope = ?"
)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


class D1ToolResultLedger:
    """Durable, run-scoped ledger for settled tool results."""

    def __init__(self, binding: Any, *, owner_scope: str, retention_seconds: int = TOOL_RESULT_RETENTION_SECONDS) -> None:
        if binding is None:
            raise ValueError("D1 tool result ledger requires a D1 binding")
        if not isinstance(owner_scope, str) or not owner_scope.strip():
            raise ValueError("owner_scope must be a non-empty string")
        if isinstance(retention_seconds, bool) or not isinstance(retention_seconds, int) or retention_seconds < 1:
            raise ValueError("retention_seconds must be a positive integer")
        self._binding = binding
        self._owner_scope = owner_scope
        self._retention_seconds = retention_seconds

    async def append(
        self,
        *,
        run_id: str,
        step_index: int,
        ordinal: int,
        result: ToolExecutionResult,
    ) -> ToolResultRef:
        ref = ToolResultRef(
            run_id=run_id,
            step_index=step_index,
            ordinal=ordinal,
            tool_id=result.tool_id,
            digest=tool_result_digest(result),
        )
        created = _now()
        result_ref = _ref_for(ref)
        statement = self._binding.prepare(_INSERT)
        statement = statement.bind(
            result_ref,
            run_id,
            self._owner_scope,
            step_index,
            ordinal,
            result.tool_id,
            encode_tool_result(result),
            ref.digest,
            created.isoformat(),
            (created + timedelta(seconds=self._retention_seconds)).isoformat(),
        )
        try:
            await _maybe_await(statement.run())
        except Exception as exc:
            raise ToolResultLedgerError(
                "tool_result_store_unavailable",
                "Tool result storage is unavailable.",
            ) from exc
        return ToolResultRef(
            run_id=run_id,
            step_index=step_index,
            ordinal=ordinal,
            tool_id=result.tool_id,
            digest=ref.digest,
        )

    async def resolve(self, ref: ToolResultRef) -> ToolExecutionResult:
        statement = self._binding.prepare(_SELECT)
        statement = statement.bind(_ref_for(ref), self._owner_scope)
        try:
            row = await _maybe_await(statement.first())
        except Exception as exc:
            raise ToolResultLedgerError(
                "tool_result_store_unavailable",
                "Tool result storage is unavailable.",
            ) from exc
        if not row:
            raise ToolResultLedgerError(
                "tool_result_not_found", "Tool result is not available."
            )
        payload = row.get("payload_json")
        digest = row.get("payload_sha256")
        if not isinstance(payload, str) or not isinstance(digest, str):
            raise ToolResultLedgerError(
                "tool_result_payload_invalid", "Stored tool result is unreadable."
            )
        result = decode_tool_result(payload)
        if tool_result_digest(result) != digest:
            raise ToolResultLedgerError(
                "tool_result_integrity_mismatch", "Stored tool result is unreadable."
            )
        return result


def _ref_for(ref: ToolResultRef) -> str:
    """The durable row key for one reference.

    The reference is reconstructed from its own fields, so a host can persist
    the reference next to the run and resolve the original payload later.
    """
    return f"{ref.run_id}:{ref.step_index}:{ref.ordinal}:{ref.tool_id}:{ref.digest}"


__all__ = ["D1ToolResultLedger", "TOOL_RESULT_RETENTION_SECONDS"]
