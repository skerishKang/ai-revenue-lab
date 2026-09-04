"""Cloudflare Worker entrypoint with identity-bound Engine composition.

All existing transport/auth/streaming behavior remains in ``worker.py``. This
canonical composition root adds the E5 trusted multimodal reference route while
preserving the explicit named service bundle introduced by #1792. The route is
source-wired but remains fail-closed until a trusted attachment resolver is
injected by a later Production activation gate.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import worker as legacy_worker
from padiem_ai_core import (
    B14ExecutionClient,
    B14ExecutionConfig,
    B14StreamingClient,
    ExecutionRuntime,
    StreamingExecutionRuntime,
)
from padiem_ai_core.grounding_runtime import GroundedResearchRuntime
from padiem_ai_core.multimodal_execution_runtime import MultimodalExecutionRuntime
from padiem_ai_core.web_runtime import create_web_provider
from workers import Request

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.engine_composition import EngineServices
from app.multimodal_attachment_service import (
    MULTIMODAL_EXECUTE_PATH,
    MultimodalAttachmentEngineService,
)
from app.orchestration_idempotency_service import CanonicalIdempotencyOrchestrationEngineService
from app.service import EngineService, ServiceResponse
from app.streaming_service import StreamingEngineService
from app.web_research_service import WebResearchEngineService

ENGINE_CONTINUATION_BINDING_NAME = "ENGINE_CONTINUATION"


def _continuation_store_for_env(env: Any) -> CloudflareD1IdentityBoundContinuationStore | None:
    """Resolve the explicit durable continuation authority; never fake Production state."""
    binding = legacy_worker._binding_value(env, ENGINE_CONTINUATION_BINDING_NAME)
    if binding is None:
        return None
    try:
        return CloudflareD1IdentityBoundContinuationStore(binding)
    except (TypeError, ValueError):
        return None


def _research_service_for_env(
    env: Any,
    execution_runtime_factory: Any,
    *,
    b14_service_bound: bool,
) -> WebResearchEngineService:
    def research_runtime_factory(_app_id: str) -> GroundedResearchRuntime:
        return GroundedResearchRuntime(
            create_web_provider(legacy_worker._web_runtime_config_for_env(env))
        )

    return WebResearchEngineService(
        research_runtime_factory=research_runtime_factory,
        execution_runtime_factory=execution_runtime_factory,
        b14_service_bound=b14_service_bound,
    )


def _engine_services_for_env(env: Any) -> EngineServices:
    binding = legacy_worker._binding_value(env, legacy_worker.B14_SERVICE_BINDING_NAME)
    if binding is None:
        unavailable = lambda app_id: (_ for _ in ()).throw(
            RuntimeError("unreachable without B14 service binding")
        )
        return EngineServices(
            completed=EngineService(runtime_factory=unavailable, b14_service_bound=False),
            streaming=StreamingEngineService(runtime_factory=unavailable, b14_service_bound=False),
            orchestration=CanonicalIdempotencyOrchestrationEngineService(
                runtime_factory=unavailable,
                b14_service_bound=False,
            ),
            research=_research_service_for_env(
                env,
                unavailable,
                b14_service_bound=False,
            ),
            memory=legacy_worker._memory_service_for_env(env),
            multimodal=MultimodalAttachmentEngineService(
                runtime_factory=unavailable,
                attachment_resolver=None,
            ),
        )

    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=Request,
    )
    config = B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN)
    b14_client = B14ExecutionClient(config, transport=transport)
    b14_stream_client = B14StreamingClient(config, transport=transport)
    continuation_store = _continuation_store_for_env(env)
    idempotency_adapter = legacy_worker._idempotency_adapter_for_env(env)

    def runtime_factory(app_id: str) -> ExecutionRuntime:
        return ExecutionRuntime(app_id=app_id, b14_client=b14_client)

    def streaming_runtime_factory(app_id: str) -> StreamingExecutionRuntime:
        return StreamingExecutionRuntime(
            app_id=app_id,
            b14_stream_client=b14_stream_client,
        )

    def multimodal_runtime_factory(app_id: str) -> MultimodalExecutionRuntime:
        return MultimodalExecutionRuntime(app_id=app_id, b14_client=b14_client)

    return EngineServices(
        completed=EngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
        ),
        streaming=StreamingEngineService(
            runtime_factory=streaming_runtime_factory,
            b14_service_bound=True,
        ),
        orchestration=CanonicalIdempotencyOrchestrationEngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
            idempotency_adapter=idempotency_adapter,
            continuation_store=continuation_store,
            approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        ),
        research=_research_service_for_env(
            env,
            runtime_factory,
            b14_service_bound=True,
        ),
        memory=legacy_worker._memory_service_for_env(env),
        multimodal=MultimodalAttachmentEngineService(
            runtime_factory=multimodal_runtime_factory,
            # E5A source seam only. A deployment-owned resolver that proves
            # app/tenant/subject scope is a later Production activation gate.
            attachment_resolver=None,
        ),
    )


class Default(legacy_worker.Default):
    """Canonical Worker entrypoint with one additional E5 source route.

    Existing routes remain inherited unchanged. The multimodal route repeats
    only the same body-read/service-auth boundary before invoking its named
    service; no storage resolver or alternate authentication mechanism lives
    here.
    """

    engine_services_factory = staticmethod(_engine_services_for_env)

    async def fetch(self, request: Any) -> Any:
        path = urlparse(str(request.url)).path
        if path != MULTIMODAL_EXECUTE_PATH:
            return await super().fetch(request)

        method = str(getattr(request, "method", ""))
        headers = getattr(request, "headers", None)
        content_type = headers.get("content-type") if headers is not None else None

        body = b""
        if method.upper() == "POST":
            try:
                text = await request.text()
                body = str(text).encode("utf-8")
            except Exception:
                return legacy_worker._json_response(
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

        auth_error = legacy_worker._authenticate_non_health_request(
            self.env,
            headers,
            body,
        )
        if auth_error is not None:
            return auth_error

        services = self.engine_services_factory(self.env)
        if services.multimodal is None:
            return legacy_worker._error_response(
                "attachment_resolver_unavailable",
                "Trusted attachment resolver is unavailable.",
                503,
            )
        result = await services.multimodal.handle(
            method=method,
            path=path,
            content_type=content_type,
            body=body,
        )
        return legacy_worker._json_response(result)
