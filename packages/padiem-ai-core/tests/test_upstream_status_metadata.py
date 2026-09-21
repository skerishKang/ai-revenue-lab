"""B14 upstream HTTP status preservation into public error metadata (#1971).

The B14 upstream status must survive the Core -> Engine error chain and be
exposed exactly at ``error.metadata.upstream_status_code``. It must never become
a sibling key on the error object, never be invented for local failures, and
never carry provider identity, tokens or upstream bodies.
"""

from __future__ import annotations

import pytest

from padiem_ai_core.b14_execution import B14ExecutionError
from padiem_ai_core.contracts import ErrorClass, RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionRuntime, ExecutionRuntimeError
from padiem_ai_core.streaming_runtime import StreamingExecutionRuntime
from padiem_ai_core.multimodal_execution_runtime import MultimodalExecutionRuntime

from test_execution_runtime import FakeExecutor as ExecutionExecutor
from test_execution_runtime import agent as execution_agent
from test_execution_runtime import request as execution_request
from test_execution_runtime import run
from test_multimodal_execution_runtime import FakeExecutor as MultimodalExecutor
from test_multimodal_execution_runtime import agent as multimodal_agent
from test_multimodal_execution_runtime import request as multimodal_request
from test_streaming_runtime import FakeStreamClient
from test_streaming_runtime import agent as streaming_agent
from test_streaming_runtime import request as streaming_request


def _upstream_error(status: int | None, *, retryable: bool = True) -> B14ExecutionError:
    return B14ExecutionError(
        "b14_upstream_error",
        "Business 14 upstream failed.",
        upstream_status_code=status,
        retryable=retryable,
    )


def _metadata() -> RunMetadata:
    return RunMetadata(
        trace_id="trace-1",
        app_id="test-app",
        agent_id="agent-1",
        status=RunStatus.FAILED,
        error_class=ErrorClass.PROVIDER_BAD_RESPONSE,
    )


def test_execution_runtime_preserves_b14_5xx_status_into_error_metadata() -> None:
    runtime = ExecutionRuntime(
        app_id="test-app", b14_client=ExecutionExecutor(error=_upstream_error(503))
    )

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(execution_request()))

    error = info.value
    assert error.upstream_status_code == 503
    public = error.to_public_dict()
    assert public["metadata"]["upstream_status_code"] == 503
    # No sibling key on the error object.
    assert "upstream_status_code" not in public
    assert set(public) == {"code", "message", "retryable", "metadata"}
    assert error.retryable is True
    # Existing metadata contract is preserved alongside the new entry.
    assert public["metadata"]["error_class"] == error.metadata.error_class.value
    assert public["metadata"]["error_class"] is not None


def test_streaming_runtime_preserves_b14_5xx_status_into_error_metadata() -> None:
    client = FakeStreamClient(error=_upstream_error(502))
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        async def _consume() -> None:
            async for _ in runtime.stream(streaming_request()):
                pass

        run(_consume())

    assert info.value.upstream_status_code == 502
    assert info.value.error_metadata()["upstream_status_code"] == 502


def test_multimodal_runtime_preserves_b14_5xx_status_into_error_metadata() -> None:
    runtime = MultimodalExecutionRuntime(
        app_id="test-app", b14_client=MultimodalExecutor(error=_upstream_error(504))
    )

    with pytest.raises(ExecutionRuntimeError) as info:
        run(runtime.run(multimodal_request()))

    assert info.value.upstream_status_code == 504
    assert info.value.error_metadata()["upstream_status_code"] == 504


def test_absent_upstream_status_is_never_invented() -> None:
    error = ExecutionRuntimeError(
        "execution_failed", "Model execution failed.", metadata=_metadata()
    )

    assert error.upstream_status_code is None
    metadata = error.error_metadata()
    assert "upstream_status_code" not in metadata
    assert metadata["status"] == RunStatus.FAILED.value


@pytest.mark.parametrize("value", [True, False, "503", 99, 600, 3.5, None])
def test_malformed_upstream_status_is_dropped(value: object) -> None:
    error = ExecutionRuntimeError(
        "b14_upstream_error",
        "Business 14 upstream failed.",
        metadata=_metadata(),
        upstream_status_code=value,  # type: ignore[arg-type]
    )

    assert error.upstream_status_code is None
    assert "upstream_status_code" not in error.error_metadata()
    assert "upstream_status_code" not in error.to_public_dict()["metadata"]


@pytest.mark.parametrize("status", [400, 401, 429, 500, 502, 503, 504, 599])
def test_in_range_upstream_statuses_are_preserved_verbatim(status: int) -> None:
    error = ExecutionRuntimeError(
        "b14_upstream_error",
        "Business 14 upstream failed.",
        metadata=_metadata(),
        upstream_status_code=status,
    )

    assert error.upstream_status_code == status
    assert type(error.upstream_status_code) is int


def test_error_metadata_never_carries_provider_or_credential_material() -> None:
    error = ExecutionRuntimeError(
        "b14_upstream_error",
        "Business 14 upstream failed.",
        metadata=_metadata(),
        upstream_status_code=503,
    )

    rendered = repr(error.to_public_dict())
    for forbidden in (
        "openrouter",
        "Authorization",
        "Bearer",
        "api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "credential",
        "https://",
        "upstream body",
    ):
        assert forbidden not in rendered
