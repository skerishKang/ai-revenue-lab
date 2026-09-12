"""Contract tests for the B54 engine deploy gate smoke-idempotency job (WO-8 PR-B).

Proves statically that the deploy gate:
  1. grew a smoke-idempotency job that needs deploy-production-engine and runs
     only on the exact deploy confirmation phrase;
  2. runs in the production environment with a bounded timeout;
  3. references the smoke caller secrets BY NAME only (values never appear);
  4. checks out the exact target SHA without persisted credentials;
  5. fails honestly when smoke secrets are missing (SKIPPED_MISSING_SECRET);
  6. runs the A9 smoke script and requires the A9_SMOKE=PASS line;
  7. does not alter the existing deploy or rollback jobs.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
SMOKE_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a9_production_smoke.py"
A10_SMOKE_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a10_continuation_production_smoke.py"
A11_SMOKE_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a11_gmail_tool_runtime_smoke.py"
A12_SMOKE_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a12_stream_replay_production_smoke.py"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    # YAML 1.1 parses bare `on:` as True; normalise the key for portability.
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_smoke_job_exists_and_depends_on_deploy() -> None:
    wf = _workflow()
    assert "smoke-idempotency" in wf["jobs"]
    job = wf["jobs"]["smoke-idempotency"]
    assert job["needs"] == "deploy-production-engine"
    assert job["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_FROM_EXACT_MAIN'"


def test_smoke_job_is_production_scoped_and_time_bounded() -> None:
    wf = _workflow()
    job = wf["jobs"]["smoke-idempotency"]
    assert job["environment"] == "production"
    assert isinstance(job["timeout-minutes"], int)
    assert 0 < job["timeout-minutes"] <= 15


def test_smoke_job_references_secret_names_not_values() -> None:
    text = _workflow_text()
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_ID" in text
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_SECRET" in text
    # Secret VALUES must never appear literally in the workflow.
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert not re.search(r"PADIEM_ENGINE_SMOKE_[A-Z_]+:\s*(?![$\[{])[A-Za-z0-9]", smoke_block)


def test_smoke_job_checks_out_exact_sha_without_persisted_credentials() -> None:
    text = _workflow_text()
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert 'ref: ${{ github.event.inputs.target_sha }}' in smoke_block
    assert "persist-credentials: false" in smoke_block


def test_smoke_job_fails_honestly_on_missing_secrets() -> None:
    text = _workflow_text()
    assert "SMOKE=SKIPPED_MISSING_SECRET" in text


def test_smoke_job_runs_the_a9_script_and_requires_the_pass_line() -> None:
    text = _workflow_text()
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert "a9_production_smoke.py" in smoke_block
    assert "A9_SMOKE=PASS" in smoke_block
    assert SMOKE_SCRIPT.is_file(), "smoke script must exist in the repo"


def test_smoke_job_runs_the_a10_script_and_requires_the_pass_line() -> None:
    # WO-9 PR-A (#1966): A10 continuation fail-closed smoke runs in the same
    # smoke-idempotency job, right after A9, and the job requires its PASS line.
    text = _workflow_text()
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert "a10_continuation_production_smoke.py" in smoke_block
    assert "A10_CONTINUATION_SMOKE=PASS" in smoke_block
    assert A10_SMOKE_SCRIPT.is_file(), "a10 smoke script must exist in the repo"


def test_a10_smoke_script_fail_closed_contract() -> None:
    """The A10 script's fail-closed verdicts must be present in its source."""
    source = A10_SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "A10_CONTINUATION_SMOKE=PASS" in source
    assert "ROWS_WRITTEN=0" in source
    assert "REAL_PROVIDER_CALLS=0" in source
    assert "SKIPPED_MISSING_SECRET" in source
    assert "STORE_BOUND=PASS" in source


def test_a10_smoke_script_sends_no_mutating_material() -> None:
    # A10 is a read-only fail-closed probe: its minimal bodies ({app_id,
    # continuation_ref} only) must never carry orchestration input, trusted
    # verification material, or a caller-supplied plan. The forbidden wire
    # fields must not even appear in the script source.
    a10_source = A10_SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "idempotency_key" not in a10_source
    assert "decision" not in a10_source


def test_a10_smoke_script_sends_explicit_user_agent() -> None:
    # 원인: Cloudflare BIC가 Python-urllib UA를 403/1010으로 차단 (a9와 동일 사유).
    a10_source = A10_SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert '"User-Agent"' in a10_source
    assert "padiem-a10-smoke/1.0" in a10_source


