"""D1 store for the Business 14 call ledger (#5318).

The binding is a trusted server-side handle, the same shape the Engine evidence
store already uses: ``prepare(sql).bind(*params)``. Values are always bound and
never interpolated; the only strings that reach the SQL text are module
constants and column names checked against an allowlist.

Two behaviours are deliberate:

* **Recording must never break a model call.** :meth:`record` swallows storage
  failures and reports a bounded status instead of raising into the gateway.
  A dashboard that is down is not a reason to fail a customer's completion.
* **Writing is idempotent and append-only.** A retried insert of the same
  ``log_id`` does not create a second record and does not overwrite the first,
  so an at-least-once worker cannot inflate a cost aggregate.

The store keeps no prompt, response or credential column, so there is nothing
here for a caller to overwrite into those positions.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from collections.abc import Mapping
from typing import Any

from app.pilot.call_ledger import CallLedgerError, CallRecord

CALL_TABLE = "b14_model_call"
ATTEMPT_TABLE = "b14_model_call_attempt"

BINDING_NAME = "B14_CALL_LEDGER_D1"

MAX_PAGE_LIMIT = 200
DEFAULT_PAGE_LIMIT = 50
# A page is bounded, but the history is not: the owner console walks a filtered
# range with this cursor so a fourth month of calls is reachable rather than
# silently truncated to the first 200 rows.
MAX_PAGE_OFFSET = 100_000

# Aggregate groupings are a fixed vocabulary. A free-form column name from a
# request would be an injection vector and would also let a caller group by a
# value that was never meant to be a dimension.
AGGREGATE_DIMENSIONS = frozenset({
    "selected_model_id", "selected_provider", "actual_response_model",
    "product", "membership_tier", "outcome", "error_code", "cost_basis",
    "token_source", "protocol", "day",
})

# `day` is a UTC date bucket over the stored `started_at`, not a column. The
# expression is a constant chosen from this table; no part of it comes from a
# request, so grouping by time stays inside the same allowlist discipline as
# grouping by a column.
AGGREGATE_EXPRESSIONS = {
    "day": "substr(started_at, 1, 10)",
}

FILTERABLE_COLUMNS = frozenset({
    "request_id", "log_id", "product", "subject_ref", "tenant_ref",
    "membership_tier", "selected_model_id", "selected_provider",
    "actual_response_model", "outcome", "error_code", "fallback_used",
    "token_source", "cost_basis", "protocol", "streaming",
})

_CALL_COLUMNS = (
    "log_id", "request_id", "endpoint", "product", "origin_source", "origin_request_id",
    "subject_ref", "tenant_ref", "membership_tier", "client_app", "client_version",
    "session_ref", "requested_model_id", "selected_model_id", "selected_provider",
    "selected_upstream_model", "selected_route_id", "actual_response_model", "route_mode",
    "streaming", "protocol", "outcome", "http_status", "error_code", "finish_reason",
    "started_at", "finished_at", "elapsed_ms", "latency_source", "ttft_ms",
    "attempt_count", "fallback_used", "fallback_depth",
    "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
    "token_source", "estimated_usd", "estimated_krw", "cost_basis", "currency",
)

_ATTEMPT_COLUMNS = (
    "log_id", "attempt_index", "provider", "model_id", "upstream_model", "route_id",
    "outcome", "error_code", "retry_index", "actual_response_model", "finish_reason",
    "provider_request_id", "started_at", "finished_at", "elapsed_ms", "latency_source",
    "prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens",
    "token_source", "estimated_usd", "estimated_krw", "cost_basis", "endpoint",
    "protocol", "dispatched",
)

_REQUEST_ENV: ContextVar[Any] = ContextVar("b14_call_ledger_env", default=None)


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def bind_ledger_env(env: Any) -> Token:
    """Publish the Worker env for this request only.

    The D1 handle must not go through the process-environment bridge: that
    bridge coerces values with ``str()``, which would destroy a binding object.
    """
    return _REQUEST_ENV.set(env)


def reset_ledger_env(token: Token) -> None:
    _REQUEST_ENV.reset(token)


def ledger_binding(env: Any = None) -> Any | None:
    """Return the configured D1 handle, or None when this deployment has none."""
    if env is None:
        env = _REQUEST_ENV.get()
    binding = getattr(env, BINDING_NAME, None) if env is not None else None
    return binding if callable(getattr(binding, "prepare", None)) else None


def storage_state(env: Any = None) -> str:
    """Value-free storage posture for a read response."""
    return "bound" if ledger_binding(env) is not None else "not_configured"


class CallLedgerStore:
    """Durable write and read side of the B14 call ledger."""

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("call ledger binding must provide prepare(sql)")
        self._binding = binding

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "CallLedgerStore(configured)"

    async def _run(self, sql: str, *params: Any) -> Any:
        return await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    async def _first(self, sql: str, *params: Any) -> Mapping[str, Any] | None:
        row = await _maybe_await(self._binding.prepare(sql).bind(*params).first())
        return dict(row) if isinstance(row, Mapping) else None

    async def _all(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        rows = await _maybe_await(self._binding.prepare(sql).bind(*params).all())
        results = rows.get("results") if isinstance(rows, Mapping) else rows
        return [dict(row) for row in (results or []) if isinstance(row, Mapping)]

    async def record(self, call: CallRecord) -> str:
        """Append one logical call and its physical attempts.

        Returns a bounded status: ``written``, ``already_recorded`` or
        ``storage_unavailable``. The caller logs the status, never a payload.
        """
        if not isinstance(call, CallRecord):
            return "rejected_contract"
        try:
            parent = call.to_row()
            await self._run(
                f"INSERT OR IGNORE INTO {CALL_TABLE} ({', '.join(_CALL_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in _CALL_COLUMNS)})",
                *[parent[column] for column in _CALL_COLUMNS],
            )
            if not call.attempts:
                return "written"
            statements = []
            for attempt in call.attempts:
                row = attempt.to_row()
                statements.append(
                    self._binding.prepare(
                        f"INSERT OR IGNORE INTO {ATTEMPT_TABLE} "
                        f"({', '.join(_ATTEMPT_COLUMNS)}) "
                        f"VALUES ({', '.join('?' for _ in _ATTEMPT_COLUMNS)})"
                    ).bind(*[row[column] for column in _ATTEMPT_COLUMNS])
                )
            batch = getattr(self._binding, "batch", None)
            if callable(batch):
                await _maybe_await(batch(statements))
            else:
                for statement in statements:
                    await _maybe_await(statement.run())
            return "written"
        except CallLedgerError:
            return "rejected_contract"
        except Exception:
            # A storage fault is recorded as a status, not raised: a model
            # answer already produced for a customer is not undone by the
            # dashboard being unavailable. No exception text is retained,
            # because driver errors can quote bound values.
            return "storage_unavailable"

    async def list_calls(
        self, *, filters: Mapping[str, Any] | None = None,
        since: str | None = None, until: str | None = None, limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clause, params = self._where(filters, since, until)
        bounded = max(1, min(int(limit), MAX_PAGE_LIMIT))
        start = max(0, min(int(offset), MAX_PAGE_OFFSET))
        sql = (
            f"SELECT {', '.join(_CALL_COLUMNS)} FROM {CALL_TABLE}"
            f"{clause} ORDER BY started_at DESC, log_id DESC LIMIT ? OFFSET ?"
        )
        return await self._all(sql, *params, bounded, start)

    async def count_calls(
        self, *, filters: Mapping[str, Any] | None = None,
        since: str | None = None, until: str | None = None,
    ) -> int:
        clause, params = self._where(filters, since, until)
        row = await self._first(f"SELECT COUNT(*) AS total FROM {CALL_TABLE}{clause}", *params)
        return int(row["total"]) if row and row.get("total") is not None else 0

    async def get_call(self, log_id: str) -> dict[str, Any] | None:
        parent = await self._first(
            f"SELECT {', '.join(_CALL_COLUMNS)} FROM {CALL_TABLE} WHERE log_id = ? LIMIT 1",
            log_id,
        )
        if parent is None:
            return None
        parent["attempts"] = await self._all(
            f"SELECT {', '.join(_ATTEMPT_COLUMNS)} FROM {ATTEMPT_TABLE} "
            "WHERE log_id = ? ORDER BY attempt_index ASC",
            log_id,
        )
        return parent

    async def aggregate(
        self, group_by: str, *, filters: Mapping[str, Any] | None = None,
        since: str | None = None, until: str | None = None, limit: int = DEFAULT_PAGE_LIMIT,
    ) -> list[dict[str, Any]]:
        """Summarise consumption per dimension over the *logical* rows.

        Tokens and cost are read from the parent row, not from the attempt
        rows, because several physical attempts can belong to one answered
        request. Summing attempts would bill the same consumption twice.
        """
        if group_by not in AGGREGATE_DIMENSIONS:
            raise ValueError("unsupported aggregate dimension")
        # A bucket name resolves to a constant expression; a column name is
        # already inside the allowlist, so the interpolated text is never the
        # caller's.
        expression = AGGREGATE_EXPRESSIONS.get(group_by, group_by)
        clause, params = self._where(filters, since, until)
        bounded = max(1, min(int(limit), MAX_PAGE_LIMIT))
        sql = (
            f"SELECT {expression} AS dimension, COUNT(*) AS calls, "
            "SUM(CASE WHEN token_source = 'measured' THEN 1 ELSE 0 END) AS calls_with_tokens, "
            "SUM(CASE WHEN token_source = 'missing' THEN 1 ELSE 0 END) AS calls_without_tokens, "
            "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS succeeded, "
            "SUM(CASE WHEN outcome = 'error' THEN 1 ELSE 0 END) AS failed, "
            "SUM(CASE WHEN fallback_used = 1 THEN 1 ELSE 0 END) AS fallbacks, "
            "SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens, "
            "SUM(total_tokens) AS total_tokens, SUM(reasoning_tokens) AS reasoning_tokens, "
            "SUM(estimated_usd) AS estimated_usd, SUM(estimated_krw) AS estimated_krw, "
            "AVG(elapsed_ms) AS avg_elapsed_ms, AVG(ttft_ms) AS avg_ttft_ms "
            f"FROM {CALL_TABLE}{clause} GROUP BY {expression} "
            # A trend is read left to right; a ranking is read by weight.
            + ("ORDER BY dimension ASC " if group_by == "day" else "ORDER BY calls DESC ")
            + "LIMIT ?"
        )
        return await self._all(sql, *params, bounded)

    @staticmethod
    def _where(
        filters: Mapping[str, Any] | None, since: str | None, until: str | None,
    ) -> tuple[str, list[Any]]:
        parts: list[str] = []
        params: list[Any] = []
        for key, value in (filters or {}).items():
            if value is None:
                continue
            if key not in FILTERABLE_COLUMNS:
                raise ValueError("unsupported call ledger filter")
            parts.append(f"{key} = ?")
            params.append(value)
        if since:
            parts.append("started_at >= ?")
            params.append(since)
        if until:
            parts.append("started_at <= ?")
            params.append(until)
        return (f" WHERE {' AND '.join(parts)}" if parts else ""), params


async def record_call(call: CallRecord, env: Any = None) -> str:
    """Module-level write used by the gateways; never raises into the request."""
    binding = ledger_binding(env)
    if binding is None:
        return "not_configured"
    try:
        return await CallLedgerStore(binding).record(call)
    except Exception:
        return "storage_unavailable"


def store_from_env(env: Any = None) -> CallLedgerStore | None:
    binding = ledger_binding(env)
    return None if binding is None else CallLedgerStore(binding)
