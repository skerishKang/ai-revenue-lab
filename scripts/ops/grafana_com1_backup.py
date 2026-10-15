"""COM1 pull-through archive of bounded PADIEM Grafana Loki events.

This is a genuine independent copy: Loki -> HTTPS logs:read -> local SQLite.
No Cloudflare Logs, R2, or Workers Logs backup dependency. Never archive
unrecognised event fields or arbitrary raw log content.
Credentials are Windows user-DPAPI protected and never printed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LOKI = "https://logs-prod-030.grafana.net"
LOKI_USER = "1834293"
QUERY = '{service_name="padiem-chat"}'
MAX_RESPONSE = 4 * 1024 * 1024
MAX_RESULTS = 5000
WINDOW_NS = 15 * 60 * 1_000_000_000
OVERLAP_NS = 3 * 1_000_000_000
ALLOWED = frozenset({
    "event", "service", "ts", "request_id", "request_id_source", "method",
    "route", "status", "duration_ms", "outcome", "stage", "code", "model",
    "provider", "b14_request_id",
})
EVENTS = ("http_request", "ai_stage")


def storage_paths() -> tuple[Path, Path]:
    base = Path(os.environ["LOCALAPPDATA"]) / "PADIEM" / "GrafanaLogs"
    return (base / "archive.sqlite3",
            base.parent / "secrets" / "grafana-loki-read.dpapi")


def load_read_token(secret_file: Path) -> str:
    """Decrypt in the COM1 Windows user context; do not expose in command args."""
    if os.name != "nt" or not secret_file.is_file():
        raise RuntimeError("COM1_LOKI_READ_DPAPI_SECRET_NOT_INSTALLED")
    # Path is determined only by LOCALAPPDATA; never interpolate user input.
    script = (
        "$ErrorActionPreference = 'Stop';"
        "$f=Join-Path $env:LOCALAPPDATA 'PADIEM\\secrets\\grafana-loki-read.dpapi';"
        "$v=Get-Content -LiteralPath $f -Raw | ConvertTo-SecureString;"
        "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($v);"
        "try {[Console]::Out.Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))}"
        "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if proc.returncode != 0 or len(proc.stdout) < 20:
        raise RuntimeError("COM1_LOKI_READ_DPAPI_DECRYPT_FAILED")
    return proc.stdout


def query_loki(token: str, start: int, end: int) -> list[tuple[str, dict]]:
    params = urllib.parse.urlencode({
        "query": QUERY, "start": str(start), "end": str(end),
        "limit": str(MAX_RESULTS), "direction": "forward",
    })
    auth = base64.b64encode((LOKI_USER + ":" + token).encode()).decode()
    req = urllib.request.Request(
        LOKI + "/loki/api/v1/query_range?" + params,
        headers={"Authorization": "Basic " + auth,
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise RuntimeError("LOKI_RESPONSE_TOO_LARGE")
    payload = json.loads(body)
    if payload.get("status") != "success":
        raise RuntimeError("LOKI_QUERY_NOT_SUCCESS")
    rows: list[tuple[str, dict]] = []
    for stream in payload.get("data", {}).get("result", []):
        for item in stream.get("values", []):
            if not isinstance(item, list) or len(item) < 2:
                continue
            timestamp, raw = item[:2]
            try:
                safe = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if (not isinstance(safe, dict) or safe.get("event") not in EVENTS
                    or not set(safe).issubset(ALLOWED)):
                continue
            # Bounded metadata only. Strip if a log format unexpectedly changes.
            if any(isinstance(v, (dict, list)) or
                   (isinstance(v, str) and len(v) > 240)
                   for v in safe.values()):
                continue
            if not (isinstance(timestamp, str) and timestamp.isdigit()):
                continue
            rows.append((timestamp, safe))
    if len(rows) >= MAX_RESULTS:
        raise RuntimeError("LOKI_RESULT_LIMIT_REACHED_INCREASE_POLL_FREQUENCY")
    return rows


def open_archive(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS events(
        fingerprint TEXT PRIMARY KEY,
        timestamp_ns TEXT NOT NULL,
        request_id TEXT,
        service TEXT NOT NULL,
        event TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS events_request_id ON events(request_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(timestamp_ns)")
    connection.execute("""CREATE TABLE IF NOT EXISTS cursor(
        id INTEGER PRIMARY KEY CHECK (id=1), last_ns TEXT NOT NULL
    )""")
    connection.commit()
    return connection


def archive_batch(connection: sqlite3.Connection,
                  rows: list[tuple[str, dict]], end: int) -> int:
    before = connection.total_changes
    with connection:
        for stamp, obj in rows:
            serialized = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"))
            fingerprint = hashlib.sha256((stamp + serialized).encode()).hexdigest()
            connection.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                (fingerprint, stamp, obj.get("request_id"), obj.get("service", "unknown"),
                 obj["event"], serialized),
            )
        connection.execute(
            "INSERT INTO cursor(id,last_ns) VALUES(1,?) ON CONFLICT(id)"
            " DO UPDATE SET last_ns=excluded.last_ns", (str(end),),
        )
    return max(0, connection.total_changes - before - 1)


def run() -> int:
    archive_path, secret_path = storage_paths()
    if not secret_path.is_file():
        print("BACKUP_NOT_ACTIVE: missing user-DPAPI logs:read token")
        return 2
    token = load_read_token(secret_path)
    with open_archive(archive_path) as connection:
        existing = connection.execute("SELECT last_ns FROM cursor WHERE id=1").fetchone()
        now = time.time_ns()
        start = (int(existing[0]) - OVERLAP_NS
                 if existing else now - WINDOW_NS)
        # Catch up in bounded 24h chunks, rather than silently discard a gap
        # after COM1 was switched off for longer than one day.
        total = 0
        windows = 0
        while start < now and windows < 96:
            end = min(start + WINDOW_NS, now)
            rows = query_loki(token, start, end)
            total += archive_batch(connection, rows, end)
            start = end - OVERLAP_NS if end < now else end
            windows += 1
    print(f"BACKUP_OK records_new={total} windows={windows} db={archive_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        # Never print exception text: HTTP library errors can embed credentials.
        print("BACKUP_FAILED:" + type(exc).__name__)
        sys.exit(1)
