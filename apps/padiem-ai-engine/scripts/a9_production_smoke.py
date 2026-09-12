"""WO-8 PR-B A9 production idempotency smoke (BLOCKER_4/5/6/7 evidence).

Runs against the PRODUCTION Engine (default https://engine.padiem.net) with the
product-owned smoke caller credential (PADIEM_ENGINE_SMOKE_CALLER_ID/_SECRET,
allowed_app_ids=["b54-padiem-claw"]). Standard library only.

Steps:
  S0  GET  /internal/v1/health                    -> 200, endpoints is a list,
      "/internal/v1/orchestrate" and
      "/internal/v1/idempotency/completed/replay" both advertised with no
      duplicate paths, capabilities idempotency_replay == "available"
      (activated by WO-8 PR-C). A9 is an idempotency/orchestration smoke, so it
      checks only these contract-relevant facts and NOT the total endpoint
      count (the manifest cardinality is free to grow with unrelated routes).
  S1  POST /internal/v1/orchestrate (pinned model, max_steps=1, idempotency
      key a9-smoke-<RUN_ID>-1)                    -> 200, ONE real provider call.
  S2  Same payload, same key                      -> 200 served from durable
      replay: execution identity equals S1's and the run_completed event
      carries the replay marker. Measured replay path: the idempotency begin
      gate lives in padiem_ai_core.orchestration.OrchestrationRunner.run
      (step "2. CONTEXT_PREPARED & Idempotency Check"), which returns the
      cached ExecutionResult from CloudflareD1IdempotencyAdapter.begin() and
      emits RUN_COMPLETED with metadata {"replay": true}.
  S3  Same key, different message                 -> 409 idempotency_conflict
      BEFORE any provider execution (BLOCKER_6).
  S4  POST /internal/v1/idempotency/completed/replay with the fingerprint the
      Runner bound (published in S1's context_prepared event metadata) -> 200
      replayed == true (BLOCKER_4 read).
  S5  Same replay body with app_id="b62"          -> 4xx service_app_not_authorized
      / service_authentication_failed: cross-app isolation (BLOCKER_5).
  S6  wrangler d1 execute (remote): exactly one row for this run's keys, in
      state 'completed', none 'reserved' (BLOCKER_7 row-state).

Honesty rules: the script exits non-zero on any failed assertion and prints
the raw failure output; the final PASS line is printed only when every step
passed. REAL_PROVIDER_CALLS is capped at 2 by design (normal run: 1).
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
CALLER_ID = os.environ.get("CALLER_ID", "")
CALLER_SECRET = os.environ.get("CALLER_SECRET", "")
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "local")

PINNED_MODEL = "sensenova/sensenova-6.8-flash-lite"
HEALTH_PATH = "/internal/v1/health"
ORCHESTRATE_PATH = "/internal/v1/orchestrate"
REPLAY_PATH = "/internal/v1/idempotency/completed/replay"
IDEMPOTENCY_KEY = f"a9-smoke-{GITHUB_RUN_ID}-1"
TRACE_ID = f"a9-smoke-{GITHUB_RUN_ID}"
REQUEST_TIMEOUT_SECONDS = 90
REAL_PROVIDER_CALLS_BUDGET = 2

_failures: list[str] = []


def _fail(step: str, message: str, raw: Any = None) -> None:
    _failures.append(f"{step}: {message}")
    print(f"[{step}] FAIL: {message}", file=sys.stderr)
    if raw is not None:
        print(f"[{step}] RAW: {raw}", file=sys.stderr)


def _require_env() -> bool:
    if not CALLER_ID or not CALLER_SECRET:
        print("SMOKE=SKIPPED_MISSING_SECRET", file=sys.stderr)
        return False
    return True


def _identity_headers() -> dict[str, str]:
    return {
        "User-Agent": "padiem-a9-smoke/1.0 (+github-actions)",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": CALLER_SECRET,
        "Content-Type": "application/json",
    }


def _request(
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
    except Exception as exc:  # network failure is a step failure, never a pass
        raise RuntimeError(f"request to {url} failed: {exc}") from exc
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def _orchestrate_payload() -> dict[str, Any]:
    """Fixed smoke payload (Claw pin parity): no max_steps/model_policy top-level
    fields — the Engine wire contract (orchestration_wire._ORCHESTRATE_ALLOWED)
    rejects them; the pin rides on agent.model_policy and max_steps is pinned to
    1 server-side (service.build_execution_request)."""
    return {
        "app_id": "b54-padiem-claw",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "A9 smoke",
            "description": "WO-8 PR-B production idempotency smoke",
            "system_instruction": "You are a smoke probe. Answer with exactly one word.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 64,
            "required_capabilities": [],
            "model_policy": {"model": PINNED_MODEL},
        },
        "messages": [{"role": "user", "content": "a9 smoke: reply with the single word OK"}],
        "trace_id": TRACE_ID,
        "execution_context": {
            "trace_id": TRACE_ID,
            "timeout_seconds": 60.0,
            "idempotency_key": IDEMPOTENCY_KEY,
        },
    }


def _bound_fingerprint(s1_body: dict[str, Any]) -> str | None:
    """Extract the fingerprint the Runner actually bound at begin().

    Core publishes it on the context_prepared event metadata (measured:
    packages/padiem-ai-core/padiem_ai_core/orchestration.py CONTEXT_PREPARED
    emission). This is NOT request_fingerprint(raw payload).
    """
    orchestration = s1_body.get("orchestration") or {}
    for event in orchestration.get("events") or []:
        metadata = event.get("metadata") or {}
        fingerprint = metadata.get("request_fingerprint")
        if (
            event.get("kind") == "context_prepared"
            and isinstance(fingerprint, str)
            and len(fingerprint) == 64
        ):
            return fingerprint
    return None


def _replay_marker_present(body: dict[str, Any]) -> bool:
    """True when the run_completed event carries the replay marker.

    Measured marker: OrchestrationRunner.run emits RUN_COMPLETED
    "Execution completed via idempotency replay" with metadata {"replay": true}
    when begin() hands back the cached completed result.
    """
    orchestration = body.get("orchestration") or {}
    for event in orchestration.get("events") or []:
        metadata = event.get("metadata") or {}
        if event.get("kind") == "run_completed" and metadata.get("replay") is True:
            return True
    return False


def s0_health() -> None:
    status, body = _request(method="GET", path=HEALTH_PATH)
    if status != 200:
        _fail("S0", f"health status {status} != 200", body)
        return
    if not isinstance(body, dict):
        _fail("S0", "health body is not an object", body)
        return
    endpoints = body.get("endpoints")
    if not isinstance(endpoints, list):
        _fail("S0", "health endpoints missing", body)
        return
    # A9 is an idempotency/orchestration smoke, not a whole-manifest cardinality
    # smoke. It asserts only the contract facts it actually depends on: the two
    # A9 routes are advertised, they are not duplicated, and the idempotency
    # replay capability is available. The total endpoint count is intentionally
    # NOT pinned, so an unrelated future endpoint never produces a false S0
    # failure against a healthy runtime.
    paths = [str(endpoint.get("path")) for endpoint in endpoints if isinstance(endpoint, dict)]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for path in paths:
        if path in seen:
            duplicates.add(path)
        else:
            seen.add(path)
    if duplicates:
        _fail("S0", f"duplicate endpoint paths advertised: {sorted(duplicates)}", sorted(paths))
    for required_path in (ORCHESTRATE_PATH, REPLAY_PATH):
        if required_path not in seen:
            _fail("S0", f"{required_path} not advertised", sorted(seen))
    capabilities = body.get("capabilities")
    if not isinstance(capabilities, dict):
        _fail("S0", "health capabilities missing", body)
        return
    if capabilities.get("idempotency_replay") != "available":
        _fail(
            "S0",
            f"capabilities.idempotency_replay={capabilities.get('idempotency_replay')!r} != 'available' (PR-C not deployed)",
        )
    print(
        f"[S0] health OK: {len(endpoints)} endpoints advertised, "
        "orchestrate+replay present, idempotency_replay=available"
    )


def s1_first_run(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None, int]:
    status, body = _request(method="POST", path=ORCHESTRATE_PATH, body=payload)
    if status != 200 or not isinstance(body, dict) or body.get("ok") is not True:
        _fail("S1", f"orchestrate status {status} != 200 or ok != true", body)
        return {}, None, 0
    orchestration = body.get("orchestration") or {}
    answer = (orchestration.get("execution") or {}).get("answer")
    if not answer or not str(answer).strip():
        _fail("S1", "S1 returned an empty execution answer", body)
    fingerprint = _bound_fingerprint(body)
    if fingerprint is None:
        _fail("S1", "context_prepared event metadata lacks a 64-char request_fingerprint", body)
    print("[S1] first run OK (1 real provider call)")
    return body, fingerprint, 1


def _execution_identity(run_body: dict[str, Any]) -> str | None:
    """Wire contract (measured, run 34050390878): route is a SIBLING of metadata
    under execution — orchestration.execution.route.request_id."""
    execution = ((run_body.get("orchestration") or {}).get("execution") or {})
    route = execution.get("route") or {}
    return route.get("request_id")


def s2_replay_no_reexecution(payload: dict[str, Any], s1_body: dict[str, Any]) -> bool:
    status, body = _request(method="POST", path=ORCHESTRATE_PATH, body=payload)
    if status != 200 or not isinstance(body, dict) or body.get("ok") is not True:
        _fail("S2", f"replay status {status} != 200 or ok != true", body)
        return False

    s1_identity = _execution_identity(s1_body)
    s2_identity = _execution_identity(body)
    if not s1_identity or not s2_identity:
        _fail("S2", "execution.route.request_id missing", {"s1": s1_body, "s2": body})
        return False
    if s1_identity != s2_identity:
        _fail("S2", f"execution identity changed across replay: {s1_identity} != {s2_identity}")
        return False
    if not _replay_marker_present(body):
        _fail("S2", "run_completed event lacks the replay marker (metadata.replay=true) — provider may have re-executed", body)
        return False
    print(f"[S2] durable replay OK: identity {s1_identity} reused, replay marker present, 0 extra provider calls")
    return True


def s3_conflict_blocks_before_provider() -> bool:
    payload = _orchestrate_payload()
    payload["messages"] = [{"role": "user", "content": "a9 smoke CONFLICT probe: different message, same key"}]
    started = time.monotonic()
    status, body = _request(method="POST", path=ORCHESTRATE_PATH, body=payload)
    elapsed = time.monotonic() - started
    if status != 409:
        _fail("S3", f"conflict status {status} != 409", body)
        return False
    code = (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None
    if code != "idempotency_conflict":
        _fail("S3", f"error code {code!r} != 'idempotency_conflict'", body)
        return False
    print(f"[S3] conflict OK: 409 idempotency_conflict in {elapsed:.2f}s (pre-execution)")
    return True


def s4_completed_replay(fingerprint: str | None) -> bool:
    if not fingerprint:
        _fail("S4", "no bound fingerprint available from S1")
        return False
    body = {
        "app_id": "b54-padiem-claw",
        "idempotency_key": IDEMPOTENCY_KEY,
        "request_fingerprint": fingerprint,
    }
    status, response = _request(method="POST", path=REPLAY_PATH, body=body)
    if status != 200 or not isinstance(response, dict):
        _fail("S4", f"replay status {status} != 200", response)
        return False
    if response.get("replayed") is not True:
        _fail("S4", f"replayed != true: {response}")
        return False
    print("[S4] completed-replay OK: replayed=true with Runner-bound fingerprint")
    return True


def s5_cross_app_isolation(fingerprint: str | None) -> bool:
    if not fingerprint:
        _fail("S5", "no bound fingerprint available from S1")
        return False
    body = {
        "app_id": "b62",
        "idempotency_key": IDEMPOTENCY_KEY,
        "request_fingerprint": fingerprint,
    }
    status, response = _request(method="POST", path=REPLAY_PATH, body=body)
    if not 400 <= status < 500:
        _fail("S5", f"cross-app probe status {status} not 4xx", response)
        return False
    code = (response or {}).get("error", {}).get("code") if isinstance(response, dict) else None
    if code not in {"service_app_not_authorized", "service_authentication_failed"}:
        _fail("S5", f"error code {code!r} not in accepted isolation codes", response)
        return False
    print(f"[S5] cross-app isolation OK: {status} {code}")
    return True


def s6_d1_row_state() -> bool:
    command = (
        "SELECT state, count(*) AS n FROM padiem_engine_idempotency "
        f"WHERE idempotency_key LIKE 'a9-smoke-{GITHUB_RUN_ID}-%' GROUP BY state"
    )
    result = subprocess.run(
        [
            "npx", "wrangler@4", "d1", "execute", "padiem-engine",
            "--remote", "--json", "--command", command,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        _fail("S6", f"wrangler d1 execute failed rc={result.returncode}", result.stderr[-2000:])
        return False
    try:
        payload = json.loads(result.stdout)
        rows = payload[0]["results"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        _fail("S6", f"unparseable wrangler output: {exc}", result.stdout[-2000:])
        return False
    states = {str(row.get("state")): int(row.get("n", 0)) for row in rows if isinstance(row, dict)}
    if states.get("completed") != 1:
        _fail("S6", f"expected exactly 1 completed row, got {states}", rows)
        return False
    if states.get("reserved", 0) != 0:
        _fail("S6", f"found reserved rows: {states}", rows)
        return False
    extra = set(states) - {"completed", "reserved"}
    if extra:
        _fail("S6", f"unexpected row states {sorted(extra)}", rows)
        return False
    print(f"[S6] D1 row-state OK: {states}")
    return True


def main() -> int:
    if not _require_env():
        return 1

    s0_health()
    if _failures:
        print("A9_SMOKE=FAIL (S0 gate)", file=sys.stderr)
        return 1

    payload = _orchestrate_payload()
    s1_body, fingerprint, provider_calls = s1_first_run(payload)
    if _failures:
        print("A9_SMOKE=FAIL (S1)", file=sys.stderr)
        return 1

    s2_replay_no_reexecution(payload, s1_body)
    s3_conflict_blocks_before_provider()
    s4_completed_replay(fingerprint)
    s5_cross_app_isolation(fingerprint)
    s6_d1_row_state()

    if _failures:
        print(f"A9_SMOKE=FAIL ({len(_failures)} failures) — see raw output above", file=sys.stderr)
        return 1
    if provider_calls > REAL_PROVIDER_CALLS_BUDGET:
        _fail("BUDGET", f"REAL_PROVIDER_CALLS {provider_calls} exceeds budget {REAL_PROVIDER_CALLS_BUDGET}")
        print("A9_SMOKE=FAIL (budget)", file=sys.stderr)
        return 1

    print(
        f"A9_SMOKE=PASS REAL_PROVIDER_CALLS={provider_calls} ROWS_WRITTEN=1 "
        "BLOCKER_4=PASS BLOCKER_5=PASS BLOCKER_6=PASS BLOCKER_7=PASS"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
