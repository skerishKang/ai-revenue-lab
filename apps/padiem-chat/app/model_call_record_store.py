"""#5318 (slice A) D1-backed store for PADIEM model call records.

One row per actual provider call. This is the audit/observability/cost authority
and is intentionally separate from the usage/quota ledger (D1UsageCounterStore),
which tracks abuse-rate limits only. No customer prompt or completion text is
stored here.

Authority boundary:
- Padiem signed auth / Control Plane owns user and tenant identity. This module
  never accepts a caller-supplied owner; ``user_id`` is the verified session id
  or ``None`` for anonymous traffic.
- Existing PADIEM_CHAT_DB D1 is reused; no request-time DDL is allowed.
- All dynamic values use prepared statement binds.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .history import _row_to_dict, _rows_from_result

_PRODUCT_RE = re.compile(r"^(chat|claw|b66|engine|b14_api|other)\Z")
_STATUS_RE = re.compile(r"^(success|error|timeout)\Z")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_ERROR_CODE_RE = re.compile(r"^[a-z0-9_]{1,64}\Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _validate_product(value: object) -> str:
    if not isinstance(value, str) or _PRODUCT_RE.fullmatch(value) is None:
        raise ValueError("invalid product")
    return value


def _validate_status(value: object) -> str:
    if not isinstance(value, str) or _STATUS_RE.fullmatch(value) is None:
        raise ValueError("invalid status")
    return value


def _nonneg_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid integer")
    if value < 0:
        raise ValueError("invalid integer")
    return value


def _nonneg_float(value: object, *, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid number")
    if value < 0:
        raise ValueError("invalid number")
    return float(value)


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    id: str
    product: str
    user_id: str | None
    provider_id: str
    model_id: str
    called_at: str
    status: str
    retry_count: int = 0
    fallback_used: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_krw: float = 0.0
    error_code: str | None = None
    conversation_id: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ModelCallRecordInput:
    product: str
    provider_id: str
    model_id: str
    status: str
    user_id: str | None = None
    retry_count: int = 0
    fallback_used: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_krw: float = 0.0
    error_code: str | None = None
    conversation_id: str | None = None
    duration_ms: int | None = None
    called_at: str | None = None


class ModelCallRecordStore(Protocol):
    async def record(self, entry: ModelCallRecordInput) -> ModelCallRecord: ...
    async def list_recent(
        self, *, product: str | None = None, limit: int = 50
    ) -> list[ModelCallRecord]: ...
    async def count_by_provider(
        self, *, since: str | None = None
    ) -> list[dict[str, Any]]: ...


class D1ModelCallRecordStore:
    """Cloudflare D1 adapter. All dynamic values use prepared statement binds."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def record(self, entry: ModelCallRecordInput) -> ModelCallRecord:
        product = _validate_product(entry.product)
        status = _validate_status(entry.status)
        if not isinstance(entry.provider_id, str) or _PROVIDER_RE.fullmatch(entry.provider_id) is None:
            raise ValueError("invalid provider_id")
        if not isinstance(entry.model_id, str) or _MODEL_RE.fullmatch(entry.model_id) is None:
            raise ValueError("invalid model_id")
        if entry.error_code is not None and (
            not isinstance(entry.error_code, str) or _ERROR_CODE_RE.fullmatch(entry.error_code) is None
        ):
            raise ValueError("invalid error_code")
        if entry.user_id is not None and not isinstance(entry.user_id, str):
            raise ValueError("invalid user_id")
        if entry.conversation_id is not None and not isinstance(entry.conversation_id, str):
            raise ValueError("invalid conversation_id")
        duration_ms = _nonneg_int(entry.duration_ms) if entry.duration_ms is not None else None

        record_id = "mc_" + uuid.uuid4().hex
        called_at = entry.called_at if entry.called_at is not None else _utc_now()
        record = ModelCallRecord(
            id=record_id,
            product=product,
            user_id=entry.user_id,
            provider_id=entry.provider_id,
            model_id=entry.model_id,
            called_at=called_at,
            status=status,
            retry_count=_nonneg_int(entry.retry_count),
            fallback_used=bool(entry.fallback_used),
            input_tokens=_nonneg_int(entry.input_tokens),
            output_tokens=_nonneg_int(entry.output_tokens),
            reasoning_tokens=_nonneg_int(entry.reasoning_tokens),
            cached_tokens=_nonneg_int(entry.cached_tokens),
            cost_usd=_nonneg_float(entry.cost_usd),
            cost_krw=_nonneg_float(entry.cost_krw),
            error_code=entry.error_code,
            conversation_id=entry.conversation_id,
            duration_ms=duration_ms,
        )

        await (
            self.db.prepare(
                "INSERT INTO model_call_records "
                "(id, product, user_id, provider_id, model_id, called_at, status, "
                "retry_count, fallback_used, input_tokens, output_tokens, "
                "reasoning_tokens, cached_tokens, cost_usd, cost_krw, error_code, "
                "conversation_id, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            .bind(
                record.id,
                record.product,
                record.user_id,
                record.provider_id,
                record.model_id,
                record.called_at,
                record.status,
                record.retry_count,
                1 if record.fallback_used else 0,
                record.input_tokens,
                record.output_tokens,
                record.reasoning_tokens,
                record.cached_tokens,
                record.cost_usd,
                record.cost_krw,
                record.error_code,
                record.conversation_id,
                record.duration_ms,
            )
            .run()
        )
        return record

    async def list_recent(
        self, *, product: str | None = None, limit: int = 50
    ) -> list[ModelCallRecord]:
        if product is not None:
            product = _validate_product(product)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500:
            raise ValueError("invalid limit")
        if product is None:
            result = await self.db.prepare(
                "SELECT id, product, user_id, provider_id, model_id, called_at, status, "
                "retry_count, fallback_used, input_tokens, output_tokens, reasoning_tokens, "
                "cached_tokens, cost_usd, cost_krw, error_code, conversation_id, duration_ms "
                "FROM model_call_records ORDER BY called_at DESC LIMIT ?"
            ).bind(limit).all()
        else:
            result = await self.db.prepare(
                "SELECT id, product, user_id, provider_id, model_id, called_at, status, "
                "retry_count, fallback_used, input_tokens, output_tokens, reasoning_tokens, "
                "cached_tokens, cost_usd, cost_krw, error_code, conversation_id, duration_ms "
                "FROM model_call_records WHERE product = ? ORDER BY called_at DESC LIMIT ?"
            ).bind(product, limit).all()
        rows = _rows_from_result(result)
        return [_row_to_record(row) for row in rows]

    async def count_by_provider(
        self, *, since: str | None = None
    ) -> list[dict[str, Any]]:
        if since is None:
            result = await self.db.prepare(
                "SELECT provider_id, model_id, COUNT(*) AS call_count, "
                "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count, "
                "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                "SUM(cost_usd) AS cost_usd, SUM(cost_krw) AS cost_krw "
                "FROM model_call_records GROUP BY provider_id, model_id "
                "ORDER BY call_count DESC"
            ).all()
        else:
            result = await self.db.prepare(
                "SELECT provider_id, model_id, COUNT(*) AS call_count, "
                "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success_count, "
                "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
                "SUM(cost_usd) AS cost_usd, SUM(cost_krw) AS cost_krw "
                "FROM model_call_records WHERE called_at >= ? GROUP BY provider_id, model_id "
                "ORDER BY call_count DESC"
            ).bind(since).all()
        return [dict(row) for row in _rows_from_result(result)]


def _row_to_record(row: dict[str, Any]) -> ModelCallRecord:
    return ModelCallRecord(
        id=str(row["id"]),
        product=str(row["product"]),
        user_id=row.get("user_id"),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        called_at=str(row["called_at"]),
        status=str(row["status"]),
        retry_count=int(row.get("retry_count") or 0),
        fallback_used=bool(row.get("fallback_used")),
        input_tokens=int(row.get("input_tokens") or 0),
        output_tokens=int(row.get("output_tokens") or 0),
        reasoning_tokens=int(row.get("reasoning_tokens") or 0),
        cached_tokens=int(row.get("cached_tokens") or 0),
        cost_usd=float(row.get("cost_usd") or 0.0),
        cost_krw=float(row.get("cost_krw") or 0.0),
        error_code=row.get("error_code"),
        conversation_id=row.get("conversation_id"),
        duration_ms=row.get("duration_ms"),
    )