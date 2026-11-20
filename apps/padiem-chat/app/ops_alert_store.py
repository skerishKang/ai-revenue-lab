"""#8105: 운영센터 알림 대기함 저장소 — 새 의견·회차 점수.

B66 회원 문의(`b66_member_inquiries.deliver_inquiry`)와 같은 모양이다:
채널별 영수증이 있어 재시도해도 이미 보낸 채널로는 다시 가지 않는다.

담는 값은 종류·분류·대상 번호뿐이다. 의견 본문·이메일·회원 이름·회원 id는
어떤 컬럼에도 넣지 않는다(외부 서비스 경유). 시계는 주입한다.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .d1_rows import rows_from_result
from .ops_notify_event import SITE_LINKS, event_target, valid_event

ALERT_ID = re.compile(r"opsalr_[0-9a-f]{32}\Z")
TARGET_ID = re.compile(r"[A-Za-z0-9_]{1,128}\Z")
KINDS = ("product_feedback", "site_feedback", "round_score")
CHANNELS = ("telegram", "discord", "email")
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
_COLUMNS = (
    "alert_id, kind, target_id, label, created_at, delivered_at,"
    " notify_site, notify_audience, notify_kind, notify_title,"
    " notify_source_id, notify_day, notify_count"
)
_KST = timezone(timedelta(hours=9))


class OpsAlertInvalid(Exception):
    pass


class OpsAlertUnavailable(Exception):
    pass


def _stamp(now: Callable[[], datetime] | None) -> str:
    moment = (now or (lambda: datetime.now(timezone.utc)))()
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class D1OpsAlertStore:
    def __init__(self, db: Any, *, now: Callable[[], datetime] | None = None):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("ops alert binding missing")
        self._db = db
        self._now = now

    async def _rows(self, sql: str, *values):
        try:
            result = await self._db.prepare(sql).bind(*values).run()
        except Exception:
            raise OpsAlertUnavailable() from None
        return [dict(row.to_py() if callable(getattr(row, "to_py", None)) else row)
                for row in rows_from_result(result)]

    async def enqueue(self, *, kind: str, target_id: str, label: str) -> dict | None:
        """같은 대상은 한 번만 쌓는다(이미 있으면 None)."""
        if kind not in KINDS:
            raise OpsAlertInvalid()
        if not isinstance(target_id, str) or TARGET_ID.fullmatch(target_id) is None:
            raise OpsAlertInvalid()
        if not isinstance(label, str) or _LABEL.fullmatch(label) is None:
            raise OpsAlertInvalid()
        same = await self._rows(
            "SELECT alert_id FROM ops_alert_outbox WHERE kind=? AND target_id=?",
            kind, target_id)
        if same:
            return None
        alert_id = "opsalr_" + secrets.token_hex(16)
        await self._rows(
            "INSERT INTO ops_alert_outbox (alert_id, kind, target_id, label,"
            " created_at, delivered_at) VALUES (?,?,?,?,?,NULL)",
            alert_id, kind, target_id, label, _stamp(self._now))
        return {"alert_id": alert_id, "kind": kind, "target_id": target_id,
                "label": label}

    def _moment(self) -> datetime:
        return (self._now or (lambda: datetime.now(timezone.utc)))()

    async def enqueue_event(self, event: dict) -> str | None:
        """One atomic insert, deduplicated even under concurrent requests."""
        if not valid_event(event):
            raise OpsAlertInvalid()
        site, kind, audience = (event[key] for key in ("site", "kind", "audience"))
        source_id = event["source_id"]
        moment = self._moment()
        rows = await self._rows(
            "INSERT INTO ops_alert_outbox (alert_id, kind, target_id, label,"
            " created_at, notify_site, notify_audience, notify_kind, notify_title,"
            " notify_source_id, notify_day) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(kind,target_id) DO NOTHING RETURNING alert_id",
            "opsalr_" + secrets.token_hex(16), "site_feedback",
            event_target(site, kind, source_id), site, _stamp(lambda: moment),
            site, audience, kind, event["title"] if audience == "real" else None,
            source_id if audience == "real" else None,
            moment.astimezone(_KST).date().isoformat())
        return rows[0]["alert_id"] if rows else None

    async def materialize_due_summaries(self) -> None:
        """Persist a single receipt-bearing outbox row for each closed KST day/site."""
        moment = self._moment()
        await self._rows(
            "INSERT INTO ops_alert_outbox (alert_id,kind,target_id,label,created_at,"
            " notify_site,notify_audience,notify_day,notify_count)"
            " SELECT 'opsalr_' || lower(hex(randomblob(16))), 'site_feedback',"
            " 'notify_summary_' || notify_site || '_' || notify_day, notify_site,"
            " ?, notify_site, 'summary', notify_day, COUNT(*)"
            " FROM ops_alert_outbox WHERE notify_audience='ai'"
            " AND notify_day < ? AND delivered_at IS NULL"
            " GROUP BY notify_site,notify_day"
            " ON CONFLICT(kind,target_id) DO NOTHING",
            _stamp(lambda: moment), moment.astimezone(_KST).date().isoformat())

    async def pending(self, limit: int = 5, *, preferred: str | None = None) -> list[dict]:
        bounded = limit if type(limit) is int and 0 < limit <= 20 else 5
        return await self._rows(
            "SELECT " + _COLUMNS + " FROM ops_alert_outbox"
            " WHERE delivered_at IS NULL AND (notify_audience IS NULL OR notify_audience!='ai')"
            " ORDER BY CASE WHEN alert_id=? THEN 0 ELSE 1 END, created_at ASC, alert_id ASC"
            " LIMIT ?", preferred, bounded)

    async def receipt_exists(self, alert_id: str, channel: str) -> bool:
        if not isinstance(alert_id, str) or ALERT_ID.fullmatch(alert_id) is None:
            return False
        if channel not in CHANNELS:
            return False
        rows = await self._rows(
            "SELECT alert_id FROM ops_alert_delivery"
            " WHERE alert_id=? AND channel=? AND delivered_at IS NOT NULL",
            alert_id, channel)
        return bool(rows)

    async def record_success(self, alert_id: str, channel: str) -> None:
        if not isinstance(alert_id, str) or ALERT_ID.fullmatch(alert_id) is None:
            raise OpsAlertInvalid()
        if channel not in CHANNELS:
            raise OpsAlertInvalid()
        moment = _stamp(self._now)
        await self._rows(
            "INSERT INTO ops_alert_delivery (alert_id, channel, delivered_at,"
            " failed_at, attempts) VALUES (?,?,?,NULL,1)"
            " ON CONFLICT(alert_id, channel) DO UPDATE SET"
            " delivered_at=excluded.delivered_at, attempts=ops_alert_delivery.attempts+1",
            alert_id, channel, moment)

    async def record_failure(self, alert_id: str, channel: str) -> None:
        if not isinstance(alert_id, str) or ALERT_ID.fullmatch(alert_id) is None:
            raise OpsAlertInvalid()
        if channel not in CHANNELS:
            raise OpsAlertInvalid()
        moment = _stamp(self._now)
        await self._rows(
            "INSERT INTO ops_alert_delivery (alert_id, channel, delivered_at,"
            " failed_at, attempts) VALUES (?,?,NULL,?,1)"
            " ON CONFLICT(alert_id, channel) DO UPDATE SET"
            " failed_at=excluded.failed_at, attempts=ops_alert_delivery.attempts+1",
            alert_id, channel, moment)

    async def complete(self, alert_id: str, channels: tuple[str, ...]) -> bool:
        if not channels:
            return False
        for channel in channels:
            if not await self.receipt_exists(alert_id, channel):
                return False
        await self._rows(
            "UPDATE ops_alert_outbox SET delivered_at=? WHERE delivered_at IS NULL"
            " AND (alert_id=? OR (notify_audience='ai' AND EXISTS ("
            " SELECT 1 FROM ops_alert_outbox AS summary WHERE summary.alert_id=?"
            " AND summary.notify_audience='summary'"
            " AND summary.notify_site=ops_alert_outbox.notify_site"
            " AND summary.notify_day=ops_alert_outbox.notify_day)))",
            _stamp(self._now), alert_id, alert_id)
        return True

    async def status(self) -> dict:
        """운영센터가 보는 채널별 상태와 대기 개수(관리자 전용)."""
        waiting = await self._rows(
            "SELECT COUNT(*) AS n FROM ops_alert_outbox WHERE delivered_at IS NULL"
            " AND (notify_audience IS NULL OR notify_audience!='summary')")
        site_rows = await self._rows(
            "SELECT COALESCE(notify_site,'chat') AS site, COUNT(*) AS n"
            " FROM ops_alert_outbox WHERE delivered_at IS NULL"
            " AND (notify_audience IS NULL OR notify_audience!='summary') GROUP BY site")
        pending_by_site = {site: 0 for site in ("chat", *SITE_LINKS)}
        pending_by_site.update({row["site"]: int(row["n"]) for row in site_rows})
        rows = await self._rows(
            "SELECT channel, MAX(delivered_at) AS last_success,"
            " MAX(failed_at) AS last_failure, SUM(attempts) AS attempts"
            " FROM ops_alert_delivery GROUP BY channel")
        by_channel = {row["channel"]: row for row in rows}
        channels = []
        for channel in CHANNELS:
            row = by_channel.get(channel, {})
            channels.append({
                "channel": channel,
                "last_success": row.get("last_success"),
                "last_failure": row.get("last_failure"),
                "attempts": int(row.get("attempts") or 0),
            })
        return {"pending": int(waiting[0]["n"]) if waiting else 0,
                "pending_by_site": pending_by_site, "channels": channels}