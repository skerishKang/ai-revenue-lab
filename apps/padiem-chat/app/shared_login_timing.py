"""Request-local, allowlisted timing details for the shared-login callback."""
from __future__ import annotations

from contextvars import ContextVar
import math

_TIMING_ORDER = (
    "assertion_build", "assertion_sign", "assertion_key_refresh",
    "exchange_headers", "exchange_body", "exchange_total",
    "portal_client_auth", "portal_code_exchange", "portal_token_sign", "portal_total",
    "account_token_verify", "identity_rpc",
    "sqlite_auth_session_read", "sqlite_auth_link_read", "sqlite_auth_revision_read",
    "sqlite_auth_session_expired_delete", "sqlite_auth_link_expired_delete",
    "sqlite_auth_session_upsert", "sqlite_auth_link_upsert",
    "profile_token_verify", "profile_user_upsert", "profile_notification",
)
_ALLOWED = frozenset(_TIMING_ORDER)
_ACTIVE: ContextVar[dict[str, tuple[int, float]] | None] = ContextVar(
    "shared_login_timing_details", default=None
)


def begin_login_timings():
    """Start a request-local collector; async child tasks inherit this collector."""
    stats: dict[str, tuple[int, float]] = {}
    return _ACTIVE.set(stats), stats


def end_login_timings(token) -> None:
    _ACTIVE.reset(token)


def record_login_timing(name: str, duration_ms: float) -> None:
    """Accumulate only fixed labels and finite durations; never accept SQL or values."""
    if name not in _ALLOWED:
        return
    try:
        duration = float(duration_ms)
    except (TypeError, ValueError):
        return
    if not math.isfinite(duration):
        return
    stats = _ACTIVE.get()
    if stats is None:
        return
    count, total = stats.get(name, (0, 0.0))
    stats[name] = (count + 1, total + max(0.0, duration))


def format_login_timing_fields(stats: dict[str, tuple[int, float]]) -> list[str]:
    fields = []
    for name in _TIMING_ORDER:
        count, total = stats.get(name, (0, 0.0))
        if count:
            fields.append(f"{name}_ms={int(round(total))}")
            fields.append(f"{name}_n={count}")
    return fields