def test_smoke_job_runs_the_a11_script_and_requires_its_verdict() -> None:
    # WO-10 ACT-1 (#2010): A11 runs in the same smoke-idempotency job, between
    # A10 and A12. The step requires an explicit verdict line. DEFERRED is an
    # honest, non-blocking record (route not wired / runtime unbound / tool not
    # authorized); FAIL is a hard gate failure. PASS is never faked.
    text = _workflow_text()
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert "a11_gmail_tool_runtime_smoke.py" in smoke_block
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=(PASS|DEFERRED)" in smoke_block
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL" in smoke_block
    assert A11_SMOKE_SCRIPT.is_file(), "a11 smoke script must exist in the repo"


def test_smoke_job_runs_a9_a10_a11_a12_in_deterministic_order() -> None:
    # Static order contract: A9 -> A10 -> A11 -> A12 inside smoke-idempotency.
    wf = _workflow()
    steps = wf["jobs"]["smoke-idempotency"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    order = [
        "Run A9 production idempotency smoke",
        "Run A10 continuation fail-closed smoke",
        "Run A11 Gmail tool_runtime smoke",
        "Run A12 streaming idempotency replay smoke",
    ]
    positions = [names.index(name) for name in order]
    assert positions == sorted(positions)
    assert A10_SMOKE_SCRIPT.is_file() and A12_SMOKE_SCRIPT.is_file()


def test_a11_smoke_script_verdict_contract() -> None:
    source = A11_SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS" in source
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=DEFERRED" in source
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL" in source
    assert "SKIPPED_MISSING_SECRET" in source
    assert "REAL_PROVIDER_CALLS=0" in source
    assert "ROWS_WRITTEN=0" in source
    assert "D1_MUTATION=0" in source


def test_a11_smoke_script_accepts_no_credential_material() -> None:
    # No OAuth token, refresh token, client secret or credential value may be
    # accepted: the script takes no CLI arguments at all.
    source = A11_SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "argparse" not in source
    assert "sys.argv" not in source
    for forbidden in ("refresh_token", "client_secret", "access_token", "client_id", "oauth", "OAuth"):
        assert forbidden not in source


def test_a11_smoke_script_sends_explicit_user_agent() -> None:
    # Same reason as a9/a10: Cloudflare BIC blocks the Python-urllib UA.
    source = A11_SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert '"User-Agent"' in source
    assert "padiem-a11-smoke/1.0" in source
    assert "x-padiem-engine-caller" in source


def test_deploy_and_rollback_jobs_unchanged_in_shape() -> None:
    wf = _workflow()
    deploy = wf["jobs"]["deploy-production-engine"]
    rollback = wf["jobs"]["rollback-production-engine"]
    assert deploy["environment"] == "production"
    assert deploy["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_FROM_EXACT_MAIN'"
    assert rollback["if"] == "github.event.inputs.confirmation == 'ROLLBACK_B54_ENGINE_TO_PREVIOUS_VERSION'"
    assert any(step.get("name") == "Post-deploy smoke" for step in deploy["steps"])


def test_smoke_script_final_line_contract() -> None:
    """The smoke script's success line must carry the exact blocker verdicts."""
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "A9_SMOKE=PASS" in source
    assert "BLOCKER_4=PASS" in source
    assert "BLOCKER_5=PASS" in source
    assert "BLOCKER_6=PASS" in source
    assert "BLOCKER_7=PASS" in source
    assert "REAL_PROVIDER_CALLS=" in source
    assert "SKIPPED_MISSING_SECRET" in source


def test_smoke_script_sends_explicit_user_agent() -> None:
    # 원인: Cloudflare BIC가 Python-urllib UA를 403/1010으로 차단, run 34049550618
    smoke_source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert '"User-Agent"' in smoke_source


def test_smoke_script_reads_route_identity_from_execution_route() -> None:
    # 회귀: run 34050390878 — 스크립트가 execution.metadata.route.request_id를
    # 읽어 S2가 FAIL. 실제 wire는 execution.route.request_id (metadata는 형제).
    import importlib.util

    spec = importlib.util.spec_from_file_location("a9_production_smoke", SMOKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 최소 fixture: run 34050390878 [S2] RAW의 실제 응답 모양.
    run_body = {
        "ok": True,
        "orchestration": {
            "execution": {
                "answer": "OK",
                "route": {"request_id": "b14req_ec37a6ce00c0", "route_mode": "manual"},
                "metadata": {"trace_id": "a9-smoke-34050390878", "status": "completed"},
            },
        },
    }
    assert module._execution_identity(run_body) == "b14req_ec37a6ce00c0"
    # 이전 경로(metadata 아래 route)에는 아무것도 없다 — 형제 구조임을 고정.
    assert run_body["orchestration"]["execution"]["metadata"].get("route") is None


# --- #2466: A9 S0 must not pin whole-manifest endpoint cardinality ----------
# A9 is an idempotency/orchestration smoke, not a whole-manifest cardinality
# smoke. The stale "len(endpoints) != 15" assertion made an exact-current-main
# Engine deploy fail S0 against a healthy runtime (the manifest now advertises
# 16 endpoints). These regression tests lock the corrected S0 contract: it
# accepts the current 16-endpoint manifest, tolerates an unrelated future
# endpoint, still requires the orchestrate + completed-replay routes and the
# idempotency_replay capability, guards duplicate paths, and never touches the
# network.

_A9_ORCHESTRATE_PATH = "/internal/v1/orchestrate"
_A9_REPLAY_PATH = "/internal/v1/idempotency/completed/replay"

# The current Engine contract manifest advertises exactly these 16 paths.
_A9_CURRENT_16_PATHS = [
    "/internal/v1/execute",
    "/internal/v1/stream",
    "/internal/v1/health",
    _A9_ORCHESTRATE_PATH,
    "/internal/v1/orchestrate/resume",
    "/internal/v1/orchestrate/cancel",
    "/internal/v1/orchestrate/stream",
    "/internal/v1/research",
    "/internal/v1/memory",
    "/internal/v1/memory/write",
    "/internal/v1/agent-skill/run",
    "/internal/v1/agent-skill/resume",
    "/internal/v1/agent-skill/cancel",
    "/internal/v1/multimodal/execute",
    "/internal/v1/multimodal/stream",
    _A9_REPLAY_PATH,
]


def _a9_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("a9_production_smoke", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _a9_health_body(paths, *, capability="available"):
    return {
        "status": "ok",
        "service": "padiem-ai-engine",
        "capabilities": {"idempotency_replay": capability},
        "endpoints": [
            {"path": path, "method": "POST", "response_media_type": "application/json"}
            for path in paths
        ],
    }


def _a9_s0_failures(body):
    """Run A9 s0_health against a fake health body with zero network access.

    urllib.request.urlopen is guarded so any real request attempt raises, proving
    the S0 gate is exercised entirely offline.
    """
    import urllib.request
    from unittest.mock import patch

    module = _a9_module()
    with patch.object(module, "_failures", []) as failures, patch.object(
        module, "_request", return_value=(200, body)
    ), patch.object(urllib.request, "urlopen", side_effect=AssertionError("network call in test")):
        module.s0_health()
        return list(failures)


def test_a9_s0_passes_with_current_16_endpoint_manifest() -> None:
    assert len(_A9_CURRENT_16_PATHS) == 16
    assert _a9_s0_failures(_a9_health_body(_A9_CURRENT_16_PATHS)) == []


def test_a9_s0_tolerates_an_unrelated_future_endpoint() -> None:
    body = _a9_health_body(_A9_CURRENT_16_PATHS + ["/internal/v1/future/route"])
    assert _a9_s0_failures(body) == []


def test_a9_s0_fails_when_orchestrate_path_is_missing() -> None:
    paths = [p for p in _A9_CURRENT_16_PATHS if p != _A9_ORCHESTRATE_PATH]
    failures = _a9_s0_failures(_a9_health_body(paths))
    assert any(_A9_ORCHESTRATE_PATH in failure for failure in failures)


def test_a9_s0_fails_when_replay_path_is_missing() -> None:
    paths = [p for p in _A9_CURRENT_16_PATHS if p != _A9_REPLAY_PATH]
    failures = _a9_s0_failures(_a9_health_body(paths))
    assert any(_A9_REPLAY_PATH in failure for failure in failures)


def test_a9_s0_fails_when_idempotency_replay_capability_unavailable() -> None:
    body = _a9_health_body(_A9_CURRENT_16_PATHS, capability="unavailable")
    failures = _a9_s0_failures(body)
    assert any("idempotency_replay" in failure for failure in failures)


def test_a9_s0_fails_on_duplicate_endpoint_paths() -> None:
    body = _a9_health_body(_A9_CURRENT_16_PATHS + [_A9_ORCHESTRATE_PATH])
    failures = _a9_s0_failures(body)
    assert any("duplicate" in failure for failure in failures)


def test_a9_script_has_no_exact_endpoint_count_hardcode() -> None:
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "!= 15" not in source
    assert "15 endpoints" not in source
    assert "endpoints count" not in source
