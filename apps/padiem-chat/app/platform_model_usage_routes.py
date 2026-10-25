"""#5318 owner console read of the B14 model call ledger.

The ledger lives on the B14 worker and is read through that worker's own
admin API, which only accepts the HMAC service proof a server can compute.
This module is that server side: it checks the console's existing global
model-admin authority, signs the read with the binding secret the deployment
already has, and projects the rows for the owner screen.

What this deliberately does not do:

* no new authority, router, engine or store — one read path, the merged API;
* no secret, proof, session or header ever reaches the browser;
* no invented zeros. A provider that reported no usage stays `missing`, a
  catalog price that was never configured stays `unknown`, and a product or
  tier no caller declared stays `unknown`/`미수집` rather than reading as free.
"""
from __future__ import annotations

import inspect
import json
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Vary": "Cookie",
}

LEDGER_LIST_PATH = "/api/pilot/v1/admin/model-calls"
LEDGER_AGGREGATE_PATH = "/api/pilot/v1/admin/model-calls/aggregate"
LEDGER_DETAIL_PREFIX = "/api/pilot/v1/admin/model-calls/"
LOG_ID_PREFIX = "b14call_"

# The B14 API's own vocabulary. Anything else is refused here before a request
# leaves, so the console cannot ask the ledger for a column it never exposes.
LEDGER_FILTERS = (
    "request_id", "log_id", "product", "subject_ref", "tenant_ref",
    "membership_tier", "selected_model_id", "selected_provider",
    "actual_response_model", "outcome", "error_code", "fallback_used",
    "token_source", "cost_basis", "protocol", "streaming",
)
LEDGER_GROUP_BY = (
    "selected_model_id", "selected_provider", "actual_response_model",
    "product", "membership_tier", "outcome", "error_code", "cost_basis",
    "token_source", "protocol", "day",
)
PRODUCTS = ("chat", "claw", "b66", "engine", "api", "unknown")
OUTCOMES = ("success", "error", "aborted")
TIERS = ("FREE", "PLUS", "PRO", "MAX")

PAGE_LIMIT_MAX = 200
PAGE_OFFSET_MAX = 100_000
MAX_VALUE_LENGTH = 128

# Values the owner screen must never read as a measured zero.
_MISSING = "missing"


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_NO_STORE)


def _bounded_filters(request: Request) -> tuple[dict[str, str], str | None]:
    """Return the allowed filters, or an error code for anything malformed."""
    selected: dict[str, str] = {}
    for key in request.query_params:
        if key in ("since", "until", "limit", "offset", "group_by"):
            continue
        if key not in LEDGER_FILTERS:
            return selected, f"unsupported_filter:{key}"
        raw = (request.query_params.get(key) or "").strip()
        if not raw:
            continue
        if len(raw) > MAX_VALUE_LENGTH:
            return selected, f"filter_value_too_long:{key}"
        selected[key] = raw
    for value in (request.query_params.get("since"), request.query_params.get("until")):
        if value and len(value.strip()) > 32:
            return selected, "timestamp_too_long"
    return selected, None


def _page(request: Request) -> tuple[int, int, str | None]:
    try:
        limit = int(request.query_params.get("limit") or 50)
        offset = int(request.query_params.get("offset") or 0)
    except ValueError:
        return 50, 0, "page_must_be_an_integer"
    if not 1 <= limit <= PAGE_LIMIT_MAX:
        return limit, offset, "page_limit_out_of_range"
    if not 0 <= offset <= PAGE_OFFSET_MAX:
        return limit, offset, "page_offset_out_of_range"
    return limit, offset, None


def _query_string(pairs: list[tuple[str, str]]) -> str:
    return "?" + "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in pairs) if pairs else ""


def _transport(request: Request):
    return getattr(request.app.state, "b14_service_transport", None)


async def _read(request: Request, path: str) -> tuple[int, Any, str | None]:
    """One signed server-to-server ledger read. Never raises into the screen."""
    transport = _transport(request)
    if transport is None or not callable(getattr(transport, "get_json", None)):
        return 0, None, "model_usage_transport_unconfigured"
    try:
        status, body = await transport.get_json(path)
        if inspect.isawaitable(body):
            body = await body
    except Exception:
        # A transport or binding fault can quote internal detail; the screen
        # gets one bounded code instead.
        return 0, None, "model_usage_read_failed"
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return status, None, "model_usage_response_unreadable"
    return status, payload, None


def _usage_state(row: dict[str, Any]) -> str:
    return "measured" if row.get("token_source") == "measured" else _MISSING


def _cost_state(row: dict[str, Any]) -> str:
    basis = row.get("cost_basis")
    if basis == "configured_snapshot":
        return "catalog_estimate"
    if basis == "known_free":
        return "known_free"
    return "unknown"


def _project_call(row: dict[str, Any]) -> dict[str, Any]:
    """Keep every stored field, then add the states the screen has to show.

    A dashboard that prints `0` for a missing token count tells the owner the
    call was free. The stored row already separates the two; these two labels
    carry that separation across the JSON boundary without a new authority.
    """
    projected = dict(row)
    projected["usage_state"] = _usage_state(row)
    projected["cost_state"] = _cost_state(row)
    declared = row.get("origin_source")
    projected["identity_source"] = declared if declared in (
        "b14_observed", "caller_declared", "unknown") else "unknown"
    projected["membership_tier_declared"] = bool(row.get("membership_tier"))
    if "attempts" in row and isinstance(row["attempts"], list):
        projected["attempts"] = [
            {**attempt,
             "usage_state": _usage_state(attempt),
             "cost_state": _cost_state(attempt),
             "dispatched": bool(attempt.get("dispatched"))}
            for attempt in row["attempts"]
        ]
    return projected


