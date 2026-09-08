"""Cloudflare Worker entrypoint with identity-bound Engine composition.

All existing transport/auth/streaming behavior remains in ``worker.py``. This
canonical composition root adds the E5 trusted multimodal reference route and
the E5B trusted document context route while preserving the explicit named
service bundle introduced by #1792. Both routes are source-wired but remain
fail-closed until their trusted resolver/evidence authorities are injected by
a later Production activation gate.
"""

from __future__ import annotations

import asyncio

from typing import Any
from urllib.parse import urlparse

from padiem_ai_core import (
    B14ExecutionClient,
    B14ExecutionConfig,
    B14StreamingClient,
    ExecutionRuntime,
    StreamingExecutionRuntime,
)
from padiem_ai_core.grounding_runtime import GroundedResearchRuntime
from padiem_ai_core.multimodal_execution_runtime import (
    MultimodalExecutionRuntime,
    MultimodalStreamingExecutionRuntime,
)
from padiem_ai_core.web_runtime import create_web_provider
from workers import Request

import worker as legacy_worker
from app.agent_skill_service import AgentSkillEngineService
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.attachment_byte_store import CloudflareD1ImageByteStore, ScopedImageByteStore
from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)
from app.connector_bindings import (
    build_tool_binding_resolver,
)
from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.gmail_port_httpx import HttpxGmailReadPort
from app.document_context_service import DOCUMENT_CONTEXT_PATH
from app.engine_composition import EngineServices
from app.idempotency_replay_service import IdempotencyReplayEngineService
from app.identity_enforcement import CALLER_CREDENTIAL_HEADER, CALLER_ID_HEADER
from app.multimodal_attachment_service import (
    MULTIMODAL_EXECUTE_PATH,
    MULTIMODAL_STREAM_PATH,
    MultimodalAttachmentEngineService,
    MultimodalStreamingEngineService,
)
from app.orchestration_idempotency_service import (
    CanonicalIdempotencyOrchestrationEngineService,
)
from app.service import EngineService, ServiceContractError, ServiceResponse
from app.streaming_service import StreamingEngineService
from app.tool_execution_service import ToolExecutionEngineService
from app.tool_projection import (
    TOOL_CANCEL_PATH,
    TOOL_EXECUTE_PATH,
    TOOL_RESUME_PATH,
)
from app.web_research_service import WebResearchEngineService

ENGINE_CONTINUATION_BINDING_NAME = "ENGINE_CONTINUATION"
ENGINE_GOOGLE_OAUTH_CLIENT_ID_ENV = "ENGINE_GOOGLE_OAUTH_CLIENT_ID"
ENGINE_GOOGLE_OAUTH_CLIENT_SECRET_ENV = "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET"
ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN_ENV = "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN"
ENGINE_CONNECTOR_GRANTS_BINDING = "ENGINE_CONNECTOR_GRANTS"
ENGINE_IMAGE_STORE_BINDING = "ENGINE_IMAGE_STORE"


def _continuation_store_for_env(
    env: Any,
) -> CloudflareD1IdentityBoundContinuationStore | None:
    """Resolve the explicit durable continuation authority; never fake Production state."""
    binding = legacy_worker._binding_value(env, ENGINE_CONTINUATION_BINDING_NAME)
    if binding is None:
        return None
    try:
        return CloudflareD1IdentityBoundContinuationStore(binding)
    except (TypeError, ValueError):
        return None


def _image_byte_store_for_env(env: Any) -> ScopedImageByteStore | None:
    """Resolve the deployment-owned scoped image byte store (#2182 S5).

    The D1 binding is Worker-owned and the ``0004_engine_attachment_images``
    schema is applied by the D1 provision gate; app code never creates or
    mutates schema. A missing or unusable binding yields ``None`` so the
    attachment route keeps failing closed instead of reading a fake store.
    """
    binding = legacy_worker._binding_value(env, ENGINE_IMAGE_STORE_BINDING)
    if binding is None:
        return None
    try:
        return ScopedImageByteStore(port=CloudflareD1ImageByteStore(binding))
    except (TypeError, ValueError):
        return None


