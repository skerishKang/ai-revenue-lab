#!/usr/bin/env python3
"""pc_read end-to-end latency probe with journal-pinned stage breakdown (#6919).

Runs on COM2 (the production host) next to the journals it reads. One run
sends a single ``pc_read`` through the public Chat ``/api/mcp`` connector
contract, then matches the request to the Chat / P01 / queue / executor
journal markers and records one JSONL row with the stage breakdown:

    identity       Chat request event timings_ms.identity (identity RPCs)
    admission      engine_timing admission_ms (P01 admission)
    queue_wait     dispatch write -> executor phase=claimed
    pickup         claimed -> the PC work phase start (guard/read round trip)
    guard          reparse guard (two-step path: guard_done elapsed)
    pc_read        the PC read round trip (read_ok elapsed)
    read_to_submit read_ok -> submit
    submit         result submission (submit phase elapsed)
    chat_assemble  submit -> the /api/mcp response (Chat assembly)

Values are bounded timings and correlation ids only: no file content, no
token, no account value ever reaches the output or the store.

Usage (COM2, WSL):
  pc_read_measure.py run --device cgi1   [--label manual]
  pc_read_measure.py run --device comp1  [--label manual]
  pc_read_measure.py summarize [--since-hours N]

Token files are read from the config directory (never printed):
  <config-dir>/<device>.token
Config (--config-dir, default /opt/padiem/com2-secrets/pc-read-metrics):
  <config-dir>/paths.json   {"cgi1": "C:/Windows/win.ini", "comp1": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://chat.padiem.net"
PROTO = "2026-07-28"
META = "io.modelcontextprotocol/"
DEFAULT_CONFIG_DIR = "/opt/padiem/com2-secrets/pc-read-metrics"
DEFAULT_STORE = "/var/lib/padiem-pc-read-metrics/metrics.jsonl"
RETENTION_DAYS = 7
UNITS = (
    "padiem-chat-com2.service",
    "padiem-p01.service",
    "padiem-oracle-mesh-executor.service",
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    moment = moment or now_utc()
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# --------------------------------------------------------------------- send
def send_probe(token: str, path: str) -> dict:
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "pc_read", "arguments": {"path": path},
            "_meta": {META + "protocolVersion": PROTO, META + "clientCapabilities": {}},
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        BASE + "/api/mcp", data=body, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "padiem-pc-read-latency-probe/1.0",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTO,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "pc_read",
        },
    )
    started = time.perf_counter()
    started_at = now_utc()
    status = 0
    request_id = ""
    structured: dict = {}
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = response.status
            request_id = response.headers.get("X-Request-Id", "")
            payload = json.loads(response.read(4_000_000))
    except urllib.error.HTTPError as exc:
        status = exc.code
        request_id = exc.headers.get("X-Request-Id", "") if exc.headers else ""
        error = "http_error"
        try:
            payload = json.loads(exc.read(200_000))
        except Exception:
            payload = {}
    except Exception as exc:
        error = type(exc).__name__
        payload = {}
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
            structured = result["structuredContent"]
    return {
        "started_at": iso(started_at),
        "started_epoch": started_at.timestamp(),
        "ended_epoch": time.time(),
        "http_status": status,
        "request_id": request_id,
        "error": error or None,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
        "call_status": structured.get("status"),
        "call_code": structured.get("code") or (structured.get("output") or {}).get("stage"),
        "content_head20": _content_head(structured),
    }


#: Result keys that carry prose/diagnostics, never file content.
_CONTENT_SKIP_KEYS = frozenset({"hint", "stage", "ok", "answer", "content_note"})


def _content_head(structured: dict) -> str | None:
    """The first 20 characters of the received file content, or None.

    Proof-of-delivery only (the owner's pass criterion): exactly the first
    20 characters are kept, never more, and only from the payload keys that
    carry the file body.
    """
    candidates = [structured.get("output"), structured.get("content")]
    output = structured.get("output")
    if isinstance(output, dict):
        candidates.extend(output.get(key) for key in ("output", "content", "text", "data"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate and not candidate.startswith("{"):
            return candidate[:20]
    return None


# ----------------------------------------------------------------- journals
def read_journal(since_epoch: float) -> list[dict]:
    since = datetime.fromtimestamp(since_epoch - 2.0, timezone.utc)
    lines: list[dict] = []
    for unit in UNITS:
        try:
            out = subprocess.run(
                ["journalctl", "-u", unit, "--no-pager", "-o", "json",
                 "--since", since.isoformat(timespec="seconds")],
                capture_output=True, text=True, timeout=30,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        for raw in out.splitlines():
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            message = row.get("MESSAGE") or ""
            if not isinstance(message, str) or not message:
                continue
            stamp = int(row.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000.0
            lines.append({"t": stamp, "unit": unit, "m": message})
    lines.sort(key=lambda item: item["t"])
    return lines


_EVENT_RE = re.compile(r'"event":"http_request"')
_QUEUE_CALL_RE = re.compile(
    r"pc_queue_call method=(?P<method>\S+) stage=(?P<stage>\S+) status=(?P<status>\S+) "
    r"outcome=(?P<outcome>\S+) reason=(?P<reason>\S+) elapsed_ms=(?P<elapsed_ms>\S+) "
    r"exception=(?P<exception>\S+) transport_phase=(?P<transport_phase>\S+) "
    r"run_hash=(?P<run_hash>\S+) dispatch_id=(?P<dispatch_id>\S+)")
_ENGINE_TIMING_RE = re.compile(
    r"engine_timing run_hash=(\S+) trace_id=(\S+) admission_ms=(\S+) core_ms=(\S+) "
    r"b14_ms=(\S+) receipt_ms=(\S+) total_ms=(\S+) outcome=(\S+)")
_PHASE_RE = re.compile(r"oracle-mesh-(?:read|command) phase=(\S+) ts=(\S+) elapsed_ms=(\d+)")
_RESULT_RE = re.compile(r"pc_result stage=(\S+) run_hash=(\S+) dispatch_id=(\S+)")
_FILES_CALL_RE = re.compile(r"pc_files_chat_call mode=(\S+) (.*)")


def _fields(text: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=([^\s]+)", text))


def correlate(lines: list[dict], probe: dict) -> dict:
    """One probe's stage facts from its journal window."""
    request_id = probe.get("request_id") or ""
    start = probe["started_epoch"]
    end = probe["ended_epoch"] + 2.0
    window = [row for row in lines if start - 2.0 <= row["t"] <= end]

    chat_event = None
    slow_identity = []
    engine = None
    queue_calls = []
    phases = []
    results = []
    files_calls = []
    for row in window:
        message = row["m"]
        if request_id and request_id in message:
            if _EVENT_RE.search(message):
                try:
                    event = json.loads(message)
                except ValueError:
                    event = None
                if isinstance(event, dict):
                    chat_event = event
            elif "identity_rpc_slow" in message:
                slow_identity.append(_fields(message))
        match = _ENGINE_TIMING_RE.search(message)
        if match:
            engine = {
                "run_hash": match.group(1), "trace_id": match.group(2),
                "admission_ms": float(match.group(3)), "core_ms": float(match.group(4)),
                "receipt_ms": float(match.group(6)), "total_ms": float(match.group(7)),
                "t": row["t"],
            }
        match = _QUEUE_CALL_RE.search(message)
        if match:
            queue_calls.append({
                "method": match.group(1), "stage": match.group(2),
                "elapsed_ms": float(match.group(6)) if match.group(6).replace(".", "", 1).isdigit() else None,
                "run_hash": match.group(9), "dispatch_id": match.group(10),
                "t": row["t"],
            })
        match = _PHASE_RE.search(message)
        if match:
            fields = _fields(message)
            phases.append({
                "phase": match.group(1), "ts": match.group(2),
                "elapsed_ms": float(match.group(3)),
                "dispatch_id": fields.get("dispatch_id", ""), "t": row["t"],
            })
        match = _RESULT_RE.search(message)
        if match:
            results.append({"stage": match.group(1), "run_hash": match.group(2),
                            "dispatch_id": match.group(3), "t": row["t"]})
        match = _FILES_CALL_RE.search(message)
        if match:
            files_calls.append({"mode": match.group(1), "rest": match.group(2), "t": row["t"]})

    out: dict = {
        "chat_duration_ms": None, "identity_ms": None, "auth_ms": None,
        "edge_ms": None, "queue_ms": None, "sqlite_ms": None,
        "admission_ms": None, "engine_core_ms": None, "engine_total_ms": None,
        "queue_wait_ms": None, "pickup_ms": None, "guard_ms": None,
        "pc_read_ms": None, "read_to_submit_ms": None, "submit_ms": None,
        "result_ingest_ms": None, "poll_discovery_ms": None,
        "chat_assemble_ms": None, "end_to_end_ms": None,
        "run_hash": None, "dispatch_id": None,
        "slow_identity": [f"{item.get('method')}={item.get('ms')}" for item in slow_identity],
        "files_calls": [f"{item['mode']}:{_stage_of(item['rest'])}" for item in files_calls][-6:],
    }
    if isinstance(chat_event, dict):
        timings = chat_event.get("timings_ms") or {}
        out["chat_duration_ms"] = chat_event.get("duration_ms")
        out["identity_ms"] = timings.get("identity")
        out["auth_ms"] = timings.get("auth")
        out["edge_ms"] = timings.get("edge")
        out["queue_ms"] = timings.get("queue")
        sqlite = (timings.get("sqlite_wait") or 0.0) + (timings.get("sqlite_execute") or 0.0)
        out["sqlite_ms"] = round(sqlite, 1)
        ended = _epoch(chat_event.get("ts"))
        if ended:
            out["end_to_end_ms"] = round((ended - probe["started_epoch"]) * 1000.0, 1)
    if engine:
        out["admission_ms"] = engine["admission_ms"]
        out["engine_core_ms"] = engine["core_ms"]
        out["engine_total_ms"] = engine["total_ms"]
        out["run_hash"] = engine["run_hash"]

    dispatch_create = next(
        (call for call in queue_calls if call["dispatch_id"] not in ("", "none")),
        None)
    if dispatch_create:
        out["dispatch_id"] = dispatch_create["dispatch_id"]
        if not out["run_hash"] and dispatch_create["run_hash"] not in ("", "none"):
            out["run_hash"] = dispatch_create["run_hash"]
    dispatch_id = out["dispatch_id"]
    relevant = [phase for phase in phases
                if not dispatch_id or phase["dispatch_id"] in ("", dispatch_id)]
    claimed = next((phase for phase in relevant if phase["phase"] == "claimed"), None)
    guard_done = next((phase for phase in relevant if phase["phase"] == "guard_done"), None)
    read_ok = next((phase for phase in relevant if phase["phase"] == "read_ok"), None)
    submit = next((phase for phase in relevant if phase["phase"] == "submit"), None)

    if dispatch_create and claimed:
        out["queue_wait_ms"] = round((claimed["t"] - dispatch_create["t"]) * 1000.0, 1)
    if read_ok:
        out["pc_read_ms"] = read_ok["elapsed_ms"]
        read_start = _epoch(read_ok["ts"])
        if read_start is not None and claimed:
            out["pickup_ms"] = round((read_start - claimed["t"]) * 1000.0, 1)
        if guard_done:
            out["guard_ms"] = guard_done["elapsed_ms"]
            guard_start = _epoch(guard_done["ts"])
            if guard_start is not None and claimed:
                out["pickup_ms"] = round((guard_start - claimed["t"]) * 1000.0, 1)
        if submit:
            submit_t = _epoch(submit["ts"]) or submit["t"]
            out["read_to_submit_ms"] = round((submit_t - read_ok["t"]) * 1000.0, 1)
    if submit:
        out["submit_ms"] = submit["elapsed_ms"]
        submit_t = _epoch(submit["ts"]) or submit["t"]
        if chat_event is not None:
            ended = _epoch(chat_event.get("ts"))
            if ended:
                out["chat_assemble_ms"] = round((ended - submit_t) * 1000.0, 1)
    # Two assembly sub-spans (the 2026-11-09 follow-up): the result receipt
    # leg (submit -> Chat's pc_result stage=received) versus the discovery
    # leg (that receipt -> the /api/mcp response end, the status-poll
    # overshoot). Both stay None until the pc_result lines reach the journal
    # (#7239's sibling hook), and chat_assemble_ms above keeps its meaning.
    result_received = next((row for row in results if row["stage"] == "received"), None)
    if result_received:
        # The receipt leg starts at the executor's submit_ok acknowledgement
        # (the HTTP 200 on the loopback submit), falling back to the submit
        # marker when an older executor printed no acknowledgement.
        submit_ok = next((phase for phase in relevant if phase["phase"] == "submit_ok"), None)
        receipt_start = (submit_ok or submit or {})
        start_t = _epoch(receipt_start.get("ts")) or receipt_start.get("t")
        if start_t:
            out["result_ingest_ms"] = round((result_received["t"] - start_t) * 1000.0, 1)
            if chat_event is not None:
                ended = _epoch(chat_event.get("ts"))
                if ended:
                    out["poll_discovery_ms"] = round((ended - result_received["t"]) * 1000.0, 1)
    return out


def _stage_of(rest: str) -> str:
    match = re.search(r"stage=(\S+)", rest)
    return match.group(1) if match else "?"


# ------------------------------------------------------------------- store
def append_row(store: str, row: dict) -> None:
    os.makedirs(os.path.dirname(store), exist_ok=True)
    with open(store, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    prune(store)


def prune(store: str) -> None:
    """Keep the last RETENTION_DAYS days of rows (7-day retention contract)."""
    if not os.path.exists(store):
        return
    cutoff = (now_utc() - timedelta(days=RETENTION_DAYS)).timestamp()
    kept: list[str] = []
    with open(store, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if float(row.get("ts_epoch") or 0.0) >= cutoff:
                kept.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    with open(store, "w", encoding="utf-8") as handle:
        handle.write("".join(line + "\n" for line in kept))


STAGES = (
    ("identity", "identity_ms"), ("admission", "admission_ms"),
    ("queue_wait", "queue_wait_ms"), ("pickup", "pickup_ms"),
    ("guard", "guard_ms"), ("pc_read", "pc_read_ms"),
    ("read_to_submit", "read_to_submit_ms"), ("submit", "submit_ms"),
    ("result_ingest", "result_ingest_ms"), ("poll_discovery", "poll_discovery_ms"),
    ("chat_assemble", "chat_assemble_ms"), ("end_to_end", "end_to_end_ms"),
)


def warn_if_needed(row: dict) -> bool:
    end_to_end = row.get("stages", {}).get("end_to_end_ms")
    failed = row.get("http_status") != 200 or row.get("call_status") != "completed"
    slow = isinstance(end_to_end, (int, float)) and end_to_end > 30_000
    return failed or slow


def cmd_run(args) -> int:
    config_dir = args.config_dir
    with open(os.path.join(config_dir, args.device + ".token"), "r", encoding="utf-8") as handle:
        token = handle.read().strip()
    paths = {}
    paths_file = os.path.join(config_dir, "paths.json")
    if os.path.exists(paths_file):
        with open(paths_file, "r", encoding="utf-8") as handle:
            paths = json.load(handle)
    path = args.path or paths.get(args.device)
    if not path:
        print("no probe path configured for " + args.device, file=sys.stderr)
        return 2

    probe = send_probe(token, path)
    time.sleep(1.5)  # let the result/telemetry lines land before reading
    lines = read_journal(probe["started_epoch"])
    stages = correlate(lines, probe)
    row = {
        "ts": iso(), "ts_epoch": time.time(), "device": args.device,
        "label": args.label, "http_status": probe["http_status"],
        "call_status": probe["call_status"], "call_code": probe["call_code"],
        "error": probe["error"], "request_id": probe["request_id"],
        "elapsed_ms": probe["elapsed_ms"],
        "content_head20": probe.get("content_head20"), "stages": stages,
    }
    append_row(args.store, row)
    print(json.dumps(row, ensure_ascii=False))
    if warn_if_needed(row):
        print("PC_READ_METRICS WARN device=%s reason=%s end_to_end_ms=%s"
              % (args.device, "failed" if probe["http_status"] != 200 or probe["call_status"] != "completed" else "slow",
                 stages.get("end_to_end_ms")), file=sys.stderr)
        return 1
    return 0


def cmd_summarize(args) -> int:
    if not os.path.exists(args.store):
        print("no rows")
        return 0
    cutoff = time.time() - args.since_hours * 3600.0
    rows = []
    with open(args.store, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if float(row.get("ts_epoch") or 0.0) >= cutoff:
                rows.append(row)
    for row in rows:
        stages = row.get("stages", {})
        cells = " ".join("%s=%s" % (name, stages.get(key)) for name, key in STAGES)
        print("%s device=%s label=%s http=%s call=%s %s"
              % (row.get("ts"), row.get("device"), row.get("label"),
                 row.get("http_status"), row.get("call_status"), cells))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--store", default=DEFAULT_STORE)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--device", required=True, choices=("cgi1", "comp1"))
    run.add_argument("--path", default=None)
    run.add_argument("--label", default="auto")
    run.set_defaults(func=cmd_run)
    summary = sub.add_parser("summarize")
    summary.add_argument("--since-hours", type=float, default=24 * 7)
    summary.set_defaults(func=cmd_summarize)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
