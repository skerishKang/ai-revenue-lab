"""Durable idempotency adapter boundary for Engine orchestration.

This module adapts a trusted server-side durable binding to the Core
IdempotencyAdapter protocol. It intentionally contains no process-local fallback
store: if the binding is absent or unavailable, callers must fail closed through
Core's existing idempotency_unavailable path rather than silently rerunning.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import inspect
import json
from typing import Any

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionResult,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)

_TABLE_NAME = "padiem_engine_idempotency"
_DEFAULT_TTL_SECONDS = 24 * 60 * 60


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


def _expires_at_iso(ttl_seconds: int) -> str:
    return (_utcnow() + timedelta(seconds=ttl_seconds)).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(value: Any) -> bool:
    parsed = _parse_timestamp(value)
    return parsed is not None and parsed <= _utcnow()


def _public_result(result: ExecutionResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result, ExecutionResult):
        return result.to_public_dict()
    return dict(result)


def _route_from_public(value: Any) -> B14RouteMetadata:
    data = dict(value) if isinstance(value, Mapping) else {}
    return B14RouteMetadata(
        request_id=data.get("request_id"),
        route_mode=data.get("route_mode"),
        selected_provider=data.get("selected_provider"),
        selected_model=data.get("selected_model"),
        selected_upstream_model=data.get("selected_upstream_model"),
        selected_route_id=data.get("selected_route_id"),
        actual_response_model=data.get("actual_response_model"),
        reason_codes=tuple(data.get("reason_codes") or ()),
        fallback_used=data.get("fallback_used"),
        attempt_count=data.get("attempt_count"),
        route_evidence_status=data.get("route_evidence_status"),
        estimated_krw=data.get("estimated_krw"),
    )


def _metadata_from_public(value: Any) -> RunMetadata:
    data = dict(value) if isinstance(value, Mapping) else {}
    usage_raw = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
    status_raw = data.get("status", RunStatus.COMPLETED.value)
    try:
        status = RunStatus(status_raw)
    except ValueError:
        status = RunStatus.COMPLETED
    return RunMetadata(
        trace_id=data.get("trace_id") or "tr_idempotency_replay",
        app_id=data.get("app_id") or "p01",
        agent_id=data.get("agent_id") or "agent:padiem:replay_1",
        status=status,
        session_id=data.get("session_id"),
        provider=data.get("provider"),
        model=data.get("model"),
        duration_ms=data.get("duration_ms"),
        usage=UsageMetadata(
            input_tokens=usage_raw.get("input_tokens"),
            output_tokens=usage_raw.get("output_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
        ),
    )


def _execution_result_from_public(value: Mapping[str, Any]) -> ExecutionResult:
    return ExecutionResult(
        answer=str(value["answer"]),
        route=_route_from_public(value.get("route")),
        metadata=_metadata_from_public(value.get("metadata")),
    )


class CloudflareD1IdempotencyAdapter:
    """Core IdempotencyAdapter backed by a trusted durable D1-like binding.

    Expected table shape is intentionally simple and app/key scoped:

    ```text
    app_id TEXT
    idempotency_key TEXT
    request_fingerprint TEXT
    state TEXT
    result_json TEXT NULL
    created_at TEXT
    updated_at TEXT
    expires_at TEXT
    PRIMARY KEY (app_id, idempotency_key)
    ```

    The adapter does not create the table at runtime; schema provisioning remains
    an explicit deployment/migration concern outside this source-only PR.
    """

    def __init__(self, binding: Any, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("idempotency binding must provide prepare(sql)")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        self._binding = binding
        self._ttl_seconds = ttl_seconds

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        stmt = self._binding.prepare(sql).bind(*params)
        row = await _maybe_await(stmt.first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _run(self, sql: str, *params: Any) -> Any:
        stmt = self._binding.prepare(sql).bind(*params)
        return await _maybe_await(stmt.run())

    async def _record(self, *, app_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        return await self._first(
            f"SELECT app_id,idempotency_key,request_fingerprint,state,result_json,expires_at "
            f"FROM {_TABLE_NAME} WHERE app_id=? AND idempotency_key=? LIMIT 1",
            app_id,
            idempotency_key,
        )

    async def _release_expired_reservation(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        record: Mapping[str, Any],
    ) -> bool:
        if record.get("state") == "completed" or not _is_expired(record.get("expires_at")):
            return False
        await self._run(
            f"DELETE FROM {_TABLE_NAME} "
            "WHERE app_id=? AND idempotency_key=? AND state != ? AND expires_at=?",
            app_id,
            idempotency_key,
            "completed",
            record.get("expires_at"),
        )
        return True

    async def begin(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ExecutionResult | None:
        record = await self._record(app_id=app_id, idempotency_key=idempotency_key)
        if record is not None and await self._release_expired_reservation(
            app_id=app_id,
            idempotency_key=idempotency_key,
            record=record,
        ):
            record = None
        if record is not None:
            if record.get("request_fingerprint") != request_fingerprint:
                raise IdempotencyConflictError("idempotency key is bound to a different request")
            if record.get("state") == "completed" and record.get("result_json"):
                return _execution_result_from_public(json.loads(str(record["result_json"])))
            raise IdempotencyConflictError("idempotency key is already reserved")

        now = _utcnow_iso()
        await self._run(
            f"INSERT INTO {_TABLE_NAME} "
            "(app_id,idempotency_key,request_fingerprint,state,result_json,created_at,updated_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            app_id,
            idempotency_key,
            request_fingerprint,
            "reserved",
            None,
            now,
            now,
            _expires_at_iso(self._ttl_seconds),
        )
        return None

    async def complete(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result: ExecutionResult | Mapping[str, Any],
    ) -> None:
        record = await self._record(app_id=app_id, idempotency_key=idempotency_key)
        if record is None or record.get("request_fingerprint") != request_fingerprint:
            raise IdempotencyConflictError("idempotency completion does not match reservation")
        await self._run(
            f"UPDATE {_TABLE_NAME} SET state=?, result_json=?, updated_at=? "
            "WHERE app_id=? AND idempotency_key=? AND request_fingerprint=?",
            "completed",
            json.dumps(_public_result(result), ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            _utcnow_iso(),
            app_id,
            idempotency_key,
            request_fingerprint,
        )

    async def commit(self, **kwargs: Any) -> None:
        await self.complete(**kwargs)

    async def abort(self, *, app_id: str, idempotency_key: str, reason: str | None = None) -> None:
        await self._run(
            f"UPDATE {_TABLE_NAME} SET state=?, result_json=?, updated_at=? "
            "WHERE app_id=? AND idempotency_key=? AND state != ?",
            "aborted",
            None,
            _utcnow_iso(),
            app_id,
            idempotency_key,
            "completed",
        )

    async def release(self, *, app_id: str, idempotency_key: str) -> None:
        await self._run(
            f"DELETE FROM {_TABLE_NAME} WHERE app_id=? AND idempotency_key=? AND state != ?",
            app_id,
            idempotency_key,
            "completed",
        )
