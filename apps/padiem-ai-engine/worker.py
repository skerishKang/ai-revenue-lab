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
from padiem_ai_core.grounding_runtime import GroundedResearchRuntime
from padiem_ai_core.web_runtime import WebRuntimeConfig, create_web_provider

from app.agent_skill_service import (
    AGENT_SKILL_CANCEL_PATH,
    AGENT_SKILL_RESUME_PATH,
    AGENT_SKILL_RUN_PATH,
    AgentSkillEngineService,
)
from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.engine_composition import EngineServices
from app.idempotency_binding import CloudflareD1IdempotencyAdapter
from app.idempotency_replay_service import (
    IDEMPOTENCY_COMPLETED_REPLAY_PATH,
    IdempotencyReplayEngineService,
)
from app.identity_enforcement import authenticate_request
from app.memory_service import MEMORY_PATH, MEMORY_WRITE_PATH, MemoryRetrievalEngineService
from app.orchestration_service import (
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    ORCHESTRATION_STREAM_PATH,
    OrchestrationEngineService,
    PreparedOrchestrationStream,
)
from app.service import EngineService, HEALTH_PATH, ServiceResponse
from app.service_identity import ServiceIdentityError
from app.streaming_service import (
    NDJSON_CONTENT_TYPE,
    STREAM_PATH,
    PreparedStream,
    StreamingEngineService,
)
from app.tool_execution_service import ToolExecutionEngineService
from app.tool_projection import (
    TOOL_CANCEL_PATH,
    TOOL_EXECUTE_PATH,
    TOOL_RESUME_PATH,
)
from app.web_research_service import RESEARCH_PATH, WebResearchEngineService

B14_SERVICE_BINDING_NAME = "B14_SERVICE"
ENGINE_IDEMPOTENCY_BINDING_NAME = "ENGINE_IDEMPOTENCY"
ENGINE_WEB_PROVIDER_ENV = "PADIEM_ENGINE_WEB_PROVIDER"
ENGINE_FIRECRAWL_API_KEY_ENV = "PADIEM_ENGINE_FIRECRAWL_API_KEY"
ENGINE_DAUM_REST_API_KEY_ENV = "PADIEM_ENGINE_DAUM_REST_API_KEY"
ENGINE_DAUM_SEARCH_SORT_ENV = "PADIEM_ENGINE_DAUM_SEARCH_SORT"
ENGINE_WEB_TIMEOUT_SECONDS_ENV = "PADIEM_ENGINE_WEB_TIMEOUT_SECONDS"
# #1990: the B14 transport timeout must cover B14's full retry chain
# (#1988: 45s hard cap + ~1.5s backoff overhead). Default 50s = 45s retry
# cap + 5s margin; the engine orchestration budget is 60s, leaving 10s.
# Core enforces the 1-60s bound on B14ExecutionConfig.timeout_seconds.
ENGINE_B14_TIMEOUT_SECONDS_ENV = "PADIEM_ENGINE_B14_TIMEOUT_SECONDS"
B14_TIMEOUT_DEFAULT_SECONDS = 50.0


def _binding_value(env: Any, name: str) -> Any | None:
    try:
        return getattr(env, name)
    except (AttributeError, TypeError):
        return None


