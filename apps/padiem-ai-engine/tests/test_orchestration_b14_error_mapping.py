"""Slice C (#1932): B14 model-execution failures must map to 4xx model-level
errors instead of being swallowed by the generic engine_internal_error 500 path.

The defect: B14 model-execution failures (e.g. upstream 502, model-not-found
404, rate-limit 429) surfaced as ``ExecutionRuntimeError`` and were caught by
``orchestrate_payload``'s final ``except Exception -> engine_internal_error 500``,
hiding the cause and the retryable flag from callers.

These tests pin the fix:
* B14 failures (404 / 429 / 502 and friends) become 4xx responses that preserve
  the safe error code and the retryable flag.
* The upstream raw response body is never forwarded (only safe code / status /
  message), so no secret/raw detail leaks to the caller.
* Genuine engine-internal failures stay 500 so real faults remain visible.
"""

from __future__ import annotations

import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14ExecutionError,
)
from padiem_ai_core.contracts import (
    ErrorClass,
    RunMetadata,
    RunStatus,
)
from padiem_ai_core.orchestration import OrchestrationRunner
from padiem_ai_core.execution_runtime import ExecutionRuntimeError
from app.orchestration_service import OrchestrationEngineService
from app.service import ServiceResponse


def make_valid_payload(app_id: str = "b62") -> dict:
    return {
        "app_id": app_id,
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "trace_id": "tr_orch_test",
        "execution_context": {"trace_id": "tr_orch_test", "timeout_seconds": 15.0},
    }


def _run_metadata(error_class: ErrorClass) -> RunMetadata:
    return RunMetadata(
        trace_id="tr_test",
        app_id="b62",
        agent_id="agent:padiem:orchestrator_1",
        status=RunStatus.FAILED,
        error_class=error_class,
    )


class _StubRuntime:
    """Satisfies OrchestrationRunner.__init__ without doing real work.

    ``OrchestrationRunner.run`` is monkeypatched in the tests below, so this
    stub's run must never actually be invoked.
    """

    async def run(self, *args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("stub runtime must not be invoked directly")


# (b14_code, error_class, retryable, expected_status, expected_retryable)
_B14_FAILURE_CASES = [
    ("upstream_request_error", ErrorClass.INPUT_ERROR, False, 400, False),  # 404
    ("upstream_server_error", ErrorClass.INTERNAL_ERROR, True, 429, True),  # 502
    ("upstream_rate_limited", ErrorClass.PROVIDER_RATE_LIMIT, True, 429, True),  # 429
    ("upstream_timeout", ErrorClass.PROVIDER_TIMEOUT, True, 429, True),
    ("upstream_auth_error", ErrorClass.AUTH_ERROR, False, 403, False),
    ("malformed_upstream", ErrorClass.PROVIDER_BAD_RESPONSE, False, 422, False),
]


@pytest.mark.parametrize(
    "code,error_class,retryable,exp_status,exp_retryable",
    _B14_FAILURE_CASES,
)
async def test_orchestrate_b14_failure_maps_to_4xx(
    monkeypatch,
    code: str,
    error_class: ErrorClass,
    retryable: bool,
    exp_status: int,
    exp_retryable: bool,
) -> None:
    message = f"Model execution failed ({code})."

    def fake_run(self, request):  # noqa: ANN001 - monkeypatched onto OrchestrationRunner
        raise ExecutionRuntimeError(
            code,
            message,
            metadata=_run_metadata(error_class),
            retryable=retryable,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)

    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: _StubRuntime(),
        b14_service_bound=True,
    )
    response = await service.orchestrate_payload(make_valid_payload())

    assert isinstance(response, ServiceResponse)
    assert 400 <= response.status_code < 500, (
        f"{code}: expected 4xx, got {response.status_code}"
    )
    assert response.status_code == exp_status, (
        f"{code}: status {response.status_code} != expected {exp_status}"
    )
    body = response.body
    assert body["ok"] is False
    # The safe B14 code is preserved (not collapsed to engine_internal_error).
    assert body["error"]["code"] == code, f"{code}: safe code not preserved"
    assert body["error"]["retryable"] is exp_retryable
    # No upstream response body / raw detail leaks: only the safe contract shape.
    assert set(body.keys()) == {"ok", "error"}
    assert set(body["error"].keys()) == {"code", "message", "retryable", "metadata"}
    assert body["error"]["message"] == message


async def test_orchestrate_b14_failure_never_500(monkeypatch) -> None:
    """Regression guard: no B14 model failure may land on the 500 path."""

    def fake_run(self, request):  # noqa: ANN001
        raise ExecutionRuntimeError(
            "upstream_server_error",
            "Model execution service failed.",
            metadata=_run_metadata(ErrorClass.INTERNAL_ERROR),
            retryable=True,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: _StubRuntime(),
        b14_service_bound=True,
    )
    response = await service.orchestrate_payload(make_valid_payload())
    assert response.status_code != 500
    assert response.body["error"]["code"] != "engine_internal_error"


async def test_orchestrate_genuine_internal_stays_500(monkeypatch) -> None:
    """Genuine engine-internal failures must remain 500, not be remapped to 4xx."""

    def fake_run(self, request):  # noqa: ANN001
        raise ExecutionRuntimeError(
            "execution_failed",
            "Model execution failed.",
            metadata=_run_metadata(ErrorClass.INTERNAL_ERROR),
            retryable=False,
        )

    monkeypatch.setattr(OrchestrationRunner, "run", fake_run)
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: _StubRuntime(),
        b14_service_bound=True,
    )
    response = await service.orchestrate_payload(make_valid_payload())
    assert response.status_code == 500
    assert response.body["error"]["code"] == "engine_internal_error"


_LEAK_SENTINEL = "LEAK_SENTINEL_9f3a2b"


class _RecordingB14Transport(httpx.AsyncBaseTransport):
    """Returns a canned B14 HTTP response without any real network call."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self._status = status_code
        self._body = body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self._status, content=self._body, request=request)


@pytest.mark.parametrize("status_code", [404, 429, 502])
async def test_b14_raw_error_body_not_forwarded(status_code: int) -> None:
    """The raw upstream B14 body (code/status/message/detail) must never reach
    the engine-visible error surface — only safe, bounded fields do."""
    raw_body = json.dumps(
        {
            "ok": False,
            "error": {
                "code": "kilo_free_rate_limited",
                "status": status_code,
                "message": _LEAK_SENTINEL,
                "detail": _LEAK_SENTINEL,
            },
        }
    ).encode("utf-8")
    transport = _RecordingB14Transport(status_code, raw_body)
    config = B14ExecutionConfig(base_url="https://b14.internal")
    client = B14ExecutionClient(config, transport=transport)
    request = B14ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="b14-model",
        temperature=0.0,
    )

    with pytest.raises(B14ExecutionError) as excinfo:
        await client.execute(request)
    err = excinfo.value
    # Core strips the raw upstream body: the sentinel and the raw B14 error.code
    # never reach the engine-visible error surface.
    assert _LEAK_SENTINEL not in err.safe_message
    assert err.code != "kilo_free_rate_limited"
    assert _LEAK_SENTINEL not in err.code