def _scope_authority_for_env(env: Any) -> AuthSessionScopeAuthority | None:
    """Compose the per-request trusted scope authority (#2182 S5).

    ``CONTROL_PLANE_LIVE_ADAPTER = NOT_DONE``: the Engine has no live Control
    Plane ``resolve_auth_session`` transport yet, exactly as for the tenant
    admission gate in ``app/tenant_auth.py``. Without that trusted client the
    scope triple cannot be server-minted, so this returns ``None`` and every
    ``att_*`` request fails closed with 503 ``attachment_resolver_unavailable``
    rather than trusting a request-asserted tenant or subject.
    """

    return None


def _multimodal_authorities_for_env(
    env: Any,
) -> tuple[ScopedImageByteStore | None, AuthSessionScopeAuthority | None]:
    return _image_byte_store_for_env(env), _scope_authority_for_env(env)


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


async def _tool_binding_resolver_for_env(env: Any):
    """Compose the Engine Gmail tool binding resolver (WO-10 PR-C activation).

    Reads the three Worker secrets and the ENGINE_CONNECTOR_GRANTS D1 binding
    from the deployment env. If any piece is missing the factory returns None,
    keeping the canonical composition fail-closed. A grant store outage
    (``ServiceContractError`` from ``_gmail_grants_for_env``) is NOT treated as
    \"grant missed\": the port and binding are present, so every app_id gets a
    resolver that surfaces the same 503 ``connector_grants_unavailable`` instead
    of a silent fail-closed misread.
    """
    port = _gmail_port_for_env(env)
    if port is None:
        return None
    try:
        grants = await _gmail_grants_for_env(env)
    except ServiceContractError as exc:
        # `except ... as exc` clears `exc` when the block ends, so the closure
        # must capture the value through a persistent local name.
        grant_error = exc

        def unavailable(_app_id: str) -> None:
            raise grant_error

        return unavailable
    if not grants:
        return None
    return build_tool_binding_resolver(gmail_port=port, grants=grants)


