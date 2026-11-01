"""COM2 BookAI records API: signed subject, SQLite persistence, protocol v1."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Mapping
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.routing import Route

from .com2_hmac import signature_matches, signature_time_error

RECORDS_PATH = "/api/bookai/records"
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_SAFE_INTEGER = 9007199254740991
_SUBJECT = re.compile(r"sub_[A-Za-z0-9_-]+")
_KINDS = frozenset({"progress", "note", "highlight", "ai_chat"})
_FIELDS = frozenset({"record_id", "book_id", "locator", "kind", "payload", "updated_at", "deleted"})
_COLUMNS = "record_id, book_id, locator, kind, payload, updated_at, deleted"


def _reply(body, status=200):
    return JSONResponse(body, status_code=status, headers={"cache-control": "private, no-store"})


def _error(code, status):
    return _reply({"error": code}, status)


def _integer(value, *, minimum=0):
    return type(value) is int and minimum <= value <= MAX_SAFE_INTEGER


def _reject_constant(value):
    raise ValueError("invalid_json")


def _records(body):
    data = json.loads(body.decode("utf-8"), parse_constant=_reject_constant)
    if not isinstance(data, dict) or set(data) != {"records"} or not isinstance(data["records"], list):
        raise ValueError("invalid_records")
    seen = set()
    for row in data["records"]:
        if not isinstance(row, dict) or set(row) != _FIELDS:
            raise ValueError("invalid_record")
        if any(not isinstance(row[key], str) or not row[key] for key in ("record_id", "book_id", "locator")):
            raise ValueError("invalid_record")
        if not isinstance(row["kind"], str) or row["kind"] not in _KINDS:
            raise ValueError("invalid_record")
        if not isinstance(row["payload"], dict) or not _integer(row["updated_at"]) or type(row["deleted"]) is not bool:
            raise ValueError("invalid_record")
        if row["record_id"] in seen:
            raise ValueError("duplicate_record_id")
        seen.add(row["record_id"])
        # Reject non-UTF-8 lone surrogates before an atomic DB batch starts.
        json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return data["records"]


def _query(raw):
    query = parse_qs(raw, keep_blank_values=True)
    if set(query) - {"since", "limit"} or any(len(values) != 1 for values in query.values()):
        raise ValueError("invalid_query")
    result = []
    for key, default, minimum in (("since", 0, 0), ("limit", 500, 1)):
        value = query.get(key, [str(default)])[0] or str(default)
        if not re.fullmatch(r"[0-9]{1,16}", value) or not _integer(int(value), minimum=minimum):
            raise ValueError("invalid_query")
        result.append(int(value))
    return tuple(result)


class BookAIRecordsStore:
    """Reuse Chat's D1 facade over its existing COM2 SQLite connection."""

    def __init__(self, db_binding):
        self._db = db_binding

    async def list(self, subject, *, since, limit):
        rows = await self._db.prepare(
            f"SELECT {_COLUMNS} FROM bookai_records "
            "WHERE subject=? AND updated_at>? ORDER BY updated_at, record_id LIMIT ?"
        ).bind(subject, -1 if since == 0 else since, limit + 1).all()
        more = len(rows) > limit
        selected = rows[:limit]
        records = [
            {**row, "payload": json.loads(row["payload"]), "deleted": bool(row["deleted"])}
            for row in selected
        ]
        return {"records": records, "next_since": records[-1]["updated_at"] if records else since, "more": more}

    async def merge(self, subject, records):
        if not records:
            return {"accepted": 0, "kept_newer": []}
        statements = []
        for row in records:
            # The conditional UPSERT is the LWW decision, inside one transaction.
            # Equal timestamps are idempotent: preserve the current row.
            statements.append(self._db.prepare(
                "INSERT INTO bookai_records "
                "(subject, record_id, book_id, locator, kind, payload, updated_at, deleted) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(subject, record_id) DO UPDATE SET "
                "book_id=excluded.book_id, locator=excluded.locator, kind=excluded.kind, "
                "payload=excluded.payload, updated_at=excluded.updated_at, deleted=excluded.deleted "
                "WHERE excluded.updated_at > bookai_records.updated_at"
            ).bind(subject, row["record_id"], row["book_id"], row["locator"], row["kind"],
                   json.dumps(row["payload"], ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                   row["updated_at"], int(row["deleted"])))
            # Read the winner in the SAME transaction, never a pre-read/write race.
            statements.append(self._db.prepare(
                "SELECT updated_at FROM bookai_records WHERE subject=? AND record_id=?"
            ).bind(subject, row["record_id"]))
        results = await self._db.batch(statements)
        kept = [
            row["record_id"] for i, row in enumerate(records)
            if results[i * 2 + 1]["results"][0]["updated_at"] > row["updated_at"]
        ]
        return {"accepted": len(records) - len(kept), "kept_newer": kept}


class BookAIRecordsService:
    def __init__(self, *, env: Mapping[str, Any], db_binding, clock=time.time):
        self._secret = env.get("BOOKAI_COM2_SYNC_SECRET", "")
        self._clock = clock
        self.store = BookAIRecordsStore(db_binding)

    async def handle(self, request):
        if request.method not in {"GET", "POST"}:
            return _error("method_not_allowed", 405)
        if not isinstance(self._secret, str) or not self._secret:
            return _error("sync_unavailable", 503)
        subject = request.headers.get("x-bookai-subject", "")
        timestamp = request.headers.get("x-bookai-timestamp", "")
        signature = request.headers.get("x-bookai-signature", "")
        if not _SUBJECT.fullmatch(subject):
            return _error("invalid_app_signature", 401)
        error = signature_time_error(timestamp, signature, now=self._clock())
        if error:
            return _error(error, 401)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                return _error("request_too_large", 413)
        try:
            query_string = request.scope.get("query_string", b"").decode("ascii")
        except UnicodeDecodeError:
            return _error("invalid_query", 400)
        signed_path = RECORDS_PATH + ("?" + query_string if query_string else "")
        if not signature_matches(secret=self._secret, method=request.method, path=signed_path,
                                 timestamp=timestamp, subject=subject, body=body, signature=signature):
            return _error("invalid_app_signature", 401)
        try:
            if request.method == "GET":
                if body:
                    return _error("invalid_request", 400)
                since, limit = _query(query_string)
                return _reply(await self.store.list(subject, since=since, limit=limit))
            if query_string:
                return _error("invalid_query", 400)
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return _error("unsupported_media_type", 415)
            records = _records(body)
            return _reply(await self.store.merge(subject, records))
        except (ValueError, UnicodeError, RecursionError):
            return _error("invalid_records" if request.method == "POST" else "invalid_query", 400)
        except sqlite3.Error:
            # Preserve the client's durable retry queue without exposing record/SQL values.
            return _error("sync_unavailable", 503)


def install_bookai_records_routes(app, *, env, db_binding, clock=time.time):
    service = BookAIRecordsService(env=env, db_binding=db_binding, clock=clock)
    app.state.bookai_records_service = service
    app.router.routes.insert(0, Route(RECORDS_PATH, service.handle, methods=["GET", "POST"]))
    return service
