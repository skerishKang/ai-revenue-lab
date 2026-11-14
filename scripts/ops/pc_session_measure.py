#!/usr/bin/env python3
"""Interactive PC session operational measurement (#7065 slice 10, stage 1).

Measures the detached interactive PC session path through the public Chat
``/api/mcp`` connector contract and judges each acceptance item PASS/FAIL:

    concurrent   repeated rounds of PC-count × 4 concurrent sessions
                 totalling 30 opened sessions, zero failures in every
                 round, and one extra session beyond a full per-PC limit
                 refused with pc_session_limit
    secret_scan  zero secret-value hits in outputs, records and logs
                 (token / cookie / account-value pattern inspection)
    keep         one session held for 3 hours (separate --keep-check only,
                 excluded from the default run)
    cleanup      PC-side processes gone within 5 s of closing a session
    roundtrip    100+ input->output round trips: median <= 8 s,
                 max <= 20 s, success rate >= 99%

Output discipline: the single summary line carries only durations, counts
and closed codes (``PC_SESSION_MEASURE verdict=...``). Session outputs,
tokens and account values are never printed; secret hits are reported as
counts per pattern class only.

Switch discipline: unless both ``PADIEM_MCP_PC_SESSION_ENABLED`` and
``PADIEM_CHAT_PC_SESSION_ENABLED`` are truthy in this process environment,
the tool does nothing and ends with ``verdict=SWITCH_OFF`` without any
network call. A server-side ``pc_session_disabled`` refusal is judged the
same way. This stage-1 tool never enables a switch and never opens a
session on a production PC by itself: it only measures when an operator
has already enabled the switches and supplies a token.

Cleanup discipline: every opened session is closed on success, on failure
and on interruption (SIGINT/SIGTERM), and the remaining PC-side process
count is reported in the summary line.

Usage (operator host, after the switches are enabled):
  pc_session_measure.py measure --device comp1 [--token-file PATH]
  pc_session_measure.py measure --devices comp1,comp2 --keep-check

Token files are read from the config directory (never printed):
  <config-dir>/<device>.token
Config (--config-dir, default /opt/padiem/com2-secrets/pc-read-metrics):
  same convention as the sibling pc_read latency probe.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import statistics
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://chat.padiem.net"
PROTO = "2026-07-28"
META = "io.modelcontextprotocol/"
DEFAULT_CONFIG_DIR = "/opt/padiem/com2-secrets/pc-read-metrics"
SWITCH_ENV_VARS = ("PADIEM_MCP_PC_SESSION_ENABLED", "PADIEM_CHAT_PC_SESSION_ENABLED")
_SWITCH_OFF_CODES = frozenset({"pc_session_disabled"})

# Acceptance criteria (seconds / counts).
CONCURRENT_TARGET = 30   # total sessions opened across repeated rounds
SESSIONS_PER_PC = 4      # per-PC interactive session limit (MAX_SESSIONS)
SESSION_LIMIT_CODE = "pc_session_limit"  # expected refusal beyond that limit
ROUNDTRIP_TARGET = 120
ROUNDTRIP_MEDIAN_MAX_S = 8.0
ROUNDTRIP_MAX_MAX_S = 20.0
ROUNDTRIP_SUCCESS_MIN = 0.99
CLEANUP_MAX_S = 5.0
CLEANUP_POLL_S = 0.2
KEEP_DEFAULT_S = 3 * 3600
KEEP_POLL_S = 60.0

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_SWITCH_OFF = 2
EXIT_INTERRUPTED = 130

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SWITCH_OFF = "SWITCH_OFF"
VERDICT_INTERRUPTED = "INTERRUPTED"


class SessionError(Exception):
    """A closed session refusal code. Server prose is never carried."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------------ switches
def _switch_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def switches_enabled(environ) -> bool:
    return all(_switch_truthy(environ.get(name)) for name in SWITCH_ENV_VARS)


# ------------------------------------------------------------------ secret scan
# Pattern classes only; matched text is never retained or printed.
_SECRET_PATTERNS = (
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/=]{8,}")),
    ("auth_header", re.compile(r"(?i)\bauthorization\s*[:=]\s*\S+")),
    ("cookie", re.compile(r"(?i)\b(?:set-)?cookie\s*[:=]")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")),
    ("api_key", re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_-]{8,}"
        r"|ix_[A-Za-z0-9_-]{8,}|xox[bpas]-[A-Za-z0-9-]{10,})\b")),
    ("account_email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("hex_token", re.compile(r"\b[A-Fa-f0-9]{64,}\b")),
)