async def _authorized(request: Request) -> JSONResponse | None:
    """The console's existing global model-admin authority, nothing new.

    Role comes from the injected authorizer only: never from an email string, a
    browser flag, a query parameter or the B66 product admin.
    """
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return _error(401, "authentication_required")
    authority = getattr(request.app.state, "central_model_admin_authorizer", None)
    verify = getattr(authority, "is_global_model_admin", None)
    if not callable(verify):
        return _error(503, "central_admin_not_configured")
    try:
        result = verify(user_id=owner)
        is_admin = await result if inspect.isawaitable(result) else result
    except Exception:
        return _error(503, "central_admin_authority_unavailable")
    return None if is_admin is True else _error(403, "global_model_admin_forbidden")


async def model_usage_calls(request: Request) -> JSONResponse:
    denial = await _authorized(request)
    if denial is not None:
        return denial
    filters, bad = _bounded_filters(request)
    if bad is not None:
        return _error(422, bad)
    _limit, _offset, bad_page = _page(request)
    if bad_page is not None:
        return _error(422, bad_page)
    pairs = sorted(filters.items())
    for name in ("since", "until"):
        value = (request.query_params.get(name) or "").strip()
        if value:
            pairs.append((name, value))
    pairs.append(("limit", str(_limit)))
    pairs.append(("offset", str(_offset)))
    status, payload, failure = await _read(request, LEDGER_LIST_PATH + _query_string(pairs))
    if failure is not None:
        return _error(503 if failure.endswith("unconfigured") else 502, failure)
    if status == 503 and isinstance(payload, dict):
        # The ledger is not bound in that deployment: an empty screen would read
        # as "no model ran", so the storage posture is passed through verbatim.
        return JSONResponse({"ok": False, "calls": [], "total": 0,
                             "storage_state": "not_configured",
                             "error": {"code": "call_ledger_unavailable"}},
                            status_code=503, headers=_NO_STORE)
    if not 200 <= status < 300 or not isinstance(payload, dict):
        return _error(502, "model_usage_upstream_error")
    rows = payload.get("calls")
    return JSONResponse(
        {
            "ok": True,
            "calls": [_project_call(row) for row in rows if isinstance(row, dict)],
            "total": payload.get("total"),
            # The page the caller asked for and the row count the ledger saw are
            # both echoed: a truncated read must be visible as a gap between the
            # two rather than a page that silently reports someone else's bounds.
            "limit": _limit,
            "offset": _offset,
            "storage_state": payload.get("storage_state"),
            "evidence_note": payload.get("evidence_note"),
            "requested": {"filters": filters, "limit": _limit, "offset": _offset},
        },
        headers=_NO_STORE,
    )


async def model_usage_call_detail(request: Request) -> JSONResponse:
    denial = await _authorized(request)
    if denial is not None:
        return denial
    log_id = (request.path_params.get("log_id") or "").strip()
    if not log_id.startswith(LOG_ID_PREFIX) or len(log_id) > 64:
        return _error(422, "invalid_log_id")
    status, payload, failure = await _read(request, LEDGER_DETAIL_PREFIX + quote(log_id, safe=""))
    if failure is not None:
        return _error(503 if failure.endswith("unconfigured") else 502, failure)
    if status == 404:
        return _error(404, "call_not_found")
    if not 200 <= status < 300 or not isinstance(payload, dict) or not isinstance(payload.get("call"), dict):
        return _error(502, "model_usage_upstream_error")
    return JSONResponse(
        {"ok": True, "call": _project_call(payload["call"]),
         "storage_state": payload.get("storage_state")},
        headers=_NO_STORE,
    )


async def model_usage_aggregate(request: Request) -> JSONResponse:
    denial = await _authorized(request)
    if denial is not None:
        return denial
    group_by = (request.query_params.get("group_by") or "").strip()
    if group_by not in LEDGER_GROUP_BY:
        return _error(422, "unsupported_group_by")
    filters, bad = _bounded_filters(request)
    if bad is not None:
        return _error(422, bad)
    pairs = sorted(filters.items())
    for name in ("since", "until"):
        value = (request.query_params.get(name) or "").strip()
        if value:
            pairs.append((name, value))
    pairs.append(("group_by", group_by))
    status, payload, failure = await _read(request, LEDGER_AGGREGATE_PATH + _query_string(pairs))
    if failure is not None:
        return _error(503 if failure.endswith("unconfigured") else 502, failure)
    if status == 503 and isinstance(payload, dict):
        return JSONResponse({"ok": False, "group_by": group_by, "rows": [],
                             "storage_state": "not_configured",
                             "error": {"code": "call_ledger_unavailable"}},
                            status_code=503, headers=_NO_STORE)
    if not 200 <= status < 300 or not isinstance(payload, dict):
        return _error(502, "model_usage_upstream_error")
    rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
    return JSONResponse(
        {
            "ok": True,
            "group_by": group_by,
            "rows": rows,
            "unit": payload.get("unit"),
            "storage_state": payload.get("storage_state"),
            # A bucket with no measured usage is reported as such: a SUM over
            # nothing is NULL in SQL, and NULL printed as 0 would claim a free
            # model to the owner.
            "unmeasured_rows": sum(1 for row in rows if not row.get("calls_with_tokens")),
        },
        headers=_NO_STORE,
    )


# The screen reads one authority it already trusts: the global model admin. This
# module adds none.
MODEL_USAGE_NEW_AUTHORITY = False
MODEL_USAGE_WRITES = False
