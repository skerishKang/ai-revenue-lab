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
from app.identity_enforcement import authenticate_request
from app.orchestration_service import (
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    OrchestrationEngineService,
)
from app.service import EngineService, HEALTH_PATH, ServiceResponse
from app.service_identity import ServiceIdentityError
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


def _error_response(code: str, message: str, status_code: int) -> Response:
    return _json_response(
        ServiceResponse(
            status_code=status_code,
            body={
                "ok": False,
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": False,
                    "metadata": None,
                },
            },
        )
    )


def _read_requested_app_id(body: bytes) -> str | None:
    """Read only the app_id needed for caller binding, without executing Core."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    app_id = payload.get("app_id")
    return app_id if isinstance(app_id, str) else None


def _authenticate_non_health_request(env: Any, headers: Any, body: bytes) -> Response | None:
    app_id = _read_requested_app_id(body)
    if app_id is None:
        return _error_response(
            "service_authentication_failed",
            "Engine caller authentication failed.",
            401,
        )
    try:
        authenticate_request(env=env, headers=headers, requested_app_id=app_id)
    except ServiceIdentityError as exc:
        if exc.code in {"service_identity_unavailable", "service_identity_misconfigured"}:
            return _error_response(
                "service_identity_unavailable",
                "Padiem AI Engine service identity is unavailable.",
                503,
            )
        if exc.code == "service_app_not_authorized":
            return _error_response(
                "service_app_not_authorized",
                "Engine caller is not authorized for the requested application.",
                403,
            )
        return _error_response(
            "service_authentication_failed",
            "Engine caller authentication failed.",
            401,
        )
    return None


def _engine_services_for_env(
    env: Any,
) -> tuple[EngineService, StreamingEngineService, OrchestrationEngineService]:
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
        orchestration = OrchestrationEngineService(
            runtime_factory=lambda app_id: (_ for _ in ()).throw(
                RuntimeError("unreachable without B14 service binding")
            ),
            b14_service_bound=False,
        )
        return completed, streaming, orchestration

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
        OrchestrationEngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
        ),
    )


def _ndjson_response(
    service: StreamingEngineService,
    prepared: PreparedStream,
) -> Response:
    """Expose one Core event per pull through a Worker ReadableStream."""

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

        orchestration_paths = {ORCHESTRATE_PATH, ORCHESTRATE_RESUME_PATH, ORCHESTRATE_CANCEL_PATH}
        if path not in {HEALTH_PATH, STREAM_PATH, "/internal/v1/execute"} | orchestration_paths:
            result = ServiceResponse(
                status_code=404,
                body={
                    "ok": False,
                    "error": {
                        "code": "not_found",
                        "message": "Internal Engine route not found.",
                        "retryable": False,
                        "metadata": None,
                    },
                },
            )
            return _json_response(result)

        if path != HEALTH_PATH:
            auth_error = _authenticate_non_health_request(self.env, headers, body)
            if auth_error is not None:
                return auth_error

        completed_service, streaming_service, orchestration_service = _engine_services_for_env(self.env)

        if path in orchestration_paths:
            result = await orchestration_service.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

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
            health["orchestration_run"] = True
            health["service_identity"] = "required_for_execute_and_stream"
            result = ServiceResponse(status_code=200, body=health)
        return _json_response(result)