def scan_secrets(texts) -> dict:
    """Count secret-pattern hits per class across ``texts`` (no text kept)."""
    counts = {name: 0 for name, _ in _SECRET_PATTERNS}
    for text in texts:
        if not isinstance(text, str) or not text:
            continue
        for name, pattern in _SECRET_PATTERNS:
            counts[name] += len(pattern.findall(text))
    return counts


# ------------------------------------------------------------------ real client
class McpSessionClient:
    """One token-bound PC over the Chat /api/mcp connector contract."""

    def __init__(self, token: str, *, base_url: str = BASE, timeout: float = 150.0) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _call(self, name: str, arguments: dict) -> dict:
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": name, "arguments": arguments,
                "_meta": {META + "protocolVersion": PROTO, META + "clientCapabilities": {}},
            },
        }).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + "/api/mcp", data=body, method="POST",
            headers={
                "Authorization": "Bearer " + self._token,
                "Content-Type": "application/json",
                "User-Agent": "padiem-pc-session-measure/1.0",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": PROTO,
                "Mcp-Method": "tools/call",
                "Mcp-Name": name,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read(4_000_000))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read(200_000))
            except Exception:
                payload = {}
        except Exception as exc:
            raise SessionError("pc_session_unavailable") from exc
        structured: dict = {}
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
                structured = result["structuredContent"]
        code = structured.get("code")
        if structured.get("status") == "failed" or (isinstance(code, str) and code):
            raise SessionError(code if isinstance(code, str) else "pc_session_unavailable")
        if structured.get("status") not in {"completed", "running", "queued"} and not structured:
            raise SessionError("pc_session_unavailable")
        return structured

    def start(self, command: str = "") -> str:
        structured = self._call("pc_shell_start", {
            "command": command, "interactive": True, "mode": "user", "terminal": True,
        })
        job_id = structured.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise SessionError("pc_session_unavailable")
        return job_id

    def roundtrip(self, job_id: str, text: str) -> str:
        structured = self._call("pc_shell_input", {"job_id": job_id, "text": text})
        output = structured.get("output")
        return output if isinstance(output, str) else ""

    def stop(self, job_id: str) -> None:
        self._call("pc_shell_stop", {"job_id": job_id})

    def is_alive(self, job_id: str) -> bool:
        structured = self._call("pc_shell_read", {"job_id": job_id, "status_only": True})
        rows = structured.get("sessions")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows[0].get("alive") is True
        return structured.get("alive") is True