def _env_text(env: Any, name: str) -> str | None:
    value = _binding_value(env, name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _b14_timeout_seconds_for_env(env: Any) -> float:
    """B14 transport timeout (seconds), env-tunable via a plain Worker var.

    Default 50.0 (#1990). Values outside Core's 1-60 bound fail closed in
    B14ExecutionConfig itself; this helper only parses, never clamps.
    """

    raw = _env_text(env, ENGINE_B14_TIMEOUT_SECONDS_ENV)
    return B14_TIMEOUT_DEFAULT_SECONDS if raw is None else float(raw)


def _web_runtime_config_for_env(env: Any) -> WebRuntimeConfig:
    """Build Core web configuration from server-only deployment state.

    The request wire has no provider, endpoint, credential or research-budget
    fields. Callers therefore cannot select or mint web-provider authority.
    """

    timeout_raw = _env_text(env, ENGINE_WEB_TIMEOUT_SECONDS_ENV)
    timeout = 15.0 if timeout_raw is None else float(timeout_raw)
    return WebRuntimeConfig(
        provider=_env_text(env, ENGINE_WEB_PROVIDER_ENV) or "off",
        firecrawl_api_key=_env_text(env, ENGINE_FIRECRAWL_API_KEY_ENV),
        daum_rest_api_key=_env_text(env, ENGINE_DAUM_REST_API_KEY_ENV),
        daum_search_sort=_env_text(env, ENGINE_DAUM_SEARCH_SORT_ENV) or "accuracy",
        web_timeout_seconds=timeout,
    )


def _idempotency_adapter_for_env(env: Any) -> CloudflareD1IdempotencyAdapter | None:
    """Return the trusted durable idempotency adapter when explicitly bound.

    Absence is intentional: Core then keeps keyed orchestration fail-closed as
    `idempotency_unavailable`. This Worker must not install a process-local fake
    store as production truth.
    """

    binding = _binding_value(env, ENGINE_IDEMPOTENCY_BINDING_NAME)
    if binding is None:
        return None
    return CloudflareD1IdempotencyAdapter(binding)


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


def _memory_service_for_env(env: Any) -> MemoryRetrievalEngineService:
    """Compose the memory read/write projection from server-only deployment state.

    Trusted memory bindings (read authorization + retrieval provider, and the
    separate write authorization + policy + classifier + idempotent adapter)
    are deployment/code authority and are registered outside this Worker in
    this slice. Their absence is intentional: each route fails closed as
    `memory_binding_unavailable` / `memory_write_binding_unavailable`, and the
    request wire can never substitute a storage endpoint, provider, adapter or
    credential for the missing authority. Read and write registries stay
    separate: binding one never enables the other.
    """

    return MemoryRetrievalEngineService(bindings={}, write_bindings={})


async def _engine_services_for_env(env: Any) -> EngineServices:
    binding = _binding_value(env, B14_SERVICE_BINDING_NAME)
    if binding is None:
        unavailable_factory = lambda app_id: (_ for _ in ()).throw(  # noqa: E731
            RuntimeError("unreachable without B14 service binding")
        )
        return EngineServices(
            completed=EngineService(
                runtime_factory=unavailable_factory,
                b14_service_bound=False,
            ),
            streaming=StreamingEngineService(
                runtime_factory=unavailable_factory,
                b14_service_bound=False,
            ),
            orchestration=OrchestrationEngineService(
                runtime_factory=unavailable_factory,
                b14_service_bound=False,
            ),
            research=WebResearchEngineService(
                research_runtime_factory=unavailable_factory,
                execution_runtime_factory=unavailable_factory,
                b14_service_bound=False,
            ),
            memory=_memory_service_for_env(env),
            # Agent/Skill source routes remain production-unactivated. Without
            # trusted resolver/store/verifier they fail closed.
            agent_skill=AgentSkillEngineService(
                runtime_factory=unavailable_factory,
                binding_resolver=None,
            ),
            # ACT-2 route admission: the Tool routes are wired, but this
            # composition carries an explicitly unconfigured resolver (no
            # trusted Gmail port or grant store here). Every request fails
            # closed as 503 `tool_runtime_unavailable` with zero provider
            # calls; the canonical entrypoint composes the real resolver.
            tool_execution=ToolExecutionEngineService(tool_binding_resolver=None),
        )

    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=Request,
    )
    config = B14ExecutionConfig(
        base_url=B14_INTERNAL_ORIGIN,
        timeout_seconds=_b14_timeout_seconds_for_env(env),
    )
    b14_client = B14ExecutionClient(config, transport=transport)
    b14_stream_client = B14StreamingClient(config, transport=transport)
    idempotency_adapter = _idempotency_adapter_for_env(env)

    def runtime_factory(app_id: str) -> ExecutionRuntime:
        return ExecutionRuntime(app_id=app_id, b14_client=b14_client)

    def streaming_runtime_factory(app_id: str) -> StreamingExecutionRuntime:
        return StreamingExecutionRuntime(
            app_id=app_id,
            b14_stream_client=b14_stream_client,
        )

    def research_runtime_factory(_app_id: str) -> GroundedResearchRuntime:
        return GroundedResearchRuntime(
            create_web_provider(_web_runtime_config_for_env(env))
        )

    return EngineServices(
        completed=EngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
        ),
        streaming=StreamingEngineService(
            runtime_factory=streaming_runtime_factory,
            b14_service_bound=True,
        ),
        orchestration=OrchestrationEngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
            idempotency_adapter=idempotency_adapter,
        ),
        research=WebResearchEngineService(
            research_runtime_factory=research_runtime_factory,
            execution_runtime_factory=runtime_factory,
            b14_service_bound=True,
        ),
        memory=_memory_service_for_env(env),
        agent_skill=AgentSkillEngineService(
            runtime_factory=runtime_factory,
            # Trusted registry/session/entitlement and continuation authority
            # remain later Production gates (#1751/#1753).
            binding_resolver=None,
            idempotency_adapter=idempotency_adapter,
        ),
        # #1964 source slice: replay composes only the same trusted durable
        # adapter as execution; without it the route fails closed (503).
        idempotency_replay=IdempotencyReplayEngineService(
            idempotency_adapter=idempotency_adapter,
        ),
        # Same explicit unconfigured-resolver slot as the unbound branch:
        # B14 binding presence never implies a Gmail tool authority.
        tool_execution=ToolExecutionEngineService(tool_binding_resolver=None),
    )


