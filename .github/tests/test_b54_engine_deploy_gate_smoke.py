"""Contract tests for the B54 engine deploy gate smoke-idempotency job (WO-8 PR-B).

Proves statically that the deploy gate:
  1. grew a smoke-idempotency job that needs deploy-production-engine and runs
     only on the exact deploy confirmation phrase;
  2. runs in the production environment with a bounded timeout;
  3. binds the smoke evidence path to the single canonical B62 authority
     (fixed caller id b54-kagent + secrets.B62_P01_ENGINE_CREDENTIAL) and no
     longer references the independent PADIEM_ENGINE_SMOKE_CALLER_* secrets;
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
SMOKE_ONLY_WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-production-smoke-only-gate.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _smoke_idempotency_block(text: str) -> str:
    return text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]


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


def test_deploy_gate_smoke_uses_canonical_b54_kagent_caller_id() -> None:
    # #2484 Goal A (test 1): the deploy gate smoke binds the fixed non-secret
    # canonical caller id b54-kagent (both the CALLER_ID name the A9 script reads
    # and the legacy NAME the A10 script reads).
    smoke_block = _smoke_idempotency_block(_workflow_text())
    assert "CALLER_ID: b54-kagent" in smoke_block
    assert "PADIEM_ENGINE_SMOKE_CALLER_ID: b54-kagent" in smoke_block


def test_deploy_gate_smoke_credential_source_is_b62_p01() -> None:
    # #2484 Goal A (test 2): the credential source is the single canonical B62
    # secret, referenced BY NAME only — never a literal value.
    smoke_block = _smoke_idempotency_block(_workflow_text())
    assert "CALLER_SECRET: ${{ secrets.B62_P01_ENGINE_CREDENTIAL }}" in smoke_block
    assert "PADIEM_ENGINE_SMOKE_CALLER_SECRET: ${{ secrets.B62_P01_ENGINE_CREDENTIAL }}" in smoke_block
    assert not re.search(
        r"(?:CALLER_SECRET|PADIEM_ENGINE_SMOKE_CALLER_SECRET):\s*(?![$\[{])[A-Za-z0-9]",
        smoke_block,
    )


def test_deploy_gate_smoke_no_longer_references_legacy_smoke_secrets() -> None:
    # #2484 Goal A (test 3): the independent PADIEM_ENGINE_SMOKE_CALLER_* SECRETS
    # no longer gate A9/A10/A11/A12. The env NAMES may persist (A10 reads them)
    # but only re-pointed at the canonical source; no old secret reference.
    text = _workflow_text()
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_ID" not in text
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_SECRET" not in text


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


# --- #2484 Goal B: mutation-free post-deploy smoke-only production gate ------
# These static contract tests prove the new smoke-only gate can re-run
# A9/A10/A11/A12 against the already-deployed Engine WITHOUT any deploy, secret
# PUT, binding mutation, D1 migration, rollback, Phase-A/Chat request or source
# mutation, and that it fails closed unless the live served version is exactly
# the expected one carrying the V1 + OVERLAY caller-registry secrets.
# Forbidden-command assertions run against the parsed `run:` script bodies only,
# so the explanatory YAML comments never satisfy or defeat them.

def _smoke_only_text() -> str:
    return SMOKE_ONLY_WORKFLOW.read_text(encoding="utf-8")


def _smoke_only_data() -> dict:
    return yaml.safe_load(_smoke_only_text())


def _smoke_only_trigger() -> dict:
    data = _smoke_only_data()
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return trigger


def _smoke_only_inputs() -> dict:
    return _smoke_only_trigger()["workflow_dispatch"]["inputs"]


def _smoke_only_job() -> dict:
    return _smoke_only_data()["jobs"]["smoke-only-production-gate"]


def _smoke_only_runs() -> str:
    return "\n".join(str(step.get("run", "")) for step in _smoke_only_job()["steps"])


def _smoke_only_step_names() -> list[str]:
    return [str(step.get("name", "")) for step in _smoke_only_job()["steps"]]


def test_smoke_only_gate_workflow_exists() -> None:
    assert SMOKE_ONLY_WORKFLOW.is_file(), "smoke-only gate workflow must exist"


def test_smoke_only_gate_is_workflow_dispatch_only() -> None:
    # Goal B test 4: dispatch-only, single job, no push/PR/schedule trigger.
    assert list(_smoke_only_trigger().keys()) == ["workflow_dispatch"]
    assert len(_smoke_only_data()["jobs"]) == 1


def test_smoke_only_gate_requires_explicit_confirmation() -> None:
    # Goal B test 5: an explicit confirmation phrase gates the whole job.
    assert _smoke_only_inputs()["confirmation"]["required"] is True
    assert (
        _smoke_only_job()["if"]
        == "github.event.inputs.confirmation == 'RUN_B54_ENGINE_POSTDEPLOY_SMOKE_ONLY'"
    )


def test_smoke_only_gate_locks_exact_main_workflow_source() -> None:
    # Goal B test 6: exact-main workflow-source lock, no persisted credentials.
    assert _smoke_only_inputs()["target_sha"]["required"] is True
    text = _smoke_only_text()
    runs = _smoke_only_runs()
    assert "ref: ${{ github.event.inputs.target_sha }}" in text
    assert "persist-credentials: false" in text
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.target_sha }}"' in runs
    assert 'test "$(git rev-parse origin/main)" = "${{ github.event.inputs.target_sha }}"' in runs


def test_smoke_only_gate_records_deployed_source_separately_from_main() -> None:
    # Goal B SHA semantics: the gate must never claim current main is the
    # deployed Engine source; it records the fixed deployed SHA separately.
    runs = _smoke_only_runs()
    assert "WORKFLOW_SOURCE_SHA=" in runs
    assert "DEPLOYED_ENGINE_SOURCE_SHA=" in runs
    assert "EXPECTED_SERVED_VERSION=" in runs
    assert "WORKFLOW_SOURCE_IS_NOT_ASSERTED_AS_DEPLOYED_SOURCE" in runs
    # the deployed Engine source is a FIXED literal, not derived from target_sha
    assert _smoke_only_job()["env"]["DEPLOYED_ENGINE_SOURCE_SHA"] == "b0bf34ab90420d6b47070c192e108adf3f4ea76d"


def test_smoke_only_gate_requires_expected_served_version_input() -> None:
    # Goal B test 7: required input, validated to a safe charset before use.
    assert _smoke_only_inputs()["expected_served_version"]["required"] is True
    runs = _smoke_only_runs()
    assert "A-Za-z0-9._-" in runs
    assert "EXPECTED_SERVED_VERSION_UNSAFE" in runs


def test_smoke_only_gate_uses_canonical_deployments_resolver() -> None:
    # Goal B test 8: GET-only, canonical resolver, no mutating HTTP method.
    runs = _smoke_only_runs()
    assert "b54_engine_served_version_guard.py" in runs
    assert "resolve-active" in runs
    assert "curl -fsS" in runs
    assert "-X POST" not in runs
    assert "-X PUT" not in runs


def test_smoke_only_gate_fails_closed_on_served_version_mismatch_before_a9() -> None:
    # Goal B test 9: served-version mismatch aborts before any smoke runs.
    names = _smoke_only_step_names()
    preflight_idx = next(i for i, n in enumerate(names) if "served-version preflight" in n)
    a9_idx = names.index("Run A9 production idempotency smoke")
    assert preflight_idx < a9_idx
    runs = _smoke_only_runs()
    assert "SERVED_VERSION_MISMATCH" in runs
    assert "SMOKE_ONLY_PREFLIGHT=FAIL_SERVED_VERSION_MISMATCH" in runs


def test_smoke_only_gate_requires_v1_and_overlay_name_type_readback() -> None:
    # Goal B test 10: V1 + OVERLAY NAME/TYPE readback required on the served version.
    runs = _smoke_only_runs()
    assert "verify" in runs
    assert "--expect-overlay" in runs
    assert "PREFLIGHT_V1_OVERLAY_PRESENT=PASS" in runs


def test_smoke_only_gate_never_outputs_secret_values() -> None:
    # Goal B test 11: secrets are consumed via env only, never interpolated or
    # echoed inside a run script.
    runs = _smoke_only_runs()
    assert "secrets." not in runs
    assert not re.search(r"echo[^\n]*CALLER_SECRET", runs)


def test_smoke_only_gate_runs_a9_a10_a11_a12_in_exact_order() -> None:
    # Goal B test 12: A9 -> A10 -> A11 -> A12, each wired to its script.
    names = _smoke_only_step_names()
    order = [
        "Run A9 production idempotency smoke",
        "Run A10 continuation fail-closed smoke",
        "Run A11 Gmail tool_runtime smoke",
        "Run A12 streaming idempotency replay smoke",
    ]
    for step_name in order:
        assert step_name in names
    positions = [names.index(step_name) for step_name in order]
    assert positions == sorted(positions)
    runs = _smoke_only_runs()
    assert "a9_production_smoke.py" in runs
    assert "a10_continuation_production_smoke.py" in runs
    assert "a11_gmail_tool_runtime_smoke.py" in runs
    assert "a12_stream_replay_production_smoke.py" in runs


def test_smoke_only_gate_a11_accepts_only_pass_or_deferred() -> None:
    # Goal B test 13: A11 never fakes PASS; FAIL is a hard gate failure.
    runs = _smoke_only_runs()
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=(PASS|DEFERRED)" in runs
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL" in runs


def test_smoke_only_gate_has_no_deploy_secret_rollback_or_migration_command() -> None:
    # Goal B tests 14-17: no deploy, secret PUT, rollback or D1 migration command.
    runs = _smoke_only_runs()
    for forbidden in (
        "pywrangler deploy",
        "wrangler deploy",
        "wrangler@4 deploy",
        "npx wrangler",
        "wrangler secret put",
        "secret put",
        "d1 migrate",
        "migrations/",
        "rollback",
    ):
        assert forbidden not in runs, f"forbidden mutation command in smoke-only run scripts: {forbidden}"


def test_smoke_only_gate_has_no_phase_a_or_chat_request() -> None:
    # Goal B test 18: no Phase-A / Chat product request.
    runs = _smoke_only_runs()
    for forbidden in ("padiem-chat", "/chat", "chat.padiem", "phase-a", "phase_a"):
        assert forbidden not in runs, f"forbidden Phase-A/Chat reference: {forbidden}"


def test_smoke_only_gate_uses_canonical_b62_credential() -> None:
    # Goal A parity: the smoke-only gate binds the same canonical authority.
    job = _smoke_only_job()
    env = job["env"]
    assert env["CALLER_ID"] == "b54-kagent"
    assert env["CALLER_SECRET"] == "${{ secrets.B62_P01_ENGINE_CREDENTIAL }}"
    assert env["PADIEM_ENGINE_SMOKE_CALLER_ID"] == "b54-kagent"
    assert env["PADIEM_ENGINE_SMOKE_CALLER_SECRET"] == "${{ secrets.B62_P01_ENGINE_CREDENTIAL }}"
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_ID" not in _smoke_only_text()
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_SECRET" not in _smoke_only_text()
