"""Engine error envelope carries B14 upstream status under error.metadata (#1971).

Verifies the public location is exactly ``error.metadata.upstream_status_code``
for both the non-streaming response and the streaming error line, with no sibling
key, no provider material, and no invented status for local failures.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from padiem_ai_core import ExecutionRuntimeError
from padiem_ai_core.contracts import ErrorClass, RunMetadata, RunStatus

from app.service import EngineService
from app.streaming_service import StreamingEngineService, _runtime_error_response

from test_service import FakeRuntime, RuntimeFactory, valid_payload
from test_streaming_service import FakeRuntime as StreamingFakeRuntime
from test_streaming_service import STREAM_PATH
from test_streaming_service import progress as stream_progress


def _error(status: int | None) -> ExecutionRuntimeError:
    return ExecutionRuntimeError(
        "upstream_timeout",
        "safe core message",
        retryable=True,
        metadata=RunMetadata(
            trace_id="trace-1",
            app_id="lovebud",
            agent_id="relationship-coach",
            session_id="session-1",
            status=RunStatus.TIMEOUT,
            error_class=ErrorClass.PROVIDER_TIMEOUT,
        ),
        upstream_status_code=status,
    )


@pytest.mark.asyncio
async def test_non_streaming_error_response_exposes_upstream_status_in_metadata() -> None:
    service = EngineService(
        runtime_factory=RuntimeFactory(FakeRuntime(error=_error(502))),
        b14_service_bound=True,
    )

    response = await service.execute_payload(valid_payload())

    assert response.status_code != 200
    assert response.body["error"]["metadata"]["upstream_status_code"] == 502
    # No sibling key on the error object, and the existing contract is intact.
    assert "upstream_status_code" not in response.body["error"]
    assert response.body["error"]["metadata"]["error_class"] == "provider_timeout"


def test_streaming_runtime_error_response_exposes_upstream_status_in_metadata() -> None:
    response = _runtime_error_response(_error(503))

    assert response.body["error"]["metadata"]["upstream_status_code"] == 503
    assert "upstream_status_code" not in response.body["error"]
    assert response.body["error"]["code"] == "upstream_timeout"


@pytest.mark.asyncio
async def test_streaming_immediate_error_exposes_upstream_status_in_metadata() -> None:
    """A first-event B14 error projects the status into the prepare error body."""

    runtime = StreamingFakeRuntime(error=_error(504))
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime, b14_service_bound=True
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json; charset=utf-8",
        body=json.dumps(valid_payload(), ensure_ascii=False).encode(),
    )

    assert prepared.status_code == 504
    assert prepared.body["error"]["metadata"]["upstream_status_code"] == 504
    assert "upstream_status_code" not in prepared.body["error"]


@pytest.mark.asyncio
async def test_streaming_error_line_exposes_upstream_status_in_metadata() -> None:
    runtime = StreamingFakeRuntime(events=[stream_progress()], error=_error(503))
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime, b14_service_bound=True
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json; charset=utf-8",
        body=json.dumps(valid_payload(), ensure_ascii=False).encode(),
    )
    lines = [line async for line in service.iter_ndjson(prepared)]

    error_lines = [json.loads(line) for line in lines if '"ok":false' in line.replace(" ", "")]
    assert error_lines, lines
    payload = error_lines[-1]
    assert payload["error"]["metadata"]["upstream_status_code"] == 503
    assert "upstream_status_code" not in payload["error"]


@pytest.mark.asyncio
async def test_local_failure_never_invents_an_upstream_status() -> None:
    service = EngineService(
        runtime_factory=RuntimeFactory(FakeRuntime(error=_error(None))),
        b14_service_bound=True,
    )

    response = await service.execute_payload(valid_payload())

    assert "upstream_status_code" not in response.body["error"]["metadata"]
    assert "upstream_status_code" not in response.body["error"]
    streaming_metadata = _runtime_error_response(_error(None)).body["error"]["metadata"]
    assert "upstream_status_code" not in streaming_metadata


@pytest.mark.asyncio
async def test_error_metadata_carries_no_provider_or_credential_material() -> None:
    service = EngineService(
        runtime_factory=RuntimeFactory(FakeRuntime(error=_error(503))),
        b14_service_bound=True,
    )

    response = await service.execute_payload(valid_payload())
    rendered = json.dumps(response.body, ensure_ascii=False, sort_keys=True)

    for forbidden in (
        "openrouter",
        "Authorization",
        "Bearer",
        "api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "https://",
    ):
        assert forbidden not in rendered
