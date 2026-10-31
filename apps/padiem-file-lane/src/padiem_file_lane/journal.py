"""One journal line per HTTP request (#6338 observation gap follow-up).

A lane incident used to leave no per-request trace, so an upload or
text-extraction failure could not be confirmed after the fact. Each row now
records: timestamp, method, path without query, status code, the constant
``FileError`` code, wall-clock duration in ms and the size of the file the
request was about. Filenames, file content, ticket or secret values,
exception message text and raw owner identifiers never enter a row — route
handlers place only constant codes and byte counts into the request scope and
this middleware writes those fields alone. A journaling failure is swallowed:
observing a request must never be able to fail it.
"""
from __future__ import annotations

import datetime
import json
import threading
import time
from pathlib import Path

SCOPE_ROW_KEY = "file_lane_journal"

# Routes whose request body is the file itself. When the handler could not
# report a committed size (the request failed mid-flight), the declared
# Content-Length is still the attempted upload size worth journaling.
_RAW_BODY_PATHS = frozenset({"/files", "/files/hwp-text"})


def new_row(scope) -> dict:
    """Seed the per-request row inside the ASGI scope."""
    row = {"method": scope.get("method"), "path": scope.get("path"),
           "error_code": None, "file_size": None}
    scope[SCOPE_ROW_KEY] = row
    return row


def row_from_scope(scope) -> dict:
    """The row seeded for this request, or an empty mapping outside HTTP."""
    return scope.get(SCOPE_ROW_KEY) or {}


def request_content_length(scope) -> int | None:
    for name, value in scope.get("headers") or []:
        if name == b"content-length":
            text = value.decode("ascii", "ignore")
            return int(text) if text.isdigit() else None
    return None


class RequestJournal:
    """Append-only JSONL store with one file per UTC day."""

    def __init__(self, root: Path):
        self.directory = Path(root) / "journal"
        self._lock = threading.Lock()

    def path_for(self, day: str) -> Path:
        return self.directory / f"requests-{day}.jsonl"

    def append(self, row: dict) -> None:
        try:
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            self.directory.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self.path_for(row["ts"][:10]).open("a", encoding="utf-8") as output:
                    output.write(line)
        except Exception:
            # The journal observes the lane; it must never be able to break it.
            pass


class RequestJournalMiddleware:
    """Pure-ASGI wrapper writing one journal row per http request."""

    def __init__(self, app, journal: RequestJournal):
        self.app = app
        self.journal = journal

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        row = new_row(scope)
        started = time.monotonic()
        status = {"value": None}

        async def observe(message):
            if message["type"] == "http.response.start":
                status["value"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except Exception:
            # Exception handlers turn every declared failure into a response;
            # an exception reaching here is an unhandled collapse that
            # ServerErrorMiddleware (outside this middleware) will answer.
            self._append(scope, row, 500, started)
            raise
        self._append(scope, row, status["value"], started)

    def _append(self, scope, row: dict, status: int | None, started: float) -> None:
        if row["file_size"] is None and row["path"] in _RAW_BODY_PATHS:
            # The declared Content-Length of a failed upload is the attempted
            # file size; no other field would survive the failure.
            row["file_size"] = request_content_length(scope)
        self.journal.append({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
            "method": row["method"],
            "path": row["path"],
            "status": status,
            "error_code": row["error_code"],
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "file_size": row["file_size"],
        })
