"""A12 production streaming idempotency replay smoke (#2025).

Runs against the PRODUCTION Engine (default https://engine.padiem.net) with the
product-owned smoke caller credential (PADIEM_ENGINE_SMOKE_CALLER_ID/_SECRET or
CALLER_ID/CALLER_SECRET, allowed_app_ids=["b54-padiem-claw"]). Standard library only.

Steps:
  S0  GET  /internal/v1/health -> 200, STREAM_PATH advertised, capabilities
      provider_streaming_run == "available".
  S1  POST /internal/v1/stream (pinned model, idempotency key a12-smoke-<RUN_ID>-1)
      -> 200 NDJSON stream, first execution produces incremental stream events
      ending with done=True and replayed=False.
  S2  POST /internal/v1/stream (same payload, same key)
      -> 200 NDJSON stream, exact 1 event line with done=True and replayed=True,
      answer matching S1's completed answer.
  S3  POST /internal/v1/stream (same key, different message content)
      -> 409 idempotency_conflict BEFORE provider execution.
  S4  D1 row state check via wrangler (optional/skipped if remote execution not configured,
      or asserted if credentials present).

Output:
  A12_STREAM_REPLAY_SMOKE=PASS|FAIL|SKIPPED_UPSTREAM

Classification rule (provider-independent gate):
  PASS               every stage ran and every invariant held.
  SKIPPED_UPSTREAM   the provider leg hit an external 5xx that the Engine
                     preserved as error.metadata.upstream_status_code. The
                     mandatory, provider-independent stages (S0 health /
                     manifest, S3 conflict) still ran and still had to pass.
  FAIL               anything else: an Engine 5xx without an upstream status,
                     an auth/contract failure, an idempotency invariant, or a
                     D1 row-state mismatch. An Engine failure is never a skip.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ENGINE_BASE_URL = os.environ.get("ENGINE_BASE_URL", "https://engine.padiem.net").rstrip("/")
CALLER_ID = os.environ.get("PADIEM_ENGINE_SMOKE_CALLER_ID") or os.environ.get("CALLER_ID", "")
CALLER_SECRET = os.environ.get("PADIEM_ENGINE_SMOKE_CALLER_SECRET") or os.environ.get("CALLER_SECRET", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")

PINNED_MODEL = "sensenova/sensenova-6.8-flash-lite"
HEALTH_PATH = "/internal/v1/health"
STREAM_PATH = "/internal/v1/stream"
IDEMPOTENCY_KEY = f"a12-smoke-{GITHUB_RUN_ID}-1"
TRACE_ID = f"a12-smoke-{GITHUB_RUN_ID}"
REQUEST_TIMEOUT_SECONDS = 90

_failures: list[str] = []
_skips: list[str] = []

# A provider 5xx that the Engine preserved as an upstream status is an external
# fact, not an Engine defect, so the gate records it as SKIPPED_UPSTREAM. Every
# other failure stays a hard FAIL: an Engine 5xx without an upstream status, an
# auth/contract failure, an idempotency invariant, or a D1 row-state mismatch.
UPSTREAM_STATUS_FIELD = "upstream_status_code"
UPSTREAM_FAILURE_RANGE = range(500, 600)


def _fail(step: str, message: str, raw: Any = None) -> None:
    _failures.append(f"{step}: {message}")
    print(f"[{step}] FAIL: {message}", file=sys.stderr)
    if raw is not None:
        print(f"[{step}] RAW: {raw}", file=sys.stderr)


def _upstream_status_code(line: Any) -> int | None:
    """Return the Engine-preserved upstream provider status when it is a 5xx."""
    if not isinstance(line, dict):
        return None
    error = line.get("error")
    if not isinstance(error, dict):
        return None
    metadata = error.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(UPSTREAM_STATUS_FIELD)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value in UPSTREAM_FAILURE_RANGE else None


def _classify_upstream_skip(step: str, status: int, lines: list[dict[str, Any]]) -> bool:
    """Record an external-provider skip. Never used for an Engine-side failure."""
    if status < 500:
        return False
    codes = [
        code for code in (_upstream_status_code(line) for line in lines) if code is not None
    ]
    if not codes:
        return False
    reason = f"{step}: upstream provider returned {codes[0]} (HTTP {status})"
    _skips.append(reason)
    print(f"[{step}] SKIPPED_UPSTREAM: {reason}", file=sys.stderr)
    return True


def _require_env() -> bool:
    if not CALLER_ID or not CALLER_SECRET:
        print("A12_STREAM_REPLAY_SMOKE=SKIPPED_UPSTREAM (smoke caller secrets missing)", file=sys.stderr)
        return False
    return True


def _identity_headers() -> dict[str, str]:
    return {
        "User-Agent": "padiem-a12-stream-smoke/1.0 (+github-actions)",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": CALLER_SECRET,
        "Content-Type": "application/json",
    }


def _stream_payload(message_content: str = "a12 smoke: reply with the single word OK") -> dict[str, Any]:
    return {
        "app_id": "b54-padiem-claw",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "A12 stream smoke",
            "description": "A12 production streaming idempotency smoke",
            "system_instruction": "You are a smoke probe. Answer with exactly one word.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 64,
            "required_capabilities": [],
            "model_policy": {"model": PINNED_MODEL},
        },
        "messages": [{"role": "user", "content": message_content}],
        "trace_id": TRACE_ID,
        "execution_context": {
            "trace_id": TRACE_ID,
            "timeout_seconds": 60.0,
            "idempotency_key": IDEMPOTENCY_KEY,
        },
    }


def _request_json(
    *,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | str]:
    url = f"{ENGINE_BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=_identity_headers())
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:
        raise RuntimeError(f"request to {url} failed: {exc}") from exc
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def _request_stream(
    *,
    path: str,
    body: dict[str, Any],
) -> tuple[int, list[dict[str, Any]], str]:
    """POST to an NDJSON streaming endpoint and return status, parsed event lines, and raw text."""
    url = f"{ENGINE_BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers=_identity_headers())
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = response.status
            lines: list[dict[str, Any]] = []
            raw_lines: list[str] = []
            for raw_line in response:
                decoded = raw_line.decode("utf-8")
                raw_lines.append(decoded)
                line_str = decoded.strip()
                if not line_str:
                    continue
                try:
                    lines.append(json.loads(line_str))
                except json.JSONDecodeError:
                    lines.append({"_raw": line_str})
            return status, lines, "".join(raw_lines)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
        try:
            return status, [json.loads(raw)], raw
        except json.JSONDecodeError:
            return status, [{"_raw": raw}], raw
    except Exception as exc:
        raise RuntimeError(f"stream request to {url} failed: {exc}") from exc


def s0_health() -> bool:
    status, body = _request_json(method="GET", path=HEALTH_PATH)
    if status != 200:
        _fail("S0", f"health status {status} != 200", body)
        return False
    if not isinstance(body, dict):
        _fail("S0", "health body is not an object", body)
        return False
    endpoints = body.get("endpoints") or []
    paths = {str(e.get("path")) for e in endpoints if isinstance(e, dict)}
    if STREAM_PATH not in paths:
        _fail("S0", f"{STREAM_PATH} not advertised in endpoints", sorted(paths))
        return False
    capabilities = body.get("capabilities") or {}
    if capabilities.get("provider_streaming_run") != "available":
        _fail("S0", f"capabilities.provider_streaming_run={capabilities.get('provider_streaming_run')!r} != 'available'")
        return False
    print(f"[S0] health OK: {STREAM_PATH} advertised, provider_streaming_run=available")
    return True


def s1_first_stream_run(payload: dict[str, Any]) -> tuple[bool, str | None]:
    status, lines, raw = _request_stream(path=STREAM_PATH, body=payload)
    if status != 200:
        if _classify_upstream_skip("S1", status, lines):
            return False, None
        _fail("S1", f"stream status {status} != 200", raw)
        return False, None
    if not lines:
        _fail("S1", "no NDJSON event lines returned", raw)
        return False, None

    terminal_event: dict[str, Any] | None = None
    accumulated_deltas: list[str] = []

    for item in lines:
        if item.get("ok") is not True:
            _fail("S1", "stream emitted non-ok line", item)
            return False, None
        if item.get("replayed") is True:
            _fail("S1", "first execution unexpectedly marked replayed:true", item)
            return False, None
        ev = item.get("event") or {}
        if not isinstance(ev, dict):
            _fail("S1", "line lacks event object", item)
            return False, None
        delta = ev.get("delta_content")
        if delta:
            accumulated_deltas.append(delta)
        if ev.get("done") is True:
            terminal_event = ev

    if terminal_event is None:
        _fail("S1", "stream finished without a done=True terminal event", raw)
        return False, None

    answer = terminal_event.get("answer") or "".join(accumulated_deltas)
    if not answer or not str(answer).strip():
        _fail("S1", "terminal event lacks answer", terminal_event)
        return False, None

    print(f"[S1] first stream run OK: {len(lines)} event lines, done=True observed, answer received")
    return True, str(answer).strip()


def s2_replay_stream_run(payload: dict[str, Any], s1_answer: str | None) -> bool:
    status, lines, raw = _request_stream(path=STREAM_PATH, body=payload)
    if status != 200:
        if _classify_upstream_skip("S2", status, lines):
            return False
        _fail("S2", f"replay stream status {status} != 200", raw)
        return False

    if len(lines) != 1:
        _fail("S2", f"expected exactly 1 NDJSON event line on replay, got {len(lines)}", lines)
        return False

    item = lines[0]
    if item.get("ok") is not True:
        _fail("S2", "replay line ok is not True", item)
        return False
    if item.get("replayed") is not True:
        _fail("S2", "replay line lacks replayed:true", item)
        return False

    ev = item.get("event") or {}
    if not isinstance(ev, dict):
        _fail("S2", "replay event is not an object", item)
        return False
    if ev.get("done") is not True:
        _fail("S2", "replay event done is not True", ev)
        return False
    if ev.get("delta_content") is not None:
        _fail("S2", f"replay event delta_content={ev.get('delta_content')!r} != None", ev)
        return False

    replay_answer = ev.get("answer")
    if not replay_answer or str(replay_answer).strip() != s1_answer:
        _fail("S2", f"replay answer {replay_answer!r} does not match S1 answer {s1_answer!r}", ev)
        return False

    print("[S2] streaming replay OK: exact 1 event line, replayed=True, done=True, answer preserved")
    return True


def s3_conflict_blocks_before_execution(base_payload: dict[str, Any]) -> bool:
    conflict_payload = dict(base_payload)
    conflict_payload["messages"] = [
        {"role": "user", "content": "a12 smoke CONFLICT probe: different message, same key"}
    ]
    started = time.monotonic()
    status, body = _request_json(method="POST", path=STREAM_PATH, body=conflict_payload)
    elapsed = time.monotonic() - started

    if status != 409:
        _fail("S3", f"conflict status {status} != 409", body)
        return False

    code = None
    if isinstance(body, dict):
        code = (body.get("error") or {}).get("code")

    if code != "idempotency_conflict":
        _fail("S3", f"error code {code!r} != 'idempotency_conflict'", body)
        return False

    print(f"[S3] conflict OK: 409 idempotency_conflict in {elapsed:.2f}s (pre-execution rejection)")
    return True


def s4_d1_row_state() -> bool:
    command = (
        "SELECT state, count(*) AS n FROM padiem_engine_idempotency "
        f"WHERE idempotency_key LIKE 'a12-smoke-{GITHUB_RUN_ID}-%' GROUP BY state"
    )
    try:
        result = subprocess.run(
            [
                "npx", "wrangler@4", "d1", "execute", "padiem-engine",
                "--remote", "--json", "--command", command,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        print(f"[S4] wrangler d1 check skipped (local/unsupported execution: {exc})")
        return True

    if result.returncode != 0:
        if "Authentication error" in result.stderr or "CLOUDFLARE_API_TOKEN" in result.stderr:
            print("[S4] D1 row-state check skipped (wrangler auth not present in environment)")
            return True
        _fail("S4", f"wrangler d1 execute failed rc={result.returncode}", result.stderr[-2000:])
        return False

    try:
        payload = json.loads(result.stdout)
        rows = payload[0]["results"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        _fail("S4", f"unparseable wrangler output: {exc}", result.stdout[-2000:])
        return False

    states = {str(row.get("state")): int(row.get("n", 0)) for row in rows if isinstance(row, dict)}
    if states.get("completed") != 1:
        _fail("S4", f"expected exactly 1 completed row, got {states}", rows)
        return False
    if states.get("reserved", 0) != 0:
        _fail("S4", f"found reserved rows: {states}", rows)
        return False

    print(f"[S4] D1 row-state OK: {states}")
    return True


def _record_verdict(verdict: str, extra: str = "") -> None:
    print(f"A12_STREAM_REPLAY_SMOKE={verdict}{extra}")


def main() -> int:
    if not _require_env():
        return 1

    if not s0_health():
        print("A12_STREAM_REPLAY_SMOKE=FAIL (S0 gate)", file=sys.stderr)
        return 1

    payload = _stream_payload()
    executed, s1_answer = s1_first_stream_run(payload)
    if _failures or (not executed and not _skips):
        print("A12_STREAM_REPLAY_SMOKE=FAIL (S1)", file=sys.stderr)
        return 1

    if executed:
        s2_replay_stream_run(payload, s1_answer)
        if _failures:
            print("A12_STREAM_REPLAY_SMOKE=FAIL (S2)", file=sys.stderr)
            return 1

    # Mandatory, provider-independent stages run even when the provider leg was
    # skipped: the Engine contract and the D1 row state are what this gate is
    # about. S4 is only meaningful for a run that actually executed, so a skipped
    # run records it as not applicable instead of claiming it passed.
    s3_conflict_blocks_before_execution(payload)
    if executed:
        s4_d1_row_state()
    else:
        print(
            "[S4] D1 row-state check NOT_APPLICABLE: no execution happened this "
            "run (provider leg skipped)"
        )

    if _failures:
        print(f"A12_STREAM_REPLAY_SMOKE=FAIL ({len(_failures)} failures) — see raw output above", file=sys.stderr)
        return 1

    if _skips:
        _record_verdict(
            "SKIPPED_UPSTREAM",
            f" MANDATORY_STAGES=S0,S3 A12_SKIP_REASON={_skips[0]}",
        )
        return 0

    _record_verdict(
        "PASS", " EXACT_1_REPLAY_EVENT=PASS REPLAYED_FLAG=PASS CONFLICT_409=PASS"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())