def _ndjson_response(
    service: StreamingEngineService | OrchestrationEngineService,
    prepared: PreparedStream | PreparedOrchestrationStream,
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
    engine_services_factory = staticmethod(_engine_services_for_env)

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

        orchestration_paths = {
            ORCHESTRATE_PATH,
            ORCHESTRATE_RESUME_PATH,
            ORCHESTRATE_CANCEL_PATH,
            ORCHESTRATION_STREAM_PATH,
        }
        idempotency_paths = {
            IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        }
        agent_skill_paths = {
            AGENT_SKILL_RUN_PATH,
            AGENT_SKILL_RESUME_PATH,
            AGENT_SKILL_CANCEL_PATH,
        }
        tool_paths = {
            TOOL_EXECUTE_PATH,
            TOOL_RESUME_PATH,
            TOOL_CANCEL_PATH,
        }
        allowed_paths = {
            HEALTH_PATH,
            STREAM_PATH,
            "/internal/v1/execute",
            RESEARCH_PATH,
            MEMORY_PATH,
            MEMORY_WRITE_PATH,
        } | orchestration_paths | agent_skill_paths | idempotency_paths | tool_paths
        if path not in allowed_paths:
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

        services = await self.engine_services_factory(self.env)

        if path == ORCHESTRATION_STREAM_PATH:
            prepared = await services.orchestration.prepare_stream(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            if isinstance(prepared, ServiceResponse):
                return _json_response(prepared)
            return _ndjson_response(services.orchestration, prepared)

        if path in orchestration_paths:
            result = await services.orchestration.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

        if path in idempotency_paths:
            # services.idempotency_replay is None only in the unbound
            # composition; replay itself still fails closed inside the service.
            if services.idempotency_replay is None:
                return _error_response(
                    "idempotency_unavailable",
                    "Trusted durable idempotency authority is unavailable.",
                    503,
                )
            result = await services.idempotency_replay.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

        if path in agent_skill_paths:
            if services.agent_skill is None:
                return _error_response(
                    "agent_skill_runtime_unavailable",
                    "Trusted Agent/Skill runtime authority is unavailable.",
                    503,
                )
            result = await services.agent_skill.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

        if path in tool_paths:
            # ACT-2 route admission. The shared composition always carries an
            # explicitly unconfigured resolver, so the service itself answers
            # 503 `tool_runtime_unavailable`; this guard covers a foreign
            # composition shape with the same machine-readable fail-closed.
            if services.tool_execution is None:
                return _error_response(
                    "tool_runtime_unavailable",
                    "The Engine Tool runtime is not provisioned for this deployment.",
                    503,
                )
            result = await services.tool_execution.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

        if path == RESEARCH_PATH:
            result = await services.research.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

        if path in (MEMORY_PATH, MEMORY_WRITE_PATH):
            result = await services.memory.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            return _json_response(result)

        if path == STREAM_PATH:
            prepared = await services.streaming.prepare(
                method=method,
                path=path,
                content_type=content_type,
                body=body,
            )
            if isinstance(prepared, ServiceResponse):
                return _json_response(prepared)
            return _ndjson_response(services.streaming, prepared)

        result = await services.completed.handle(
            method=method,
            path=path,
            content_type=content_type,
            body=body,
        )
        if path == HEALTH_PATH and result.status_code == 200:
            health = dict(result.body)
            health["service_identity"] = "required_for_all_non_health_routes"
            caps = health.get("capabilities")
            if isinstance(caps, dict):
                if "completed_run" in caps:
                    health["completed_run"] = caps["completed_run"] == "available"
                if "provider_streaming_run" in caps:
                    health["streaming_run"] = caps["provider_streaming_run"] == "available"
                if "orchestration_run" in caps:
                    health["orchestration_run"] = caps["orchestration_run"] == "available"
            result = ServiceResponse(status_code=200, body=health)
        return _json_response(result)
