"""#2550: split the generic stream-502 first-fail taxonomy for #2113.

Two known B62 boundaries previously emitted the same generic ``upstream_error``
code, making the production first-fail boundary indistinguishable:

1. Core ``ExecutionRuntimeError(code="execution_failed")`` (unexpected internal
   failure wrapped by the product-neutral runtime) now maps to the distinct
   safe public code ``upstream_execution_failed``.
2. An unexpected non-``ChatRuntimeError`` exception raised in the route before
   the first visible delta now returns HTTP 502 with the distinct safe public
   code ``upstream_route_error``.

Every previously known mapping stays byte-identical, the unknown-code generic
fallthrough is preserved, and no raw exception message, class, or traceback
may ever reach the response body.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from padiem_ai_core import ExecutionRuntimeError, RunMetadata, RunStatus
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.b14_streaming import B14StreamEvent

from app.b14_client import ChatRuntimeError, _chat_error, _translate_execution_error
from app.config import Settings
from app.main import create_app

GENERIC_MESSAGE = "답변을 불러오지 못했습니다. 다시 시도해 주세요."
INTERNAL_SENTINEL = "raw-internal-failure-detail-must-never-leak"

KNOWN_MAPPINGS = (
    ("upstream_timeout", 504, "upstream_timeout"),
    ("upstream_rate_limited", 503, "upstream_busy"),
    ("upstream_response_too_large", 502, "upstream_response_too_large"),
    ("malformed_upstream", 502, "malformed_upstream"),
    ("empty_upstream_answer", 502, "malformed_upstream"),
    ("upstream_unavailable", 502, "upstream_unavailable"),
    ("invalid_execution_request", 422, "invalid_request"),
    ("upstream_auth_error", 502, "provider_auth_error"),
    ("upstream_request_error", 502, "provider_route_error"),
    ("upstream_server_error", 502, "provider_server_error"),
)


def _core_error(code: str, safe_message: str) -> ExecutionRuntimeError:
    metadata = RunMetadata(
        trace_id="tr_2550_taxonomy",
        app_id="padiem-chat",
        agent_id="b62-auto",
        status=RunStatus.FAILED,
    )
    return ExecutionRuntimeError(code, safe_message, metadata=metadata)


def _payload() -> dict:
    return {
        "messages": [{"role": "user", "content": "스트리밍으로 답해 주세요"}],
        "mode": "auto",
    }


def _event(content: str | None = None, *, done: bool = False) -> B14StreamEvent:
    return B14StreamEvent(
        model="secret/free-model",
        delta_content=content,
        route=B14RouteMetadata(route_mode="auto"),
        done=done,
    )


class ScriptedClient:
    def __init__(self, script):
        self.script = list(script)
        self.closed = False

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None):
        try:
            for item in self.script:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            self.closed = True


def _app_with_client(client) -> object:
    app = create_app(Settings(runtime_mode="mock"))
    app.state.b14_client = client
    app.state.usage_gate_enforced = False
    return app


async def _post(app) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.post("/api/chat/stream", json=_payload())


# ---------------------------------------------------------------------------
# 1. execution_failed -> distinct upstream_execution_failed
# ---------------------------------------------------------------------------


def test_execution_failed_maps_to_distinct_upstream_execution_failed():
    error = _chat_error("execution_failed")
    assert error.status_code == 502
    assert error.code == "upstream_execution_failed"
    assert error.code != "upstream_error"
    assert error.user_message == GENERIC_MESSAGE


def test_translate_execution_error_maps_core_execution_failed():
    error = _translate_execution_error(
        _core_error("execution_failed", "Model execution failed.")
    )
    assert error.status_code == 502
    assert error.code == "upstream_execution_failed"
    assert error.user_message == GENERIC_MESSAGE
    assert "Model execution failed" not in error.user_message


def test_route_prefers_distinct_execution_failed_code_before_sse():
    client = ScriptedClient(
        [ChatRuntimeError(502, "upstream_execution_failed", GENERIC_MESSAGE)]
    )
    response = asyncio.run(_post(_app_with_client(client)))

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "upstream_execution_failed"
    assert response.json()["error"]["message"] == GENERIC_MESSAGE
    assert "event:" not in response.text


# ---------------------------------------------------------------------------
# 2. existing known mappings: exact regression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("code", "status", "public_code"), KNOWN_MAPPINGS)
def test_known_mappings_exact_regression(code: str, status: int, public_code: str):
    error = _chat_error(code)
    assert error.status_code == status
    assert error.code == public_code


def test_generic_fallthrough_still_covers_unknown_codes():
    error = _chat_error("some_unseen_code")
    assert error.status_code == 502
    assert error.code == "upstream_error"
    assert error.user_message == GENERIC_MESSAGE


# ---------------------------------------------------------------------------
# 3. route-level unexpected exception before first visible delta
# ---------------------------------------------------------------------------


def test_route_unexpected_exception_before_first_delta_is_upstream_route_error():
    client = ScriptedClient([RuntimeError(INTERNAL_SENTINEL)])
    response = asyncio.run(_post(_app_with_client(client)))

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "upstream_route_error"
    assert response.json()["error"]["message"] == GENERIC_MESSAGE
    assert "event:" not in response.text


def test_route_unexpected_exception_emits_no_raw_detail_class_or_traceback():
    client = ScriptedClient([ValueError(INTERNAL_SENTINEL)])
    response = asyncio.run(_post(_app_with_client(client)))

    body = response.text
    assert INTERNAL_SENTINEL not in body
    assert "ValueError" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body


# ---------------------------------------------------------------------------
# 4. normal SSE success path unchanged
# ---------------------------------------------------------------------------


def test_normal_sse_success_path_unchanged():
    client = ScriptedClient([_event("첫째"), _event("둘째"), _event(done=True)])
    response = asyncio.run(_post(_app_with_client(client)))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: delta") == 2
    assert response.text.count("event: done") == 1
    assert "upstream_route_error" not in response.text
    assert "upstream_execution_failed" not in response.text
