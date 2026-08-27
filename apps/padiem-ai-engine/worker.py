"""Cloudflare Python Worker entrypoint for the internal Padiem AI Engine.

The Worker is intentionally Service-Binding-only (`workers_dev = false`).  It
contains the Cloudflare adapter while all execution semantics stay in the
shared Padiem AI Core.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from workers import Request, Response, WorkerEntrypoint

from padiem_ai_core import B14ExecutionClient, B14ExecutionConfig, ExecutionRuntime

from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.service import EngineService, ServiceResponse

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


def _service_for_env(env: Any) -> EngineService:
    binding = _binding_value(env, B14_SERVICE_BINDING_NAME)
    if binding is None:
        return EngineService(
            runtime_factory=lambda app_id: (_ for _ in ()).throw(
                RuntimeError("unreachable without B14 service binding")
            ),
            b14_service_bound=False,
        )

    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=Request,
    )
    b14_client = B14ExecutionClient(
        B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN),
        transport=transport,
    )

    def runtime_factory(app_id: str) -> ExecutionRuntime:
        return ExecutionRuntime(app_id=app_id, b14_client=b14_client)

    return EngineService(
        runtime_factory=runtime_factory,
        b14_service_bound=True,
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

        service = _service_for_env(self.env)
        result = await service.handle(
            method=method,
            path=path,
            content_type=content_type,
            body=body,
        )
        return _json_response(result)
