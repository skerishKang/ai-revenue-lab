from __future__ import annotations

import hashlib
import hmac
import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .config import Settings


IDENTIFIER_DAILY_FAILURE_LIMIT = 5
NETWORK_DAILY_FAILURE_LIMIT = 50
GLOBAL_DAILY_FAILURE_LIMIT = 10_000
_RETENTION_DAYS = 3

_AUTHORITY_UNAVAILABLE_REASON = "authority_unavailable"
_BUDGET_SPENT_REASON = "identifier_budget_spent"
_NORMAL_REASON = "normal"


@dataclass(frozen=True, slots=True)
class AuthAbuseWindow:
    """Authoritative per-identifier failure window for one failed attempt.

    ``identifier_failures`` is the identifier's own durable failure count for the
    current window, including this attempt when it was counted. It is the only
    field a caller is allowed to derive security behaviour from.

    ``network_admitted`` and ``global_admitted`` are advisory storage/volume
    signals. They are deliberately NOT authorization inputs: letting them
    suppress per-identifier accounting is the cross-subject fail-open that lets
    one attacker switch brute-force protection off for unrelated accounts.
    """

    identifier_failures: int
    identifier_admitted: bool
    network_admitted: bool
    global_admitted: bool
    reason: str


UNAVAILABLE_WINDOW = AuthAbuseWindow(
    identifier_failures=0,
    identifier_admitted=False,
    network_admitted=False,
    global_admitted=False,
    reason=_AUTHORITY_UNAVAILABLE_REASON,
)


class AuthAbuseStore(Protocol):
    async def record_failure(
        self,
        *,
        identifier_key: str,
        network_key: str,
        day_bucket: str,
        identifier_limit: int,
        network_limit: int,
        global_limit: int,
        updated_at: str,
    ) -> AuthAbuseWindow: ...


def _rows(result: Any) -> list[Any]:
    if result is None:
        return []
    if isinstance(result, dict):
        rows = result.get("results")
    else:
        rows = getattr(result, "results", None)
    return list(rows or [])


def _granted(result: Any) -> bool:
    return bool(_rows(result))


def _granted_value(result: Any) -> Any:
    rows = _rows(result)
    if not rows:
        return None
    row = rows[0]
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0] if len(row) else None


class D1AuthAbuseStore:
    """Dedicated durable password-login abuse counters.

    This store is intentionally separate from the B14/AI UsageGate authority.
    It persists only opaque HMAC subject keys and bounded daily counters.

    The identifier take is the only authoritative statement. The network and
    global takes run in the same batch but are never chained to it, so neither
    can suppress, freeze, or skip identifier accounting. They exist to bound
    retained row growth and to keep volume observable.
    """

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    def _take_statement(
        self,
        *,
        subject_type: str,
        subject_key: str,
        day_bucket: str,
        limit: int,
        updated_at: str,
        limited: bool,
    ) -> Any:
        # `limited` scopes stop incrementing at their budget and report no rows
        # afterwards. The identifier scope is deliberately NOT limited: it is a
        # rate meter, and a meter that freezes at its cap cannot tell "spent the
        # daily budget" from "one typo", so the escalation floor would never
        # rise. Its own cost is already bounded by the account lock, which caps
        # how often a failure can actually be recorded.
        guard = "WHERE auth_login_abuse_buckets.failure_count < ? " if limited else ""
        sql = (
            "INSERT INTO auth_login_abuse_buckets "
            "(subject_type, subject_key, bucket_start, failure_count, updated_at) "
            "VALUES (?, ?, ?, 1, ?) "
            "ON CONFLICT(subject_type, subject_key, bucket_start) DO UPDATE SET "
            "failure_count=auth_login_abuse_buckets.failure_count + 1, "
            "updated_at=excluded.updated_at "
            f"{guard}"
            "RETURNING failure_count"
        )
        if not limited:
            return self.db.prepare(sql).bind(
                subject_type,
                subject_key,
                day_bucket,
                updated_at,
            )
        return self.db.prepare(sql).bind(
            subject_type,
            subject_key,
            day_bucket,
            updated_at,
            limit,
        )

    async def _cleanup(self, cutoff: str) -> None:
        await self.db.prepare(
            "DELETE FROM auth_login_abuse_buckets WHERE updated_at < ?"
        ).bind(cutoff).run()

    async def record_failure(
        self,
        *,
        identifier_key: str,
        network_key: str,
        day_bucket: str,
        identifier_limit: int,
        network_limit: int,
        global_limit: int,
        updated_at: str,
    ) -> AuthAbuseWindow:
        # Every take is an independent upsert. No statement is gated on the
        # previous statement's row count, so one saturated scope can never
        # decide another scope's outcome.
        results = await self.db.batch(
            [
                self._take_statement(
                    subject_type="identifier",
                    subject_key=identifier_key,
                    day_bucket=day_bucket,
                    limit=identifier_limit,
                    updated_at=updated_at,
                    limited=False,
                ),
                self._take_statement(
                    subject_type="network",
                    subject_key=network_key,
                    day_bucket=day_bucket,
                    limit=network_limit,
                    updated_at=updated_at,
                    limited=True,
                ),
                self._take_statement(
                    subject_type="global",
                    subject_key="global",
                    day_bucket=day_bucket,
                    limit=global_limit,
                    updated_at=updated_at,
                    limited=True,
                ),
            ]
        )

        identifier_admitted = _granted(results[0]) if results else False
        if not identifier_admitted:
            # The identifier meter only fails when the durable statement itself
            # could not run. Never invent a zero that would look like a fresh
            # identifier and drop the caller back to the base window.
            return UNAVAILABLE_WINDOW

        raw_count = _granted_value(results[0])
        try:
            identifier_failures = int(raw_count)
        except (TypeError, ValueError):
            return UNAVAILABLE_WINDOW

        network_admitted = bool(results[1]) and _granted(results[1])
        global_admitted = bool(results[2]) and _granted(results[2])

        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            cutoff = (parsed - timedelta(days=_RETENTION_DAYS)).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z")
            await self._cleanup(cutoff)
        except Exception:
            # Cleanup failure never widens the authorization surface. The
            # guarded counters above remain authoritative for this attempt.
            pass

        return AuthAbuseWindow(
            identifier_failures=identifier_failures,
            identifier_admitted=identifier_failures <= identifier_limit,
            network_admitted=network_admitted,
            global_admitted=global_admitted,
            reason=(
                _NORMAL_REASON
                if identifier_failures <= identifier_limit
                else _BUDGET_SPENT_REASON
            ),
        )


