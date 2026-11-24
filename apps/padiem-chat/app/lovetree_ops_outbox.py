"""#7690 역방향: 운영센터 답글·상태를 러브트리로 보내는 outbox.

받는 계약은 CTO 댓글 "역방향(운영센터 → 러브트리) 계약 확정"이다.
서명은 정방향과 같은 모양이다: 머리 x-pd-site/x-pd-timestamp(밀리초)/
x-pd-signature, HMAC-SHA256(비밀, 시각 + "\\n" + "lovetree" + "\\n" + 본문 원문
바이트). 비밀·주소 없이는 보내지 않고 줄에 대기한다(조용히 실패하지 않고
행·표시로 남긴다). 4xx는 실패로 남기고 재시도하지 않으며, 5xx·네트워크만
1분·5분·30분·2시간·12시간 뒤 다시 보낸다. 다섯 번 실패하면 '보내기 실패'로
남겨 운영센터에서 다시 보낼 수 있다.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .feedback_store import FeedbackUnavailable
from .lifespan_hooks import lifespan_hooks
from .d1_rows import rows_from_result

_SITE = "lovetree"
RETRY_DELAYS_SECONDS = (60, 300, 1800, 7200, 43200)
_MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS)
_MAX_BODY_BYTES = 8192
# 운영센터 상태 → 러브트리 상태. closed는 운영센터에 없어 보내지 않는다.
CHAT_STATUS_TO_EXTERNAL = {
    "new": "received", "reviewing": "reviewing",
    "fixed": "fixed", "deferred": "later",
}
REPLY_ID_PREFIX = "rpb_"
EVENT_KEY_PREFIX = "ops_"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1000)


def new_event_key() -> str:
    # eventKey: [A-Za-z0-9_-]{16,128}. 한 행 = 한 일이라 재시도에도 같은 키다.
    return EVENT_KEY_PREFIX + uuid.uuid4().hex


def new_reply_id() -> str:
    return REPLY_ID_PREFIX + uuid.uuid4().hex


def build_payload(*, event_key: str, external_feedback_id: Any, kind: str,
                  reply: dict | None = None, status: str | None = None) -> bytes:
    """받는 쪽 계약 본문(JSON 바이트). kind마다 필요한 칸만 넣는다.

    러브트리 ingest는 평평한 본문을 받는다: reply는 replyId·body·createdAt을
    맨 위 칸으로, status는 status 칸 하나만. 빈 칸(null)이나 중첩 객체는
    400으로 거부된다(11-23 운영 실측).
    """
    record: dict[str, Any] = {
        "eventKey": event_key,
        "feedbackId": int(external_feedback_id),
        "kind": kind,
    }
    if kind == "reply" and reply is not None:
        record["replyId"] = reply["replyId"]
        record["body"] = reply["body"]
        record["createdAt"] = reply["createdAt"]
    elif kind == "status" and status is not None:
        record["status"] = status
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def signature_headers(*, secret: str, raw: bytes, timestamp_ms: int) -> dict[str, str]:
    message = str(timestamp_ms).encode("utf-8") + b"\n" + _SITE.encode("utf-8") + b"\n" + raw
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "x-pd-site": _SITE,
        "x-pd-timestamp": str(timestamp_ms),
        "x-pd-signature": "sha256=" + digest,
        "content-type": "application/json",
    }


def outbox_state(row: dict, *, configured: bool) -> str:
    """운영센터에서 보이는 행 상태: 대기·보냄·실패·보내기 실패."""
    if row.get("sent_at"):
        return "sent"
    if row.get("failed_at"):
        return "failed"
    if int(row.get("attempts") or 0) >= _MAX_ATTEMPTS:
        return "exhausted"
    if not configured:
        return "waiting"
    return "pending"


class D1LovetreeOpsOutbox:
    """러브트리 보내기 줄. 적재·재보내기·행 조회를 맡는다."""

    def __init__(self, db):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise FeedbackUnavailable()
        self._db = db

    async def _rows(self, sql, *values):
        try:
            rows = rows_from_result(await self._db.prepare(sql).bind(*values).run())
            return [dict(row.to_py() if callable(getattr(row, "to_py", None)) else row) for row in rows]
        except FeedbackUnavailable:
            raise
        except Exception:
            raise FeedbackUnavailable() from None

    async def _row(self, sql, *values):
        rows = await self._rows(sql, *values)
        return rows[0] if rows else None

    async def enqueue_reply(self, *, feedback_id: str, external_feedback_id: str,
                            body: str, now: str | None = None) -> dict:
        """운영자가 쓴 답글 한 건. 운영 메모와 다른 표·다른 행으로 들어간다."""
        created = now or _now_iso()
        row = await self._row(
            "INSERT INTO lovetree_ops_outbox "
            "(event_key,feedback_id,external_feedback_id,kind,reply_id,reply_body,"
            "reply_created_at,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) RETURNING event_key,feedback_id,"
            "external_feedback_id,kind,reply_id,reply_body,reply_created_at,"
            "status,created_at,attempts,next_attempt_at,sent_at,failed_at,"
            "last_status_code,last_error",
            new_event_key(), feedback_id, external_feedback_id, "reply",
            new_reply_id(), body, created, None, created)
        if row is None:
            raise FeedbackUnavailable()
        return row

    async def enqueue_status(self, *, feedback_id: str, external_feedback_id: str,
                             status: str, now: str | None = None) -> dict:
        """운영자가 운영센터에서 직접 바꾼 상태 한 건. 정방향으로 받은 변화는 들어오지 않는다."""
        created = now or _now_iso()
        row = await self._row(
            "INSERT INTO lovetree_ops_outbox "
            "(event_key,feedback_id,external_feedback_id,kind,status,created_at) "
            "VALUES (?,?,?,?,?,?) RETURNING event_key,feedback_id,"
            "external_feedback_id,kind,reply_id,reply_body,reply_created_at,"
            "status,created_at,attempts,next_attempt_at,sent_at,failed_at,"
            "last_status_code,last_error",
            new_event_key(), feedback_id, external_feedback_id, "status",
            status, created)
        if row is None:
            raise FeedbackUnavailable()
        return row

    async def list_for_feedback(self, feedback_id: str, *, limit: int = 20) -> list[dict]:
        rows = await self._rows(
            "SELECT event_key,feedback_id,external_feedback_id,kind,reply_id,"
            "reply_body,reply_created_at,status,created_at,attempts,"
            "next_attempt_at,sent_at,failed_at,last_status_code,last_error "
            "FROM lovetree_ops_outbox WHERE feedback_id=? "
            "ORDER BY created_at DESC,event_key DESC LIMIT ?",
            feedback_id, limit)
        return rows

    async def pending_rows(self, *, limit: int = 20, now: str | None = None) -> list[dict]:
        current = now or _now_iso()
        return await self._rows(
            "SELECT event_key,feedback_id,external_feedback_id,kind,reply_id,"
            "reply_body,reply_created_at,status,created_at,attempts,"
            "next_attempt_at,sent_at,failed_at,last_status_code,last_error "
            "FROM lovetree_ops_outbox "
            "WHERE sent_at IS NULL AND failed_at IS NULL AND attempts < ? "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY created_at ASC,event_key ASC LIMIT ?",
            _MAX_ATTEMPTS, current, limit)

    async def mark_sent(self, event_key: str, *, now: str | None = None) -> None:
        await self._rows(
            "UPDATE lovetree_ops_outbox SET sent_at=?,attempts=attempts+1,"
            "next_attempt_at=NULL,last_status_code=200,last_error=NULL "
            "WHERE event_key=? AND sent_at IS NULL",
            now or _now_iso(), event_key)

    async def mark_permanent_failure(self, event_key: str, *, status_code: int,
                                     error: str, now: str | None = None) -> None:
        await self._rows(
            "UPDATE lovetree_ops_outbox SET failed_at=?,attempts=attempts+1,"
            "next_attempt_at=NULL,last_status_code=?,last_error=? "
            "WHERE event_key=? AND sent_at IS NULL AND failed_at IS NULL",
            now or _now_iso(), status_code, error[:200], event_key)

    async def mark_retry(self, event_key: str, *, status_code: int | None,
                         error: str, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        attempts = await self._row(
            "SELECT attempts FROM lovetree_ops_outbox WHERE event_key=?", event_key)
        count = (int(attempts["attempts"]) if attempts else 0) + 1
        delay = RETRY_DELAYS_SECONDS[min(count - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        next_at = None if count >= _MAX_ATTEMPTS else (
            current + timedelta(seconds=delay)
        ).isoformat().replace("+00:00", "Z")
        await self._rows(
            "UPDATE lovetree_ops_outbox SET attempts=?,next_attempt_at=?,"
            "last_status_code=?,last_error=? WHERE event_key=? "
            "AND sent_at IS NULL AND failed_at IS NULL",
            count, next_at, status_code, error[:200], event_key)

    async def reset_row(self, event_key: str, *, feedback_id: str, now: str | None = None) -> dict | None:
        """'보내기 실패' 행을 다시 보낼 수 있게 돌린다. 실패가 아닌 행은 그대로 둔다."""
        row = await self._row("SELECT * FROM lovetree_ops_outbox WHERE event_key=? AND feedback_id=?",
                              event_key, feedback_id)
        if row is None:
            return None
        if (not row.get("failed_at")
                and int(row.get("attempts") or 0) < _MAX_ATTEMPTS):
            return None
        return await self._row(
            "UPDATE lovetree_ops_outbox SET attempts=0,next_attempt_at=NULL,"
            "failed_at=NULL,last_status_code=NULL,last_error=NULL "
            "WHERE event_key=? AND feedback_id=? "
            "RETURNING event_key,feedback_id,external_feedback_id,kind,reply_id,"
            "reply_body,reply_created_at,status,created_at,attempts,"
            "next_attempt_at,sent_at,failed_at,last_status_code,last_error",
            event_key, feedback_id)


def reply_config(state: Any) -> tuple[str | None, str | None]:
    """(보낼 주소, 비밀). 둘 중 하나라도 없으면 보내지 않고 줄에 대기한다."""
    settings = getattr(state, "settings", None)
    url = getattr(settings, "site_feedback_reply_url_lovetree", None)
    secret = getattr(settings, "site_feedback_reply_secret_lovetree", None)
    return (url if isinstance(url, str) and url else None,
            secret if isinstance(secret, str) and secret else None)


def _payload_of(row: dict) -> bytes:
    reply = None
    if row.get("kind") == "reply":
        reply = {"replyId": row["reply_id"], "body": row["reply_body"],
                 "createdAt": row["reply_created_at"]}
    return build_payload(
        event_key=row["event_key"], external_feedback_id=row["external_feedback_id"],
        kind=row["kind"], reply=reply, status=row.get("status"))


async def dispatch_pending(state: Any, *, limit: int = 20, client: Any = None,
                       now: datetime | None = None) -> dict:
    """보낼 줄 한 묶음을 보낸다. 설정이 없으면 행을 건드리지 않는다."""
    store = getattr(state, "lovetree_ops_outbox", None)
    url, secret = reply_config(state)
    if store is None or url is None or secret is None:
        return {"sent": 0, "retried": 0, "failed": 0, "checked": 0}
    current = now or datetime.now(timezone.utc)
    current_iso = current.isoformat().replace("+00:00", "Z")
    rows = await store.pending_rows(limit=limit, now=current_iso)
    result = {"sent": 0, "retried": 0, "failed": 0, "checked": len(rows)}
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)
    try:
        for row in rows:
            raw = _payload_of(row)
            if len(raw) > _MAX_BODY_BYTES:
                await store.mark_permanent_failure(
                    row["event_key"], status_code=None, error="payload_too_large", now=current_iso)
                result["failed"] += 1
                continue
            headers = signature_headers(secret=secret, raw=raw, timestamp_ms=_now_ms())
            try:
                response = await client.post(url, content=raw, headers=headers)
            except Exception as error:
                await store.mark_retry(row["event_key"], status_code=None,
                                       error=type(error).__name__, now=current)
                result["retried"] += 1
                continue
            code = int(response.status_code)
            if 200 <= code < 300:
                await store.mark_sent(row["event_key"], now=current_iso)
                result["sent"] += 1
            elif 400 <= code < 500:
                await store.mark_permanent_failure(
                    row["event_key"], status_code=code, error=f"http_{code}", now=current_iso)
                result["failed"] += 1
            else:
                await store.mark_retry(row["event_key"], status_code=code,
                                       error=f"http_{code}", now=current)
                result["retried"] += 1
    finally:
        if own_client:
            await client.aclose()
    return result


async def dispatch_under_lock(state: Any, **kwargs) -> dict | None:
    """같은 DB를 쓰는 CPython 워커 중 한 곳만 줄을 보낸다.

    잠금을 못 잡으면 이번 회차를 건너뛴다. 1분 뒤 다음 주기나 다른 요청의
    백그라운드 발송이 같은 줄을 다시 본다. 보내는 내용·간격·출력은 그대로다.
    """
    lock = getattr(state, "lovetree_ops_process_lock", None)
    if lock is None:
        return await dispatch_pending(state, **kwargs)
    if not lock.acquire(wait=False):
        return None
    try:
        return await dispatch_pending(state, **kwargs)
    finally:
        lock.release()


def _spawn(state: Any) -> None:
    """적재·재보내기 뒤 백그라운드로 보낸다. 루프가 없어도 다음 주기에 나간다."""
    try:
        task = asyncio.create_task(dispatch_under_lock(state))
    except RuntimeError:
        return
    tasks = getattr(state, "lovetree_ops_tasks", None)
    if tasks is None:
        tasks = set()
        state.lovetree_ops_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def schedule_dispatch(state: Any) -> None:
    """적재·재보내기 뒤 호출하는 공개 입구. 백그라운드로 보내고 줄만 남긴다."""
    _spawn(state)


async def retry_loop(state: Any, *, sleep=asyncio.sleep) -> None:
    """1분마다 줄을 본다 — 가장 짧은 재시도(1분)에 맞춘다."""
    while True:
        await dispatch_under_lock(state)
        await sleep(60)


def install_retry_loop(app: Any, *, process_lock: Any = None) -> None:
    """CPython lifespan이 주기 재시도를 맡는다. Worker에는 붙이지 않는다.

    같은 DB를 여는 워커마다 같은 잠금 파일을 받아 한 곳만 줄을 보낸다.
    """
    task = None

    async def start():
        nonlocal task
        app.state.lovetree_ops_process_lock = process_lock
        task = asyncio.create_task(retry_loop(app.state))

    async def stop():
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        tasks = tuple(getattr(app.state, "lovetree_ops_tasks", ()) or ())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if process_lock is not None and getattr(process_lock, "held", False):
            process_lock.release()

    hooks = lifespan_hooks(app)
    hooks.on_startup.append(start)
    hooks.on_shutdown.insert(0, stop)


async def drain_tasks(state: Any) -> None:
    """시험·종료 경로가 백그라운드 발송을 기다릴 때 쓴다."""
    tasks = tuple(getattr(state, "lovetree_ops_tasks", ()) or ())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
