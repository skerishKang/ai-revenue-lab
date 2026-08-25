from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from .config import Settings


@dataclass(frozen=True, slots=True)
class UsageDecision:
    allowed: bool
    code: str | None = None
    status_code: int = 200
    user_message: str | None = None
    subject_type: str | None = None
    bucket_type: str | None = None
    count: int | None = None
    limit: int | None = None
    retry_after_seconds: int | None = None


class UsageCounterStore(Protocol):
    async def consume(
        self,
        *,
        subject_type: str,
        subject_key: str,
        minute_bucket: str,
        day_bucket: str,
        burst_limit: int,
        daily_limit: int,
        global_daily_limit: int,
        updated_at: str,
    ) -> UsageDecision: ...


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _limit_decision(
    code: str,
    *,
    subject_type: str,
    bucket_type: str,
    limit: int,
    retry_after_seconds: int | None,
) -> UsageDecision:
    messages = {
        "rate_limited": "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
        "quota_exhausted": "오늘 사용할 수 있는 AI 요청 한도에 도달했습니다.",
        "service_limit_reached": "오늘의 서비스 사용 한도에 도달했습니다. 다음에 다시 이용해 주세요.",
    }
    return UsageDecision(
        allowed=False,
        code=code,
        status_code=429,
        user_message=messages[code],
        subject_type=subject_type,
        bucket_type=bucket_type,
        limit=limit,
        retry_after_seconds=retry_after_seconds,
    )


class D1UsageCounterStore:
    """Cloudflare D1-backed bounded counters using prepared statements only.

    A rejected request is compensated by decrementing any earlier bucket increments
    from the same authorization attempt. If compensation itself fails, the result is
    conservative over-counting; provider execution still remains fail-closed.
    """

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _increment_if_below(
        self,
        *,
        subject_type: str,
        subject_key: str,
        bucket_type: str,
        bucket_start: str,
        limit: int,
        updated_at: str,
    ) -> int | None:
        statement = self.db.prepare(
            "INSERT INTO live_usage_buckets "
            "(subject_type, subject_key, bucket_type, bucket_start, request_count, updated_at) "
            "VALUES (?, ?, ?, ?, 1, ?) "
            "ON CONFLICT(subject_type, subject_key, bucket_type, bucket_start) DO UPDATE SET "
            "request_count=live_usage_buckets.request_count + 1, updated_at=excluded.updated_at "
            "WHERE live_usage_buckets.request_count < ? "
            "RETURNING request_count"
        ).bind(subject_type, subject_key, bucket_type, bucket_start, updated_at, limit)
        row = _row_to_dict(await statement.first())
        if row is None:
            return None
        try:
            return int(row.get("request_count"))
        except (TypeError, ValueError):
            return None

    async def _refund(
        self,
        *,
        subject_type: str,
        subject_key: str,
        bucket_type: str,
        bucket_start: str,
        updated_at: str,
    ) -> None:
        statement = self.db.prepare(
            "UPDATE live_usage_buckets SET request_count=request_count - 1, updated_at=? "
            "WHERE subject_type=? AND subject_key=? AND bucket_type=? AND bucket_start=? AND request_count > 0"
        ).bind(updated_at, subject_type, subject_key, bucket_type, bucket_start)
        await statement.run()

    async def _cleanup(self, cutoff: str) -> None:
        statement = self.db.prepare("DELETE FROM live_usage_buckets WHERE updated_at < ?").bind(cutoff)
        await statement.run()

    async def consume(
        self,
        *,
        subject_type: str,
        subject_key: str,
        minute_bucket: str,
        day_bucket: str,
        burst_limit: int,
        daily_limit: int,
        global_daily_limit: int,
        updated_at: str,
    ) -> UsageDecision:
        acquired: list[tuple[str, str, str, str]] = []

        async def take(stype: str, skey: str, btype: str, bstart: str, limit: int) -> int | None:
            count = await self._increment_if_below(
                subject_type=stype,
                subject_key=skey,
                bucket_type=btype,
                bucket_start=bstart,
                limit=limit,
                updated_at=updated_at,
            )
            if count is not None:
                acquired.append((stype, skey, btype, bstart))
            return count

        async def refund_acquired() -> None:
            for stype, skey, btype, bstart in reversed(acquired):
                try:
                    await self._refund(
                        subject_type=stype,
                        subject_key=skey,
                        bucket_type=btype,
                        bucket_start=bstart,
                        updated_at=updated_at,
                    )
                except Exception:
                    # Conservative over-counting is safer than allowing provider execution.
                    pass

        minute_count = await take(subject_type, subject_key, "minute", minute_bucket, burst_limit)
        if minute_count is None:
            return _limit_decision(
                "rate_limited",
                subject_type=subject_type,
                bucket_type="minute",
                limit=burst_limit,
                retry_after_seconds=60,
            )

        daily_count = await take(subject_type, subject_key, "day", day_bucket, daily_limit)
        if daily_count is None:
            await refund_acquired()
            return _limit_decision(
                "quota_exhausted",
                subject_type=subject_type,
                bucket_type="day",
                limit=daily_limit,
                retry_after_seconds=None,
            )

        global_count = await take("global", "global", "global_day", day_bucket, global_daily_limit)
        if global_count is None:
            await refund_acquired()
            return _limit_decision(
                "service_limit_reached",
                subject_type=subject_type,
                bucket_type="global_day",
                limit=global_daily_limit,
                retry_after_seconds=None,
            )

        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            cutoff = (parsed - timedelta(days=8)).isoformat(timespec="seconds").replace("+00:00", "Z")
            await self._cleanup(cutoff)
        except Exception:
            pass

        return UsageDecision(
            allowed=True,
            subject_type=subject_type,
            bucket_type="day",
            count=daily_count,
            limit=daily_limit,
        )


