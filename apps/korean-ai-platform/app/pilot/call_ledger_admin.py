"""Owner-facing read API over the B14 call ledger (#5318).

The ledger holds per-call execution facts: which provider actually answered,
each physical attempt a fallback made, the usage the provider reported, and a
cost *estimate* from the configured price snapshot. This surface reads it and
never writes, so no query here can change a route, a credential or a record.

Authentication is the same authority the credential-spending lanes already use
— the HMAC service proof in ``app.pilot.service_proof`` — with two deliberate
differences:

* **no mock-mode bypass.** The completion lanes skip the proof when no
  provider call happens, which is correct for them and wrong here: a mock
  ledger read would return somebody's usage rows while pretending otherwise.
* **GET has an empty body.** The proof is computed over
  ``"<timestamp>." + b""``, which is the existing contract, not a second one.

That means this API is reachable only by an authenticated PADIEM server-side
caller (the Chat/Engine owner console today), never by a browser and never by
an anonymous internet caller. It is the reason no usage row is exposed on the
public worker surface.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Router

from app.pilot.call_ledger import CallLedgerError, LEDGER_ID_PREFIX
from app.pilot.call_ledger_store import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    AGGREGATE_DIMENSIONS,
    FILTERABLE_COLUMNS,
    store_from_env,
)
from app.pilot.service_proof import service_proof_denial

LIST_PATH = "/v1/admin/model-calls"
DETAIL_PATH = "/v1/admin/model-calls/{log_id}"
AGGREGATE_PATH = "/v1/admin/model-calls/aggregate"

router = Router()


def _error(code: str, message: str, *, status: int = 422) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def _denial(request: Request) -> JSONResponse | None:
    """Refuse any caller that cannot present the existing server-to-server proof."""
    denial = await service_proof_denial(request, await request.body())
    if denial is None:
        return None
    return _error(denial.code, "인증된 서버 간 호출만 조회할 수 있습니다.",
                  status=denial.status_code)


def _query(request: Request) -> tuple[dict[str, Any], str | None, str | None, int, str | None]:
    """Parse the bounded query surface. An unknown parameter is refused.

    Filters are a fixed allowlist rather than passthrough column names, so a
    query string can never name a column this API was not meant to expose.
    """
    params = request.query_params
    unknown = sorted(
        key for key in set(params)
        if key not in (set(FILTERABLE_COLUMNS) | {"since", "until", "limit", "group_by"})
    )
    if unknown:
        raise CallLedgerError("unknown query parameter: " + unknown[0])
    filters: dict[str, Any] = {}
    for column in FILTERABLE_COLUMNS:
        raw = params.get(column)
        if raw is None or not raw.strip():
            continue
        filters[column] = raw.strip()[:128]
    limit_raw = params.get("limit")
    try:
        limit = int(limit_raw) if limit_raw else DEFAULT_PAGE_LIMIT
    except ValueError as exc:
        raise CallLedgerError("limit must be an integer") from exc
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise CallLedgerError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")
    since = (params.get("since") or "").strip() or None
    until = (params.get("until") or "").strip() or None
    for name, value in (("since", since), ("until", until)):
        if value is not None and (len(value) > 32 or not _is_timestamp(value)):
            raise CallLedgerError(f"{name} must be an ISO-8601 UTC timestamp")
    return filters, since, until, limit, (params.get("group_by") or "").strip() or None


def _is_timestamp(value: str) -> bool:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "call_ledger_unavailable",
                "message": "호출 이력 저장소가 이 배포에 연결되지 않았습니다.",
            },
            "storage_state": "not_configured",
        },
        headers={"Cache-Control": "no-store"},
    )


def _state(store) -> str:
    """Describe the store that is actually answering this read.

    Reporting the request-env posture while serving rows from another handle
    would tell an operator the ledger is unconfigured exactly when it is not.
    """
    return "bound" if store is not None else "not_configured"


def _resolve_store(request: Request):
    """Return the store this read should use.

    Production resolves the D1 handle from the request-scoped Worker env. A test
    may inject a store on ``app.state`` instead — the same seam
    ``stream_gateway`` already uses for ``app.state.stream_transport`` — because
    the env handle cannot be created inside a TestClient process.
    """
    injected = getattr(request.app.state, "call_ledger_store", None)
    return injected if injected is not None else store_from_env()


@router.route(LIST_PATH, methods=["GET"])
async def list_model_calls(request: Request):
    denial = await _denial(request)
    if denial is not None:
        return denial
    store = _resolve_store(request)
    if store is None:
        return _unavailable()
    try:
        filters, since, until, limit, _group = _query(request)
        rows, total = await _list(store, filters, since, until, limit)
    except CallLedgerError as exc:
        return _error("invalid_query", str(exc))
    except Exception:
        return _error("call_ledger_unavailable", "호출 이력을 읽을 수 없습니다.", status=502)
    return JSONResponse(
        {
            "calls": rows,
            "total": total,
            "limit": limit,
            "storage_state": _state(store),
            "evidence_note": (
                "tokens=missing means the provider reported no usage; it is not a zero. "
                "estimated_usd/krw is a catalog price snapshot, not an invoice."
            ),
        },
        headers={"Cache-Control": "no-store"},
    )


async def _list(store, filters, since, until, limit):
    rows = await store.list_calls(filters=filters, since=since, until=until, limit=limit)
    total = await store.count_calls(filters=filters, since=since, until=until)
    return rows, total


@router.route(AGGREGATE_PATH, methods=["GET"])
async def aggregate_model_calls(request: Request):
    denial = await _denial(request)
    if denial is not None:
        return denial
    store = _resolve_store(request)
    if store is None:
        return _unavailable()
    try:
        filters, since, until, limit, group_by = _query(request)
        if group_by not in AGGREGATE_DIMENSIONS:
            return _error("invalid_group_by", "group_by 대상이 올바르지 않습니다.")
        rows = await store.aggregate(
            group_by, filters=filters, since=since, until=until, limit=limit
        )
    except CallLedgerError as exc:
        return _error("invalid_query", str(exc))
    except Exception:
        return _error("call_ledger_unavailable", "집계를 계산할 수 없습니다.", status=502)
    return JSONResponse(
        {
            "group_by": group_by,
            "rows": rows,
            # Aggregates come from the logical parent rows, so a fallback that
            # made three provider calls still counts its usage once.
            "unit": "logical_request",
            "storage_state": _state(store),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.route(DETAIL_PATH, methods=["GET"])
async def get_model_call(request: Request):
    denial = await _denial(request)
    if denial is not None:
        return denial
    store = _resolve_store(request)
    if store is None:
        return _unavailable()
    log_id = (request.path_params.get("log_id") or "").strip()
    if not log_id.startswith(LEDGER_ID_PREFIX) or len(log_id) > 64:
        return _error("invalid_log_id", "log_id 형식이 올바르지 않습니다.")
    try:
        row = await store.get_call(log_id)
    except Exception:
        return _error("call_ledger_unavailable", "호출 이력을 읽을 수 없습니다.", status=502)
    if row is None:
        return _error("call_not_found", "해당 호출 이력이 없습니다.", status=404)
    return JSONResponse(
        {"call": row, "storage_state": _state(store)},
        headers={"Cache-Control": "no-store"},
    )