def _gmail_port_for_env(env: Any) -> HttpxGmailReadPort | None:
    client_id = legacy_worker._binding_value(env, ENGINE_GOOGLE_OAUTH_CLIENT_ID_ENV)
    client_secret = legacy_worker._binding_value(env, ENGINE_GOOGLE_OAUTH_CLIENT_SECRET_ENV)
    refresh_token = legacy_worker._binding_value(env, ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN_ENV)
    if not client_id or not client_secret or not refresh_token:
        return None
    try:
        return HttpxGmailReadPort(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
    except Exception:
        return None


async def _gmail_grants_for_env(env: Any) -> dict[str, GmailGrant]:
    binding = legacy_worker._binding_value(env, ENGINE_CONNECTOR_GRANTS_BINDING)
    if binding is None:
        return {}
    try:
        store = CloudflareD1ConnectorGrantStore(binding)
        return await store.load_gmail_grants()
    except ServiceContractError:
        raise
    except Exception:
        raise ServiceContractError(
            "connector_grants_unavailable",
            "Connector grant storage could not be loaded.",
            status_code=503,
        ) from None


async def _engine_services_for_env(env: Any) -> EngineServices:
    binding = legacy_worker._binding_value(env, legacy_worker.B14_SERVICE_BINDING_NAME)
    image_byte_store, scope_authority = _multimodal_authorities_for_env(env)
    if binding is None:
        unavailable = lambda app_id: (_ for _ in ()).throw(
            RuntimeError("unreachable without B14 service binding")
        )
        return EngineServices(
            completed=EngineService(
                runtime_factory=unavailable, b14_service_bound=False
            ),
            streaming=StreamingEngineService(
                runtime_factory=unavailable, b14_service_bound=False
            ),
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
                image_byte_store=image_byte_store,
                scope_authority=scope_authority,
            ),
            multimodal_streaming=MultimodalStreamingEngineService(
                runtime_factory=unavailable,
                image_byte_store=image_byte_store,
                scope_authority=scope_authority,
            ),
            # E7 tool execution/continuation remains a source seam: the
            # resolver factory below returns None until a real port and grant
            # store are bound (PR-C). With no port/grant every request still
            # fails closed as `tool_runtime_unavailable` exactly as before.
            tool_execution=ToolExecutionEngineService(
                tool_binding_resolver=await _tool_binding_resolver_for_env(env)
            ),
            # binding_resolver stays None until a trusted Agent/Skill registry source exists (#1969); every request fails closed 503 agent_skill_runtime_unavailable.
            agent_skill=AgentSkillEngineService(
                runtime_factory=unavailable,
                binding_resolver=None,
            ),
        )

    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=Request,
    )
    config = B14ExecutionConfig(
        base_url=B14_INTERNAL_ORIGIN,
        timeout_seconds=legacy_worker._b14_timeout_seconds_for_env(env),
    )
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

    def multimodal_streaming_runtime_factory(app_id: str) -> MultimodalStreamingExecutionRuntime:
        return MultimodalStreamingExecutionRuntime(
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
            idempotency_adapter=idempotency_adapter,
        ),
        orchestration=CanonicalIdempotencyOrchestrationEngineService(
            runtime_factory=runtime_factory,
            b14_service_bound=True,
            idempotency_adapter=idempotency_adapter,
            continuation_store=continuation_store,
            approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
            tool_binding_resolver=await _tool_binding_resolver_for_env(env),
        ),
        research=_research_service_for_env(
            env,
            runtime_factory,
            b14_service_bound=True,
        ),
        memory=legacy_worker._memory_service_for_env(env),
        multimodal=MultimodalAttachmentEngineService(
            runtime_factory=multimodal_runtime_factory,
            # #2182 S5: the resolver is no longer a caller-supplied object. It
            # is built per request from the deployment D1 image store plus the
            # per-request server-minted TrustedCallerScope. Either authority is
            # absent until its own gate, and the route fails closed 503.
            image_byte_store=image_byte_store,
            scope_authority=scope_authority,
        ),
        multimodal_streaming=MultimodalStreamingEngineService(
            runtime_factory=multimodal_streaming_runtime_factory,
            image_byte_store=image_byte_store,
            scope_authority=scope_authority,
        ),
        # E7 tool execution/continuation remains a source seam: the
        # resolver factory below returns None until a real port and grant
        # store are bound (PR-C). With no port/grant every request still
        # fails closed as `tool_runtime_unavailable` exactly as before.
        tool_execution=ToolExecutionEngineService(
            tool_binding_resolver=await _tool_binding_resolver_for_env(env)
        ),
        # #1964 source slice: replay composes only the same trusted durable
        # adapter as execution; without it the route fails closed (503).
        idempotency_replay=IdempotencyReplayEngineService(
            idempotency_adapter=idempotency_adapter,
        ),
        # binding_resolver stays None until a trusted Agent/Skill registry source exists (#1969); every request fails closed 503 agent_skill_runtime_unavailable.
        agent_skill=AgentSkillEngineService(
            runtime_factory=runtime_factory,
            binding_resolver=None,
            idempotency_adapter=idempotency_adapter,
            approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
            continuation_store=continuation_store,
        ),
    )


