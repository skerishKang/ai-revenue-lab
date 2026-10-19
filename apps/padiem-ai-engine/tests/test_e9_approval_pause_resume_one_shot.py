from __future__ import annotations

import asyncio
import importlib.util
import io
from pathlib import Path
from contextlib import redirect_stdout
import sys

import pytest

from app.approval_smoke_binding import (
    APPROVAL_SMOKE_AGENT_ID,
    APPROVAL_SMOKE_APP_ID,
    APPROVAL_SMOKE_CANONICAL_TOOL_ID,
    APPROVAL_SMOKE_RUNTIME_TOOL_ID,
    build_approval_smoke_binding,
)
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.orchestration_continuation import InMemoryContinuationStore
from app.orchestration_service import OrchestrationEngineService


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e9_approval_pause_resume_one_shot.py"
spec = importlib.util.spec_from_file_location("e9_approval_pause_resume_one_shot", SCRIPT)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


SECRET = "S" * 48
CONT_REF = "cont_private_opaque_ref_123"
PAUSE_ID = "pause_smoke_123"
CREATED_AT = "2026-10-07T00:00:00+00:00"


def _paused_body() -> dict:
    return {
        "ok": True,
        "orchestration": {
            "execution": {
                "answer": "",
                "route": {},
                "metadata": {"status": "paused", "tool_events": []},
            },
            "resolved_tool_ids": [runner.CANONICAL_TOOL_ID],
            "approval_pause": {
                "status": "paused",
                "continuation_id": PAUSE_ID,
                "tool_id": runner.RUNTIME_TOOL_ID,
                "requirement": "user_confirmation",
                "created_at": CREATED_AT,
            },
            "continuation_ref": CONT_REF,
        },
    }


def _completed_body() -> dict:
    return {
        "ok": True,
        "orchestration": {
            "execution": {
                "answer": "",
                "route": {},
                "metadata": {
                    "status": "completed",
                    "tool_events": [
                        {
                            "tool_id": runner.RUNTIME_TOOL_ID,
                            "status": "completed",
                        }
                    ],
                },
            },
            "resolved_tool_ids": [runner.CANONICAL_TOOL_ID],
            "approval_pause": None,
        },
    }


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, body):
        self.calls.append((method, path, body))
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


def test_fixture_identity_constants_match_canonical_binding() -> None:
    binding = build_approval_smoke_binding()
    profile = binding.resolve_authority(APPROVAL_SMOKE_AGENT_ID).compiled.runtime_profile

    assert runner.APP_ID == APPROVAL_SMOKE_APP_ID
    assert runner.CANONICAL_AGENT_ID == APPROVAL_SMOKE_AGENT_ID
    assert runner.RUNTIME_AGENT_ID == profile.id
    assert runner.CANONICAL_TOOL_ID == APPROVAL_SMOKE_CANONICAL_TOOL_ID
    assert runner.RUNTIME_TOOL_ID == APPROVAL_SMOKE_RUNTIME_TOOL_ID


def test_initial_payload_is_provider_free_fixed_authority_and_zero_retry() -> None:
    payload = runner._initial_payload("0123456789abcdef")
    assert payload["app_id"] == APPROVAL_SMOKE_APP_ID
    assert payload["agent"]["id"] == runner.RUNTIME_AGENT_ID
    assert payload["agent"]["model_policy"] == {"model": "test/provider-free"}
    assert payload["agent_plan"]["agent_id"] == APPROVAL_SMOKE_AGENT_ID
    assert payload["agent_plan"]["steps"][0]["tool_id"] == APPROVAL_SMOKE_RUNTIME_TOOL_ID
    assert payload["max_retries"] == 0
    assert payload["require_evidence"] is False
    assert payload["require_verification"] is False
    assert "provider" not in payload
    assert "credential" not in payload


def test_one_shot_posts_exactly_once_then_resumes_exactly_once_without_ref_output() -> None:
    fake = FakeTransport([(200, _paused_body()), (200, _completed_body())])
    output = io.StringIO()
    with redirect_stdout(output):
        runner.run_one_shot(fake, run_source="unit-test-run")

    assert len(fake.calls) == 2
    first = fake.calls[0]
    second = fake.calls[1]
    assert first[0:2] == ("POST", runner.ORCHESTRATE_PATH)
    assert second[0:2] == ("POST", runner.RESUME_PATH)
    assert first[2]["max_retries"] == 0
    assert second[2]["max_retries"] == 0
    assert second[2]["continuation_ref"] == CONT_REF
    assert second[2]["decision"]["pause_id"] == PAUSE_ID
    assert second[2]["decision"]["decided_at"] == CREATED_AT

    rendered = output.getvalue()
    assert CONT_REF not in rendered
    assert PAUSE_ID not in rendered
    assert SECRET not in rendered