class InMemoryUsageCounterStore:
    """Deterministic network-free test store with the same policy semantics."""

    def __init__(self):
        self.counts: dict[tuple[str, str, str, str], int] = {}
        self.consume_calls = 0

    async def consume(
        self,
        *,
        subject_type: str,
        subject_key: str,
        minute_bucket: str,
        day_bucket: str,
        burst_limit: int,
        daily_limit: int,
        global_daily_limit: int,
        updated_at: str,
    ) -> UsageDecision:
        self.consume_calls += 1
        keys = [
            ((subject_type, subject_key, "minute", minute_bucket), burst_limit, "rate_limited", 60),
            ((subject_type, subject_key, "day", day_bucket), daily_limit, "quota_exhausted", None),
            (("global", "global", "global_day", day_bucket), global_daily_limit, "service_limit_reached", None),
        ]
        acquired: list[tuple[str, str, str, str]] = []
        for key, limit, code, retry_after in keys:
            current = self.counts.get(key, 0)
            if current >= limit:
                for acquired_key in acquired:
                    self.counts[acquired_key] = max(0, self.counts.get(acquired_key, 0) - 1)
                return _limit_decision(
                    code,
                    subject_type=subject_type,
                    bucket_type=key[2],
                    limit=limit,
                    retry_after_seconds=retry_after,
                )
            self.counts[key] = current + 1
            acquired.append(key)
        return UsageDecision(
            allowed=True,
            subject_type=subject_type,
            bucket_type="day",
            count=self.counts[(subject_type, subject_key, "day", day_bucket)],
            limit=daily_limit,
        )


class UsageGate:
    def __init__(
        self,
        settings: Settings,
        store: UsageCounterStore | None,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def quota_store_bound(self) -> bool:
        return self.store is not None

    @property
    def ready(self) -> bool:
        return self.store is not None and bool(self.settings.quota_salt)

    def _anonymous_subject(self, raw_ip: str | None) -> str | None:
        if not self.settings.quota_salt or not raw_ip:
            return None
        try:
            normalized = ipaddress.ip_address(raw_ip.strip()).compressed
        except ValueError:
            return None
        digest = hashlib.sha256(
            self.settings.quota_salt.encode("utf-8") + b"\x00" + normalized.encode("ascii")
        ).hexdigest()
        return "anon_" + digest

    async def authorize(self, *, raw_ip: str | None, user_id: str | None) -> UsageDecision:
        # Mock execution makes zero B14/provider calls and must consume zero quota.
        if self.settings.runtime_mode != "b14":
            return UsageDecision(allowed=True, subject_type="mock")

        if self.store is None or not self.settings.quota_salt:
            return UsageDecision(
                allowed=False,
                code="live_abuse_gate_unavailable",
                status_code=503,
                user_message="현재 AI 연결을 안전하게 사용할 준비가 되지 않았습니다.",
            )

        if user_id is not None:
            subject_type = "user"
            subject_key = user_id
            burst_limit = self.settings.user_burst_limit
            daily_limit = self.settings.user_daily_limit
        else:
            subject_type = "anonymous"
            subject_key = self._anonymous_subject(raw_ip)
            if subject_key is None:
                return UsageDecision(
                    allowed=False,
                    code="live_identity_unavailable",
                    status_code=503,
                    user_message="현재 익명 AI 사용을 안전하게 확인할 수 없습니다.",
                    subject_type="anonymous",
                )
            burst_limit = self.settings.anonymous_burst_limit
            daily_limit = self.settings.anonymous_daily_limit

        now = self._clock().astimezone(timezone.utc).replace(microsecond=0)
        minute_bucket = now.replace(second=0).isoformat().replace("+00:00", "Z")
        day_bucket = now.replace(hour=0, minute=0, second=0).isoformat().replace("+00:00", "Z")
        updated_at = now.isoformat().replace("+00:00", "Z")

        try:
            return await self.store.consume(
                subject_type=subject_type,
                subject_key=subject_key,
                minute_bucket=minute_bucket,
                day_bucket=day_bucket,
                burst_limit=burst_limit,
                daily_limit=daily_limit,
                global_daily_limit=self.settings.global_daily_limit,
                updated_at=updated_at,
            )
        except Exception:
            return UsageDecision(
                allowed=False,
                code="live_abuse_gate_unavailable",
                status_code=503,
                user_message="현재 AI 사용 한도를 확인할 수 없습니다.",
                subject_type=subject_type,
            )