class Default(legacy_worker.Default):
    """Canonical Worker entrypoint with one additional E5/E5B source route.

    Existing routes remain inherited unchanged. The multimodal route repeats
    only the same body-read/service-auth boundary before invoking its named
    service; no storage resolver or alternate authentication mechanism lives
    here.
    """

    engine_services_factory = staticmethod(_engine_services_for_env)

    async def fetch(self, request: Any) -> Any:
        path = urlparse(str(request.url)).path
        if path == DOCUMENT_CONTEXT_PATH:
            return await self._fetch_document_context(request, path)
        if path == MULTIMODAL_EXECUTE_PATH:
            return await self._fetch_multimodal(request, path)
        if path == MULTIMODAL_STREAM_PATH:
            return await self._fetch_multimodal_stream(request, path)
        if path in {TOOL_EXECUTE_PATH, TOOL_RESUME_PATH, TOOL_CANCEL_PATH}:
            return await self._fetch_tool(request, path)
        return await super().fetch(request)

    async def _fetch_multimodal(self, request: Any, path: str) -> Any:
        """E5A trusted multimodal reference route: source-wired, fail-closed.

        This repeats only the same body-read/service-auth boundary before
        invoking its named service; no storage resolver or alternate
        authentication mechanism lives here.
        """
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

        services = await self.engine_services_factory(self.env)
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

    async def _fetch_multimodal_stream(self, request: Any, path: str) -> Any:
        method = str(getattr(request, "method", ""))
        headers = getattr(request, "headers", None)
        content_type = headers.get("content-type") if headers is not None else None
        body = b""
        if method.upper() == "POST":
            try:
                body = str(await request.text()).encode("utf-8")
            except Exception:
                return legacy_worker._json_response(
                    ServiceResponse(status_code=400, body={"ok": False, "error": {
                        "code": "invalid_request", "message": "Request body could not be read.",
                        "retryable": False, "metadata": None,
                    }})
                )
        auth_error = legacy_worker._authenticate_non_health_request(self.env, headers, body)
        if auth_error is not None:
            return auth_error
        services = await self.engine_services_factory(self.env)
        if services.multimodal_streaming is None:
            return legacy_worker._error_response(
                "multimodal_streaming_unavailable",
                "Multimodal streaming service is unavailable.",
                503,
            )
        prepared = await services.multimodal_streaming.prepare(
            method=method, path=path, content_type=content_type, body=body
        )
        if isinstance(prepared, ServiceResponse):
            return legacy_worker._json_response(prepared)
        return legacy_worker._ndjson_response(services.multimodal_streaming, prepared)

    async def _fetch_tool(self, request: Any, path: str) -> Any:
        """E7 tool execution/continuation route: source-wired, fail-closed.

        The canonical composition leaves the whole service uninjected with any
        trusted tool registry or continuation authority until a later
        Production activation gate, so every request fails closed before any
        tool handler can run.
        """
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

        services = await self.engine_services_factory(self.env)
        if services.tool_execution is None:
            return legacy_worker._error_response(
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
        return legacy_worker._json_response(result)

    async def _fetch_document_context(self, request: Any, path: str) -> Any:
        """E5B trusted document context route: source-wired, fail-closed.

        The wire carries only an ``att_*`` reference, so the shared body-app
        authenticator cannot bind it; caller credential verification and the
        server-owned scope triple are the injected scope authority's job. The
        canonical composition leaves the whole service uninjected until the
        Production activation gate provides that authority plus the resolver
        and evidence port, so every request fails closed before any port is
        reachable. No storage endpoint may be named by the caller here.
        """
        method = str(getattr(request, "method", ""))
        headers = getattr(request, "headers", None)
        content_type = headers.get("content-type") if headers is not None else None
        caller_id = headers.get(CALLER_ID_HEADER) if headers is not None else None
        credential = (
            headers.get(CALLER_CREDENTIAL_HEADER) if headers is not None else None
        )

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

        services = await self.engine_services_factory(self.env)
        if services.documents is None:
            return legacy_worker._error_response(
                "document_context_unavailable",
                "Trusted document context service is unavailable.",
                503,
            )
        result = await services.documents.handle(
            method=method,
            path=path,
            content_type=content_type,
            body=body,
            caller_id=caller_id if isinstance(caller_id, str) else "",
            credential=credential if isinstance(credential, str) else "",
        )
        return legacy_worker._json_response(result)