def test_runner_does_not_retry_after_first_failure_and_does_not_echo_raw_body() -> None:
    fake = FakeTransport(
        [
            (
                503,
                {
                    "error": {
                        "code": "continuation_store_unavailable",
                        "message": f"must-not-leak-{SECRET}-{CONT_REF}",
                    }
                },
            )
        ]
    )
    with pytest.raises(runner.SmokeError) as exc:
        runner.run_one_shot(fake, run_source="failure-test")
    assert len(fake.calls) == 1
    message = str(exc.value)
    assert "continuation_store_unavailable" in message
    assert SECRET not in message
    assert CONT_REF not in message


def test_malformed_or_wrong_pause_fails_before_resume_request() -> None:
    bad = _paused_body()
    bad["orchestration"]["approval_pause"]["tool_id"] = "some.other.tool"
    fake = FakeTransport([(200, bad)])

    with pytest.raises(runner.SmokeError, match="APPROVAL_TOOL_MISMATCH"):
        runner.run_one_shot(fake, run_source="bad-pause")
    assert len(fake.calls) == 1


def test_completed_response_must_prove_exact_tool_completion_and_must_not_repause() -> None:
    bad_completed = _completed_body()
    bad_completed["orchestration"]["continuation_ref"] = "cont_second_pause"
    fake = FakeTransport([(200, _paused_body()), (200, bad_completed)])

    with pytest.raises(runner.SmokeError, match="RESUME_REPAUSED_UNEXPECTEDLY"):
        runner.run_one_shot(fake, run_source="repaused")
    assert len(fake.calls) == 2


def test_http_transport_disables_redirects_and_keeps_credential_only_in_header() -> None:
    transport = runner.HttpTransport(
        base_url="https://engine.padiem.net",
        caller_id="approval-smoke-caller",
        caller_credential=SECRET,
    )
    assert isinstance(transport._opener.handlers[-1], runner._NoRedirect) or any(
        isinstance(handler, runner._NoRedirect) for handler in transport._opener.handlers
    )

    source = SCRIPT.read_text(encoding="utf-8")
    assert "HTTP_RETRIES=0" in source
    assert "HTTP_REDIRECTS_FOLLOWED=0" in source
    assert "x-padiem-engine-credential" in source
    assert "print(continuation_ref" not in source
    assert "print(CALLER" not in source


def test_main_without_secret_stops_before_network(monkeypatch, capsys) -> None:
    monkeypatch.delenv(runner.CALLER_ID_ENV, raising=False)
    monkeypatch.delenv(runner.CALLER_CREDENTIAL_ENV, raising=False)
    assert runner.main() == 2
    captured = capsys.readouterr()
    assert "BLOCKED_MISSING_CALLER_AUTHORITY" in captured.err
    assert CONT_REF not in captured.err


class _ProviderBombRuntime:
    async def run(self, _request):
        raise AssertionError("provider/fallback runtime must not run")


class CanonicalServiceTransport:
    def __init__(self):
        self.binding = build_approval_smoke_binding()
        self.calls = []
        self.service = OrchestrationEngineService(
            runtime_factory=lambda _app_id: _ProviderBombRuntime(),
            b14_service_bound=True,
            continuation_store=InMemoryContinuationStore(),
            approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
            tool_binding_resolver=lambda app_id: (
                self.binding if app_id == APPROVAL_SMOKE_APP_ID else None
            ),
        )

    def request(self, method, path, body):
        self.calls.append((method, path, body))
        assert method == "POST"
        if path == runner.ORCHESTRATE_PATH:
            response = asyncio.run(self.service.orchestrate_payload(body))
        elif path == runner.RESUME_PATH:
            response = asyncio.run(self.service.resume_payload(body))
        else:
            raise AssertionError(f"unexpected path: {path}")
        return response.status_code, response.body


def test_runner_payload_completes_real_canonical_pause_resume_without_provider() -> None:
    transport = CanonicalServiceTransport()
    runner.run_one_shot(transport, run_source="canonical-integration")
    assert [call[1] for call in transport.calls] == [
        runner.ORCHESTRATE_PATH,
        runner.RESUME_PATH,
    ]
    assert len(transport.calls) == 2
