"""Network-free contract tests for #3321 approval live smoke runner."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "a17_approval_continuation_live_smoke.py"


def _load():
    spec = importlib.util.spec_from_file_location("a17_approval_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _paused(module, trace_id: str):
    return {
        "ok": True,
        "orchestration": {
            "execution": {
                "metadata": {
                    "status": "paused",
                    "provider": "p01_agent_bridge",
                    "tool_events": [],
                },
                "route": {
                    "selected_provider": "p01_agent_bridge",
                    "selected_model": "bounded_agent_plan",
                },
            },
            "context": {"trace_id": trace_id},
            "continuation_ref": "cont_private_ref_123456",
            "approval_pause": {
                "continuation_id": "pause_private_id_123",
                "tool_id": module.RUNTIME_TOOL_ID,
                "requirement": "user_confirmation",
                "trace_id": trace_id,
                "created_at": "2026-10-01T05:59:00+00:00",
            },
            "continuation_state": {"status": "waiting_approval"},
        },
    }


def _completed(module, trace_id: str):
    return {
        "ok": True,
        "orchestration": {
            "execution": {
                "metadata": {
                    "status": "completed",
                    "provider": "p01_agent_bridge",
                    "tool_events": [
                        {
                            "tool_id": module.RUNTIME_TOOL_ID,
                            "status": "completed",
                            "duration_ms": 1,
                            "error_class": None,
                        }
                    ],
                },
                "route": {
                    "selected_provider": "p01_agent_bridge",
                    "selected_model": "bounded_agent_plan",
                },
            },
            "context": {"trace_id": trace_id},
            "continuation_state": {"status": "resumable"},
        },
    }


def test_success_is_exactly_two_posts_no_retry_and_leaks_no_ids_or_secret() -> None:
    module = _load()
    calls = []
    credential = "credential-NEVER-PRINT"
    caller = "caller:approval-smoke"
    token = "0123456789abcdef"
    trace = f"tr_approval_smoke_{token}"

    def transport(path, body, got_caller, got_credential):
        calls.append((path, body, got_caller, got_credential))
        if len(calls) == 1:
            return 200, json.dumps(_paused(module, trace)).encode()
        assert len(calls) == 2
        assert body["continuation_ref"] == "cont_private_ref_123456"
        assert body["decision"]["pause_id"] == "pause_private_id_123"
        assert body["decision"]["outcome"] == "approved"
        assert body["decision"]["decided_at"] == "2026-10-01T05:59:00+00:00"
        return 200, json.dumps(_completed(module, trace)).encode()

    out = io.StringIO()
    with redirect_stdout(out):
        code = module.run(
            caller,
            credential,
            transport=transport,
            token_hex=lambda _n: token,
        )

    rendered = out.getvalue()
    assert code == 0
    assert [call[0] for call in calls] == [
        module.ORCHESTRATE_PATH,
        module.RESUME_PATH,
    ]
    assert len(calls) == 2
    assert "APPROVAL_CONTINUATION_LIVE_SMOKE=PASS" in rendered
    assert "ORCHESTRATE_POST_COUNT=1" in rendered
    assert "RESUME_POST_COUNT=1" in rendered
    assert "NETWORK_RETRY_COUNT=0" in rendered
    assert "PROVIDER_CALLS=0" in rendered
    assert "CONTINUATION_STORE_MUTATION=BOUNDED_CANONICAL_LIFECYCLE" in rendered

    for secret in (
        credential,
        "cont_private_ref_123456",
        "pause_private_id_123",
        trace,
        token,
    ):
        assert secret not in rendered


def test_orchestrate_failure_stops_before_resume_and_outputs_only_safe_code() -> None:
    module = _load()
    calls = []

    def transport(path, body, caller, credential):
        calls.append(path)
        return 403, json.dumps(
            {
                "error": {
                    "code": "service_app_not_authorized",
                    "private": "cont_should_never_print",
                }
            }
        ).encode()

    out = io.StringIO()
    with redirect_stdout(out):
        code = module.run(
            "caller:approval-smoke",
            "credential-private",
            transport=transport,
            token_hex=lambda _n: "abcdef0123456789",
        )

    rendered = out.getvalue()
    assert code == 1
    assert calls == [module.ORCHESTRATE_PATH]
    assert "ENGINE_ERROR_CODE=service_app_not_authorized" in rendered
    assert "RESUME_POST_COUNT=0" in rendered
    assert "cont_should_never_print" not in rendered
    assert "credential-private" not in rendered


def test_noncanonical_pause_never_resumes_or_prints_raw_response() -> None:
    module = _load()
    calls = []

    def transport(path, body, caller, credential):
        calls.append(path)
        return 200, json.dumps(
            {
                "ok": True,
                "orchestration": {
                    "private_ref": "cont_hidden_raw_ref",
                },
            }
        ).encode()

    out = io.StringIO()
    with redirect_stdout(out):
        code = module.run(
            "caller:approval-smoke",
            "credential-private",
            transport=transport,
            token_hex=lambda _n: "abcdef0123456789",
        )

    rendered = out.getvalue()
    assert code == 1
    assert calls == [module.ORCHESTRATE_PATH]
    assert "FAIL_NONCANONICAL_PAUSE" in rendered
    assert "cont_hidden_raw_ref" not in rendered


def test_resume_failure_does_not_leak_continuation_pause_or_trace() -> None:
    module = _load()
    token = "1234567890abcdef"
    trace = f"tr_approval_smoke_{token}"
    calls = []

    def transport(path, body, caller, credential):
        calls.append(path)
        if len(calls) == 1:
            return 200, json.dumps(_paused(module, trace)).encode()
        return 409, json.dumps(
            {
                "error": {
                    "code": "continuation_identity_mismatch",
                    "private_ref": body["continuation_ref"],
                }
            }
        ).encode()

    out = io.StringIO()
    with redirect_stdout(out):
        code = module.run(
            "caller:approval-smoke",
            "credential-private",
            transport=transport,
            token_hex=lambda _n: token,
        )

    rendered = out.getvalue()
    assert code == 1
    assert len(calls) == 2
    assert "ENGINE_ERROR_CODE=continuation_identity_mismatch" in rendered
    assert "cont_private_ref_123456" not in rendered
    assert "pause_private_id_123" not in rendered
    assert trace not in rendered


def test_request_identity_is_fixed_in_source_not_argv_or_environment() -> None:
    module = _load()
    body = module.canonical_orchestrate_body(
        trace_id="tr_approval_smoke_fixed",
        nonce="nonce-fixed",
    )
    assert body["app_id"] == "b54-engine-approval-smoke"
    assert body["agent_plan"]["agent_id"] == "agent:padiem:approval_smoke@1"
    assert body["agent_plan"]["steps"][0]["tool_id"] == "approval_smoke.confirm"
    assert body["subject_id"] == "subject:approval-smoke"
    assert body["agent"]["id"].startswith("agent-runtime:")

    source = SCRIPT.read_text(encoding="utf-8")
    assert 'APP_ID = "b54-engine-approval-smoke"' in source
    assert 'CANONICAL_AGENT_ID = "agent:padiem:approval_smoke@1"' in source
    assert 'RUNTIME_TOOL_ID = "approval_smoke.confirm"' in source
    assert "argparse" not in source
    assert 'os.environ.get("APP_ID"' not in source
    assert 'os.environ.get("AGENT_ID"' not in source
    assert 'os.environ.get("TOOL_ID"' not in source


def test_runner_has_no_retry_redirect_follow_or_provider_endpoint() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "HTTPRedirectHandler" in source
    assert "def redirect_request" in source
    assert "for attempt" not in source
    assert "while " not in source
    assert "openai.com" not in source
    assert "api.telegram.org" not in source
    assert "googleapis.com" not in source
    assert "slack.com" not in source
    assert "print(raw" not in source
    assert "print(payload" not in source
    assert "PROVIDER_CALLS=0" in source
