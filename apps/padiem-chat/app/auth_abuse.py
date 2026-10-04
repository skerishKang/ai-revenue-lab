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


@dataclass(frozen=True, slots=True)
class AuthAbuseDecision:
    allow_failure_accounting: bool
    reason: str


class AuthAbuseStore(Protocol):
    async def consume(
        self,
        *,
        identifier_key: str,
        network_key: str,
        day_bucket: str,
        identifier_limit: int,
        network_limit: int,
        global_limit: int,
        updated_at: str,
    ) -> bool: ...


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


class D1AuthAbuseStore:
    """Dedicated durable password-login abuse counters.

    This store is intentionally separate from the B14/AI UsageGate authority.
    It persists only opaque HMAC subject keys and bounded daily counters.
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
        chained: bool,
    ) -> Any:
        if chained:
            sql = (
                "INSERT INTO auth_login_abuse_buckets "
                "(subject_type, subject_key, bucket_start, failure_count, updated_at) "
                "SELECT ?, ?, ?, 1, ? WHERE (SELECT changes()) > 0 "
                "ON CONFLICT(subject_type, subject_key, bucket_start) DO UPDATE SET "
                "failure_count=auth_login_abuse_buckets.failure_count + 1, "
                "updated_at=excluded.updated_at "
                "WHERE auth_login_abuse_buckets.failure_count < ? "
                "AND (SELECT changes()) > 0 "
                "RETURNING failure_count"
            )
        else:
            sql = (
                "INSERT INTO auth_login_abuse_buckets "
                "(subject_type, subject_key, bucket_start, failure_count, updated_at) "
                "VALUES (?, ?, ?, 1, ?) "
                "ON CONFLICT(subject_type, subject_key, bucket_start) DO UPDATE SET "
                "failure_count=auth_login_abuse_buckets.failure_count + 1, "
                "updated_at=excluded.updated_at "
                "WHERE auth_login_abuse_buckets.failure_count < ? "
                "RETURNING failure_count"
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

    async def consume(
        self,
        *,
        identifier_key: str,
        network_key: str,
        day_bucket: str,
        identifier_limit: int,
        network_limit: int,
        global_limit: int,
        updated_at: str,
    ) -> bool:
        # Global first bounds row creation under identifier spraying. Each later
        # take is changes()-chained to the previous verdict.
        statements = [
            self._take_statement(
                subject_type="global",
                subject_key="global",
                day_bucket=day_bucket,
                limit=global_limit,
                updated_at=updated_at,
                chained=False,
            ),
            self._take_statement(
                subject_type="network",
                subject_key=network_key,
                day_bucket=day_bucket,
                limit=network_limit,
                updated_at=updated_at,
                chained=True,
            ),
            self._take_statement(
                subject_type="identifier",
                subject_key=identifier_key,
                day_bucket=day_bucket,
                limit=identifier_limit,
                updated_at=updated_at,
                chained=True,
            ),
        ]
        results = await self.db.batch(statements)
        allowed = (
            len(results) >= 3
            and _granted(results[0])
            and _granted(results[1])
            and _granted(results[2])
        )

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

        return allowed


class InMemoryAuthAbuseStore:
    """Network-free test oracle. Never composed as the Production authority."""

    def __init__(self):
        self.counts: dict[tuple[str, str, str], int] = {}
        self.consume_calls = 0

    async def consume(
        self,
        *,
        identifier_key: str,
        network_key: str,
        day_bucket: str,
        identifier_limit: int,
        network_limit: int,
        global_limit: int,
        updated_at: str,
    ) -> bool:
        del updated_at
        self.consume_calls += 1
        keys = [
            (("global", "global", day_bucket), global_limit),
            (("network", network_key, day_bucket), network_limit),
            (("identifier", identifier_key, day_bucket), identifier_limit),
        ]
        for key, limit in keys:
            current = self.counts.get(key, 0)
            if current >= limit:
                return False
            self.counts[key] = current + 1
        return True


class AuthAbuseGate:
    """Failure-accounting gate; never an authentication authority.

    A denied/unavailable decision suppresses mutation of per-account failure
    state. It does not decide whether a verified password may authenticate.
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

    async def authorize_failure_accounting(
        self,
        *,
        identifier: str,
        raw_ip: str | None,
    ) -> AuthAbuseDecision:
        if not self.ready:
            return AuthAbuseDecision(False, "authority_unavailable")

        identifier_key = self._opaque_key("identifier", identifier)
        network_key = self._opaque_key("network", self._network_value(raw_ip))
        if identifier_key is None or network_key is None or self.store is None:
            return AuthAbuseDecision(False, "authority_unavailable")

        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        day_bucket = now.replace(hour=0, minute=0, second=0).isoformat().replace(
            "+00:00", "Z"
        )
        updated_at = now.isoformat().replace("+00:00", "Z")
        try:
            allowed = await self.store.consume(
                identifier_key=identifier_key,
                network_key=network_key,
                day_bucket=day_bucket,
                identifier_limit=IDENTIFIER_DAILY_FAILURE_LIMIT,
                network_limit=NETWORK_DAILY_FAILURE_LIMIT,
                global_limit=GLOBAL_DAILY_FAILURE_LIMIT,
                updated_at=updated_at,
            )
        except Exception:
            return AuthAbuseDecision(False, "authority_unavailable")
        return AuthAbuseDecision(
            bool(allowed),
            "allowed" if allowed else "throttled",
        )
