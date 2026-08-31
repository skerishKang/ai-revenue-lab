"""Cloudflare Worker entrypoint with identity-bound orchestration continuation wiring.

All transport/auth/streaming behavior remains in the existing worker module. This
entrypoint replaces only the orchestration service factory so approval resumes
use the canonical continuation execution identity contract.
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
from workers import Request

from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.orchestration_identity_service import IdentityBoundOrchestrationEngineService
from app.service import EngineService
from app.streaming_service import StreamingEngineService


def _engine_services_for_env(
    env: Any,
) -> tuple[EngineService, StreamingEngineService, IdentityBoundOrchestrationEngineService]:
    binding = legacy_worker._binding_value(env, legacy_worker.B14_SERVICE_BINDING_NAME)
    if binding is None:
        unavailable = lambda app_id: (_ for _ in ()).throw(
            RuntimeError("unreachable without B14 service binding")
        )
        return (
            EngineService(runtime_factory=unavailable, b14_service_bound=False),
            StreamingEngineService(runtime_factory=unavailable, b14_service_bound=False),
            IdentityBoundOrchestrationEngineService(
                runtime_factory=unavailable,
                b14_service_bound=False,
            ),
        )

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
        IdentityBoundOrchestrationEngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
        ),
    )


# Default.fetch resolves this global from legacy_worker, so replace only the
# factory seam before exporting the unchanged WorkerEntrypoint class.
legacy_worker._engine_services_for_env = _engine_services_for_env
Default = legacy_worker.Default
