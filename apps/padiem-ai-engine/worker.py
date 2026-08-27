"""Cloudflare Python Worker entrypoint for the internal Padiem AI Engine.

The Worker is intentionally Service-Binding-only (`workers_dev = false`). It
contains the Cloudflare adapter while all execution semantics stay in the
shared Padiem AI Core.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from workers import Request, Response, WorkerEntrypoint

from padiem_ai_core import (
    B14ExecutionClient,
    B14ExecutionConfig,
    B14StreamingClient,
    ExecutionRuntime,
    StreamingExecutionRuntime,
)

from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.service import EngineService, HEALTH_PATH, ServiceResponse
from app.streaming_service import (
    NDJSON_CONTENT_TYPE,
    STREAM_PATH,
    PreparedStream,
    StreamingEngineService,
)

B14_SERVICE_BINDING_NAME = "B14_SERVICE"


def _binding_value(env: Any, name: str) -> Any | None:
    try:
        return getattr(env, name)
    except (AttributeError, TypeError):
        return None


def _json_response(result: ServiceResponse) -> Response:
    return Response(
        json.dumps(
            dict(result.body),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        status=result.status_code,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
        },
    )


def _engine_services_for_env(
    env: Any,
) -> tuple[EngineService, StreamingEngineService]:
    binding = _binding_value(env, B14_SERVICE_BINDING_NAME)
    if binding is None:
        completed = EngineService(
            runtime_factory=lambda app_id: (_ for _ in ()).throw(
                RuntimeError("unreachable without B14 service binding")
            ),
            b14_service_bound=False,
        )
        streaming = StreamingEngineService(
            runtime_factory=lambda app_id: (_ for _ in ()).throw(
                RuntimeError("unreachable without B14 service binding")
            ),
            b14_service_bound=False,
        )
        return completed, streaming

    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=Request,
    )
    config = B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN)
    b14_client = B14ExecutionClient(config, transport=transport)
    b14_stream_client = B14StreamingClient(config, transport=transport)

    def runtime_factory(app_id: str) -> ExecutionRuntime:
        return ExecutionRuntime(app_id=app_id, b14_client=b14_client)

    def streaming_runtime_factory(app_id: str) -> StreamingExecutionRuntime:
        return StreamingExecutionRuntime(
            app_id=app_id,
            b14_stream_client=b14_stream_client,
        )

    return (
        EngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
        ),
        StreamingEngineService(
            runtime_factory=streaming_runtime_factory,
            b14_service_bound=True,
        ),
    )


def _ndjson_response(
    service: StreamingEngineService,
    prepared: PreparedStream,
) -> Response:
    """Expose one Core event per pull through a Worker ReadableStream."""

    # Streams are a request-context JavaScript API in Python Workers, so keep
    # the FFI imports and construction inside the active fetch invocation.
    from js import ReadableStream, TextEncoder
    from pyodide.ffi import create_proxy, to_js

    encoder = TextEncoder.new()
    lines = service.iter_ndjson(prepared)
    finished = False

    async def _close_lines() -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        close = getattr(lines, "aclose", None)
        if callable(close):
            try:
                await close()
            except Exception:
                pass

    async def pull(controller: Any) -> None:
        nonlocal finished
        if finished:
            controller.close()
            return
        try:
            line = await anext(lines)
        except StopAsyncIteration:
            finished = True
            controller.close()
            return
        except Exception:
            # iter_ndjson already converts execution failures to a bounded
            # terminal line. This is only an adapter-level last resort.
            await _close_lines()
            controller.error("Padiem AI Engine stream adapter failed.")
            return
        controller.enqueue(encoder.encode(line))

    async def cancel(_reason: Any = None) -> None:
        await _close_lines()

    stream = ReadableStream.new(
        to_js(
            {
                "pull": create_proxy(pull),
                "cancel": create_proxy(cancel),
            }
        )
    )
    return Response(
        stream,
        status=200,
        headers={
            "Content-Type": NDJSON_CONTENT_TYPE,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        path = urlparse(str(request.url)).path
        method = str(getattr(request, "method", ""))
        headers = getattr(request, "headers", None)
        content_type = headers.get("content-type") if headers is not None else None

        body = b""
        if method.upper() == "POST":
            try:
                text = await request.text()
                body = str(text).encode("utf-8")
            except Exception:
                return _json_response(
                    ServiceResponse(
                        status_code=400,
                        body={
                            "ok": False,
                            "error": {
                                "code": "invalid_request",
                                "message": "Request body could not be read.",
                                "retryable": False,
                                "metadata": None,
                            },
                        },
                    )
                )

        completed_service, streaming_service = _engine_services_for_env(self.env)

        if path == STREAM_PATH:
            prepared = await streaming_service.prepare(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            if isinstance(prepared, ServiceResponse):
                return _json_response(prepared)
            return _ndjson_response(streaming_service, prepared)

        result = await completed_service.handle(
            method=method,
            path=path,
            content_type=content_type,
            body=body,
        )
        if path == HEALTH_PATH and result.status_code == 200:
            health = dict(result.body)
            health["streaming_run"] = True
            result = ServiceResponse(status_code=200, body=health)
        return _json_response(result)