# ------------------------------------------------------------------ measurement
class _Opened:
    """Every session the runner opened, for guaranteed cleanup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list = []  # (client, handle)

    def add(self, client, handle) -> None:
        with self._lock:
            self._items.append((client, handle))

    def snapshot(self):
        with self._lock:
            return list(self._items)

    def close_all(self) -> None:
        for client, handle in self.snapshot():
            try:
                client.stop(handle)
            except Exception:
                pass

    def remaining(self) -> int:
        count = 0
        for client, handle in self.snapshot():
            try:
                if client.is_alive(handle):
                    count += 1
            except Exception:
                count += 1  # unprovable death still counts as remaining
        return count


def _median(values: list) -> float:
    return statistics.median(values) if values else 0.0


def _check_session_limit(client, opened, *, should_stop) -> str:
    """Hold a full per-PC limit on one PC, then attempt one more session.

    The attempt must be the (per-PC limit + 1)-th live session on that PC
    and must be refused with ``pc_session_limit``. Returns REJECTED when it
    is refused with that code, OPENED when it starts, ERROR for any other
    refusal or failure. Every session opened here is closed before
    returning.
    """
    holds = []
    extra = None
    limit = "ERROR"
    try:
        for _ in range(SESSIONS_PER_PC):
            if should_stop():
                break
            handle = client.start("")
            opened.add(client, handle)
            holds.append(handle)
        if not should_stop() and len(holds) == SESSIONS_PER_PC:
            try:
                extra = client.start("")
            except SessionError as exc:
                if exc.code in _SWITCH_OFF_CODES:
                    raise
                limit = "REJECTED" if exc.code == SESSION_LIMIT_CODE else "ERROR"
            except Exception:
                limit = "ERROR"
            else:
                limit = "OPENED"
                opened.add(client, extra)
    except SessionError as exc:
        if exc.code in _SWITCH_OFF_CODES:
            raise
        limit = "ERROR"  # could not hold the per-PC limit to attempt one more
    except Exception:
        limit = "ERROR"
    finally:
        if extra is not None:
            try:
                client.stop(extra)
            except Exception:
                pass
        for handle in holds:
            try:
                client.stop(handle)
            except Exception:
                pass
    return limit


def _measure_concurrent(clients, opened, *, monotonic, sleep, should_stop) -> dict:
    """Open CONCURRENT_TARGET sessions through repeated concurrent rounds.

    Each round opens ``len(devices) * SESSIONS_PER_PC`` sessions at once --
    never more than the per-PC interactive limit -- echoes once per session
    and closes it before the next round, so a PC never holds over its own
    limit while the rounds accumulate to CONCURRENT_TARGET in total. The
    item passes only when every round had zero failures and the extra
    beyond-limit session was refused.
    """
    from concurrent.futures import ThreadPoolExecutor

    devices = list(clients)
    per_round = len(devices) * SESSIONS_PER_PC
    if not devices:
        return {
            "started": 0, "failures": 0, "rounds": 0, "per_round": 0,
            "limit": "SKIPPED", "passed": False,
        }

    started = 0
    attempted = 0
    rounds = 0
    failures = 0
    limit = "SKIPPED"
    lock = threading.Lock()

    def open_one(client, index: int) -> None:
        nonlocal failures, started
        handle = None
        try:
            handle = client.start("")
            with lock:
                started += 1
            opened.add(client, handle)
            if not should_stop():
                client.roundtrip(handle, "echo %d" % index)
        except SessionError as exc:
            if exc.code in _SWITCH_OFF_CODES:
                raise
            with lock:
                failures += 1
        except Exception:
            with lock:
                failures += 1
        finally:
            if handle is not None:
                try:
                    client.stop(handle)
                except Exception:
                    pass

    def run_round(count: int, base: int) -> None:
        nonlocal rounds
        rounds += 1
        try:
            with ThreadPoolExecutor(max_workers=max(count, 1)) as pool:
                list(pool.map(
                    lambda offset: open_one(
                        clients[devices[(base + offset) % len(devices)]],
                        base + offset),
                    range(count)))
        except SessionError as exc:
            if exc.code in _SWITCH_OFF_CODES:
                raise
            with lock:
                failures += count  # defensive: the round aborted as a whole

    while attempted < CONCURRENT_TARGET and not should_stop():
        count = min(per_round, CONCURRENT_TARGET - attempted)
        run_round(count, attempted)
        attempted += count

    if attempted == CONCURRENT_TARGET and not should_stop():
        limit = _check_session_limit(
            clients[devices[0]], opened, should_stop=should_stop)

    return {
        "started": started, "failures": failures,
        "rounds": rounds, "per_round": per_round, "limit": limit,
        "passed": (attempted == CONCURRENT_TARGET and failures == 0
                   and limit == "REJECTED"),
    }


def _measure_roundtrips(clients, opened, *, monotonic, sleep, should_stop, texts) -> dict:
    client = clients[next(iter(clients))]
    handle = client.start("")
    opened.add(client, handle)
    latencies: list = []
    successes = 0
    failures = 0
    try:
        for index in range(ROUNDTRIP_TARGET):
            if should_stop():
                break
            begin = monotonic()
            try:
                output = client.roundtrip(handle, "echo %d" % index)
                texts.append(output)
                successes += 1
            except SessionError:
                failures += 1
            except Exception:
                failures += 1
            latencies.append(monotonic() - begin)
    finally:
        try:
            client.stop(handle)
        except Exception:
            pass
    total = successes + failures
    rate = successes / total if total else 0.0
    median = _median(latencies)
    peak = max(latencies) if latencies else 0.0
    passed = (total >= 100 and median <= ROUNDTRIP_MEDIAN_MAX_S
              and peak <= ROUNDTRIP_MAX_MAX_S and rate >= ROUNDTRIP_SUCCESS_MIN)
    return {
        "count": total, "successes": successes, "failures": failures,
        "median_s": median, "max_s": peak, "success_rate": rate, "passed": passed,
    }


def _measure_cleanup(clients, opened, *, monotonic, sleep, should_stop) -> dict:
    client = clients[next(iter(clients))]
    handle = client.start("")
    opened.add(client, handle)
    begin = monotonic()
    try:
        client.stop(handle)
    except Exception:
        pass
    elapsed = 0.0
    alive = True
    while True:
        try:
            alive = client.is_alive(handle)
        except Exception:
            alive = True
        elapsed = monotonic() - begin
        if not alive or elapsed >= CLEANUP_MAX_S:
            break
        sleep(min(CLEANUP_POLL_S, CLEANUP_MAX_S - elapsed))
    return {
        "elapsed_s": elapsed, "remaining": 1 if alive else 0,
        "passed": (not alive) and elapsed <= CLEANUP_MAX_S,
    }


def _measure_keep(clients, opened, *, monotonic, sleep, should_stop, texts,
                  keep_seconds: float) -> dict:
    client = clients[next(iter(clients))]
    handle = client.start("")
    opened.add(client, handle)
    begin = monotonic()
    ok = True
    held = 0.0
    try:
        while True:
            held = monotonic() - begin
            if held >= keep_seconds:
                break
            if should_stop():
                ok = False
                break
            sleep(min(KEEP_POLL_S, keep_seconds - held))
            try:
                texts.append(client.roundtrip(handle, "echo keep"))
                if not client.is_alive(handle):
                    ok = False
                    break
            except Exception:
                ok = False
                break
    finally:
        try:
            client.stop(handle)
        except Exception:
            pass
    held = monotonic() - begin
    return {"held_s": held, "passed": ok and held >= keep_seconds}


def run_measurement(client_factory, *, devices, environ, monotonic=time.monotonic,
                    sleep=time.sleep, should_stop=lambda: False,
                    keep_check: bool = False, keep_seconds: float = KEEP_DEFAULT_S) -> dict:
    """Run every acceptance item. Returns a counts/codes-only result dict."""
    texts: list = []
    result = {
        "verdict": VERDICT_FAIL,
        "concurrent": {"started": 0, "failures": 0, "rounds": 0, "per_round": 0,
                       "limit": "SKIPPED", "passed": False},
        "secret_hits": 0,
        "secret_by_class": {},
        "keep": {"skipped": True, "held_s": 0.0, "passed": False},
        "cleanup": {"elapsed_s": 0.0, "remaining": 0, "passed": False},
        "roundtrips": {"count": 0, "successes": 0, "failures": 0,
                       "median_s": 0.0, "max_s": 0.0, "success_rate": 0.0, "passed": False},
        "remaining": 0,
    }
    if not switches_enabled(environ):
        result["verdict"] = VERDICT_SWITCH_OFF
        return result

    clients = {device: client_factory(device) for device in devices}
    opened = _Opened()
    interrupted = False
    try:
        result["concurrent"] = _measure_concurrent(
            clients, opened, monotonic=monotonic, sleep=sleep, should_stop=should_stop)
        if not should_stop():
            result["roundtrips"] = _measure_roundtrips(
                clients, opened, monotonic=monotonic, sleep=sleep,
                should_stop=should_stop, texts=texts)
        if not should_stop():
            result["cleanup"] = _measure_cleanup(
                clients, opened, monotonic=monotonic, sleep=sleep, should_stop=should_stop)
        if keep_check and not should_stop():
            result["keep"] = _measure_keep(
                clients, opened, monotonic=monotonic, sleep=sleep,
                should_stop=should_stop, texts=texts, keep_seconds=keep_seconds)
            result["keep"]["skipped"] = False
    except SessionError as exc:
        if exc.code in _SWITCH_OFF_CODES:
            opened.close_all()
            result["remaining"] = opened.remaining()
            result["verdict"] = VERDICT_SWITCH_OFF
            return result
        # Any other closed refusal fails the item in progress; cleanup below
        # still runs and the verdict stays FAIL.
    finally:
        if should_stop():
            interrupted = True
        opened.close_all()
    result["remaining"] = opened.remaining()
    by_class = scan_secrets([*texts, summary_line(result)])
    result["secret_by_class"] = {k: v for k, v in by_class.items() if v}
    result["secret_hits"] = sum(by_class.values())
    if interrupted or should_stop():
        result["verdict"] = VERDICT_INTERRUPTED
        return result
    items_passed = result["concurrent"]["passed"] and result["roundtrips"]["passed"] \
        and result["cleanup"]["passed"] and result["secret_hits"] == 0
    if keep_check:
        items_passed = items_passed and result["keep"]["passed"]
    result["verdict"] = VERDICT_PASS if items_passed else VERDICT_FAIL
    return result


def summary_line(result: dict) -> str:
    concurrent = result["concurrent"]
    roundtrips = result["roundtrips"]
    cleanup = result["cleanup"]
    keep = result["keep"]
    keep_field = "SKIPPED" if keep.get("skipped") else ("PASS" if keep["passed"] else "FAIL")
    return (
        "PC_SESSION_MEASURE verdict=%s concurrent_fail=%d/%d rounds=%d "
        "per_round=%d limit=%s secret_hits=%d "
        "keep=%s keep_s=%.0f cleanup_s=%.2f cleanup_remaining=%d "
        "roundtrips=%d rt_median_s=%.2f rt_max_s=%.2f rt_success=%.3f remaining=%d"
        % (result["verdict"], concurrent["failures"], CONCURRENT_TARGET,
           concurrent.get("rounds", 0), concurrent.get("per_round", 0),
           concurrent.get("limit", "SKIPPED"),
           result["secret_hits"], keep_field, keep.get("held_s", 0.0),
           cleanup.get("elapsed_s", 0.0), cleanup.get("remaining", 0),
           roundtrips.get("count", 0), roundtrips.get("median_s", 0.0),
           roundtrips.get("max_s", 0.0), roundtrips.get("success_rate", 0.0),
           result.get("remaining", 0))
    )


# ------------------------------------------------------------------ CLI
def _read_token(config_dir: str, device: str) -> str:
    path = os.path.join(config_dir, device + ".token")
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive PC session operational measurement (#7065 slice 10).")
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure", help="run the measurement")
    measure.add_argument("--device", default="comp1")
    measure.add_argument("--devices", default=None,
                         help="comma-separated devices (overrides --device)")
    measure.add_argument("--config-dir", default=DEFAULT_CONFIG_DIR)
    measure.add_argument("--base-url", default=BASE)
    measure.add_argument("--keep-check", action="store_true",
                         help="also hold one session for 3 hours (default: excluded)")
    measure.add_argument("--record", default=None,
                         help="optional JSON record path (counts and codes only)")
    return parser


def main(argv=None, environ=None, monotonic=time.monotonic, sleep=time.sleep,
         wall_now=None) -> int:
    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    wall_now = wall_now or (lambda: datetime.now(timezone.utc))
    devices = [d.strip() for d in (args.devices or args.device).split(",") if d.strip()]
    started_at = wall_now()

    stop_event = threading.Event()

    def _on_signal(signum, frame):
        stop_event.set()

    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    def factory(device: str) -> McpSessionClient:
        return McpSessionClient(_read_token(args.config_dir, device),
                                base_url=args.base_url)

    try:
        result = run_measurement(
            factory, devices=devices, environ=env, monotonic=monotonic, sleep=sleep,
            should_stop=stop_event.is_set, keep_check=args.keep_check)
    except KeyboardInterrupt:
        result = {"verdict": VERDICT_INTERRUPTED,
                  "concurrent": {"started": 0, "failures": 0, "rounds": 0,
                  "per_round": 0, "limit": "SKIPPED", "passed": False},
                  "secret_hits": 0, "secret_by_class": {}, "keep": {"skipped": True, "held_s": 0.0,
                  "passed": False}, "cleanup": {"elapsed_s": 0.0, "remaining": 0, "passed": False},
                  "roundtrips": {"count": 0, "successes": 0, "failures": 0, "median_s": 0.0,
                  "max_s": 0.0, "success_rate": 0.0, "passed": False}, "remaining": 0}
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
    line = summary_line(result)
    print(line)
    if args.record:
        record = dict(result)
        record["started_at"] = started_at.isoformat()
        record["line"] = line
        with open(args.record, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
    return {
        VERDICT_PASS: EXIT_PASS, VERDICT_FAIL: EXIT_FAIL,
        VERDICT_SWITCH_OFF: EXIT_SWITCH_OFF, VERDICT_INTERRUPTED: EXIT_INTERRUPTED,
    }[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
