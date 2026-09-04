"""Cloudflare Worker entrypoint with identity-bound orchestration continuation wiring.

All transport/auth/streaming behavior remains in the existing worker module. This
canonical composition root supplies the identity-bound service bundle through an
explicit named composition seam: it subclasses the shared ``Default`` entrypoint
and overrides ``engine_services_factory`` so approval resumes and durable
idempotency use the canonical logical-execution identity contract, while every
Engine route family (completed, streaming, orchestration, research) stays
addressable by name with no positional-tuple contract between modules.
"""

from __future__ import annotations

from typing import Any

import worker as legacy_worker
from padiem_ai_core import (
    B14ExecutionClient,
    B14ExecutionConfig,
    B14StreamingClient,
    ExecutionRuntime,
    StreamingExecutionRuntime,
)
from padiem_ai_core.grounding_runtime import GroundedResearchRuntime
from padiem_ai_core.web_runtime import create_web_provider
from workers import Request

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.engine_composition import EngineServices
from app.orchestration_idempotency_service import CanonicalIdempotencyOrchestrationEngineService
from app.service import EngineService
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
        # Core validates provider/key/timeout configuration. Provider selection
        # is deployment authority only and cannot be supplied by the request.
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
    )


class Default(legacy_worker.Default):
    # Authentication, route allow-listing and response encoding stay inherited
    # from the shared worker module; only the named service bundle below is
    # identity-bound. No module-global replacement is performed anywhere.

    engine_services_factory = staticmethod(_engine_services_for_env)