class InMemoryAuthAbuseStore:
    """Network-free test oracle. Never composed as the Production authority."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, str], int] = {}
        self.record_calls = 0

    def _take(self, key: tuple[str, str, str], limit: int) -> bool:
        current = self.counts.get(key, 0)
        if current >= limit:
            return False
        self.counts[key] = current + 1
        return True

    async def record_failure(
        self,
        *,
        identifier_key: str,
        network_key: str,
        day_bucket: str,
        identifier_limit: int,
        network_limit: int,
        global_limit: int,
        updated_at: str,
    ) -> AuthAbuseWindow:
        del updated_at
        self.record_calls += 1
        # The identifier is metered first and independently. Advisory scopes are
        # recorded afterwards so their saturation cannot reach it.
        identifier_key_tuple = ("identifier", identifier_key, day_bucket)
        identifier_failures = self.counts.get(identifier_key_tuple, 0) + 1
        self.counts[identifier_key_tuple] = identifier_failures
        return AuthAbuseWindow(
            identifier_failures=identifier_failures,
            identifier_admitted=identifier_failures <= identifier_limit,
            network_admitted=self._take(
                ("network", network_key, day_bucket), network_limit
            ),
            global_admitted=self._take(
                ("global", "global", day_bucket), global_limit
            ),
            reason=(
                _NORMAL_REASON
                if identifier_failures <= identifier_limit
                else _BUDGET_SPENT_REASON
            ),
        )


class AuthAbuseGate:
    """Per-identifier failure-window authority; never an authentication authority.

    The gate records how many failures the identifier itself has spent in the
    current window. It never decides whether a verified password may
    authenticate, it never suppresses failure recording, and it cannot be used
    to weaken protection: a missing, exhausted, or failing store all leave the
    caller's base lock policy in force.
    """

    def __init__(
        self,
        settings: Settings,
        store: AuthAbuseStore | None,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def ready(self) -> bool:
        return self.store is not None and bool(self.settings.session_secret)

    def _opaque_key(self, domain: str, value: str) -> str | None:
        secret = self.settings.session_secret
        if not secret:
            return None
        digest = hmac.new(
            secret.encode("utf-8"),
            b"padiem-auth-abuse-v1\x00"
            + domain.encode("ascii")
            + b"\x00"
            + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"aab_{domain}_{digest}"

    @staticmethod
    def _network_value(raw_ip: str | None) -> str:
        if raw_ip:
            try:
                return ipaddress.ip_address(raw_ip.strip()).compressed
            except ValueError:
                pass
        return "unavailable"

    async def record_failure_window(
        self,
        *,
        identifier: str,
        raw_ip: str | None,
    ) -> AuthAbuseWindow:
        if not self.ready or self.store is None:
            return UNAVAILABLE_WINDOW

        identifier_key = self._opaque_key("identifier", identifier)
        network_key = self._opaque_key("network", self._network_value(raw_ip))
        if identifier_key is None or network_key is None:
            return UNAVAILABLE_WINDOW

        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        day_bucket = now.replace(hour=0, minute=0, second=0).isoformat().replace(
            "+00:00", "Z"
        )
        updated_at = now.isoformat().replace("+00:00", "Z")
        try:
            return await self.store.record_failure(
                identifier_key=identifier_key,
                network_key=network_key,
                day_bucket=day_bucket,
                identifier_limit=IDENTIFIER_DAILY_FAILURE_LIMIT,
                network_limit=NETWORK_DAILY_FAILURE_LIMIT,
                global_limit=GLOBAL_DAILY_FAILURE_LIMIT,
                updated_at=updated_at,
            )
        except Exception:
            return UNAVAILABLE_WINDOW
