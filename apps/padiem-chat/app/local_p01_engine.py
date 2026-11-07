"""The CPython host's P01/Engine composition (#6356 follow-up, 2026-10-31).

``claw_p01_composition`` projects the P01 surface from Worker bindings. A native
CPython host has no bindings, so the same two lanes are composed here from one
explicit loopback origin plus the same caller identity the Worker validates.

Default off: with none of the three variables set the composition returns
``(None, None, None)`` and the caller keeps reporting
``NOT_CONFIGURED reason=p01_engine_transport_unbound``. A configured but
malformed surface fails closed with one bounded diagnostic constant; no origin,
credential length, value or exception text is ever printed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from kagent.p01_adapter import P01_APP_ID
from kagent.p01_approval_continuation import P01EngineApprovalContinuationClient
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from padiem_ai_engine_client import PadiemAiEngineClient

from .calendar_read_activation_engine import (
    CALENDAR_READ_ACTIVATION_PATH,
    CloudflareCalendarReadActivationEngineClient,
)
from .claw_p01_composition import compose_p01_lanes
from .connector_tool_engine_client import (
    TOOL_EXECUTE_ENDPOINT,
    CloudflareConnectorToolEngineClient,
)
from .orchestration_composition import CHAT_ENGINE_APP_ID
from .local_engine_transport import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_ENGINE_RESPONSE_BYTES,
    LocalEngineHttpTransport,
    LocalEngineTransportError,
    local_engine_origin,
)
from .worker_config import (
    P01_DIAG_CLIENT_CONSTRUCTOR_ERROR,
    P01_DIAG_COMPOSITION_UNAVAILABLE,
    validate_p01_caller_and_credential,
)

LOCAL_P01_ORIGIN_ENV = "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN"
LOCAL_P01_CALLER_ID_ENV = "PADIEM_CHAT_LOCAL_P01_CALLER_ID"
LOCAL_P01_CREDENTIAL_ENV = "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL"
LOCAL_P01_UNBOUND_DIAGNOSTIC = "p01_engine_transport_unbound"
LOCAL_P01_ORIGIN_INVALID_DIAGNOSTIC = "p01_engine_origin_invalid"


@dataclass(frozen=True, slots=True)
class LocalP01EngineConfig:
    origin: str
    caller_id: str
    credential: str


def _env_text(env: Any, name: str) -> str:
    value = env.get(name) if hasattr(env, "get") else None
    return value.strip() if isinstance(value, str) else ""


def local_p01_engine_config_from_env(
    env: Any,
) -> tuple[LocalP01EngineConfig | None, str | None]:
    """Return the configured loopback surface, its diagnostic, or ``(None, None)``."""

    raw_origin = _env_text(env, LOCAL_P01_ORIGIN_ENV)
    caller_id = _env_text(env, LOCAL_P01_CALLER_ID_ENV)
    credential = env.get(LOCAL_P01_CREDENTIAL_ENV) if hasattr(env, "get") else None
    credential = credential if isinstance(credential, str) else ""
    if not raw_origin and not caller_id and not credential:
        return None, None
    try:
        origin = local_engine_origin(raw_origin)
    except LocalEngineTransportError:
        return None, LOCAL_P01_ORIGIN_INVALID_DIAGNOSTIC
    # Same validation the deployed Worker applies to its own caller surface.
    diagnostic = validate_p01_caller_and_credential(caller_id, credential)
    if diagnostic is not None:
        return None, diagnostic
    return LocalP01EngineConfig(origin=origin, caller_id=caller_id, credential=credential), None


def _engine_client(
    config: LocalP01EngineConfig,
    *,
    client: httpx.AsyncClient | None,
    app_id: str,
) -> tuple[PadiemAiEngineClient | None, str | None]:
    """The one Engine client constructor both host lanes use."""

    try:
        return (
            PadiemAiEngineClient(
                transport=LocalEngineHttpTransport(config.origin, client=client),
                app_id=app_id,
                caller_id=config.caller_id,
                credential=config.credential,
            ),
            None,
        )
    except (TypeError, ValueError):
        return None, P01_DIAG_CLIENT_CONSTRUCTOR_ERROR
    except Exception:
        return None, P01_DIAG_COMPOSITION_UNAVAILABLE


def build_local_engine_client(
    env: Any,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[PadiemAiEngineClient | None, str | None]:
    """One loopback Engine client for the host, or a bounded diagnostic.

    The chat orchestration bridge submits turns as ``padiem-chat`` and the claw
    lanes as ``P01_APP_ID``. Both travel the same validated caller surface, so
    the transport and identity checks live here once and the app id is the only
    difference a caller supplies.
    """

    config, diagnostic = local_p01_engine_config_from_env(env)
    if config is None:
        return None, diagnostic
    return _engine_client(config, client=client, app_id=CHAT_ENGINE_APP_ID)


def build_local_p01_lanes(
    env: Any,
    *,
    client: httpx.AsyncClient | None = None,
    allow_subject_identity: bool = False,
) -> tuple[
    Any | None,
    P01EngineApprovalContinuationClient | None,
    str | None,
]:
    """Compose both B54 P01 lanes over one loopback transport, or fail closed.

    ``allow_subject_identity`` is the host's view of the Worker's
    ``identity_authority_bound``: the caller passes True only when a Control
    Plane identity authority is actually composed, so the canonical USER lane is
    never invented from a host that cannot revalidate the subject (#3382).
    """

    config, diagnostic = local_p01_engine_config_from_env(env)
    if config is None:
        return None, None, diagnostic
    engine_client, diagnostic = _engine_client(
        config, client=client, app_id=P01_APP_ID
    )
    if engine_client is None:
        return None, None, diagnostic
    try:
        # The host has no Control Plane identity authority bound, so the
        # canonical USER lane stays off exactly as it does in a Worker without
        # that binding: the validated callers still travel, the subject does not
        # get invented.
        adapter, continuation = compose_p01_lanes(
            engine_client, allow_subject_identity=allow_subject_identity
        )
    except Exception:
        return None, None, P01_DIAG_COMPOSITION_UNAVAILABLE
    return adapter, continuation, None


def build_local_p01_adapter(
    env: Any,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[Any | None, str | None]:
    """The orchestrate lane alone, with the same single bounded diagnostic."""

    adapter, _, diagnostic = build_local_p01_lanes(env, client=client)
    return adapter, diagnostic


@dataclass(frozen=True, slots=True)
class LocalEngineRequest:
    """The ``js_object`` shape a Service Binding receives, built by the client."""

    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    body: str | None = None

    @property
    def js_object(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "method": self.method,
            "headers": dict(self.headers or {}),
            "body": self.body,
        }


class LocalEngineFetchResponse:
    """The bounded slice of a Binding ``Response`` the Engine clients read."""

    __slots__ = ("status", "_body")

    def __init__(self, *, status: int, body: str) -> None:
        self.status = int(status)
        self._body = body

    async def text(self) -> str:
        return self._body


class LocalEngineFetchBinding:
    """Service-Binding-shaped ``fetch`` over one loopback Engine origin.

    The Worker client builds its URL from ``ENGINE_INTERNAL_ORIGIN`` and hands
    the request to a Service Binding that ignores the host entirely. A native
    host has no binding, so this object accepts exactly the paths named at
    construction and dials the configured loopback origin with the same method,
    headers and body. A path outside that set is refused before any socket use,
    so the caller cannot widen the target.
    """

    def __init__(
        self,
        origin: str,
        *,
        paths: tuple[str, ...],
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._origin = local_engine_origin(origin)
        self._paths = frozenset(paths)
        self._client = client
        self._timeout = timeout
        if client is not None and getattr(client, "follow_redirects", False):
            raise LocalEngineTransportError(
                "local engine client must not follow redirects"
            )

    async def fetch(self, request: object) -> LocalEngineFetchResponse:
        if not isinstance(request, dict):
            raise LocalEngineTransportError("Engine request must be an object")
        parsed = urlparse(str(request.get("url") or ""))
        if parsed.path not in self._paths:
            raise LocalEngineTransportError(
                "Engine client requested an unsupported internal target"
            )
        method = str(request.get("method") or "").upper()
        if method != "POST":
            raise LocalEngineTransportError("Engine call must be POST")
        headers = {
            str(name): str(value)
            for name, value in dict(request.get("headers") or {}).items()
        }
        body = request.get("body")
        if body is not None and not isinstance(body, (str, bytes)):
            raise LocalEngineTransportError("Engine request body must be text")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            follow_redirects=False, timeout=self._timeout
        )
        try:
            try:
                response = await client.request(
                    method, self._origin + parsed.path, headers=headers, content=body
                )
            except httpx.HTTPError:
                raise LocalEngineTransportError(
                    "local engine request failed"
                ) from None
            if len(response.content) > MAX_ENGINE_RESPONSE_BYTES:
                raise LocalEngineTransportError(
                    "Engine response exceeded the host transport safety limit"
                )
            return LocalEngineFetchResponse(
                status=response.status_code, body=response.text
            )
        finally:
            if owns_client:
                await client.aclose()


def build_local_calendar_read_activation_client(
    env: Any,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[CloudflareCalendarReadActivationEngineClient | None, str | None]:
    """The Worker's Calendar READ activation client over the loopback Engine.

    Same client class, same caller surface and same closed response contract the
    deployed Worker uses; only the transport is the host's loopback binding and
    only the reviewed activation path is reachable through it. Unconfigured
    stays unbound so the route keeps its documented 503.
    """

    config, diagnostic = local_p01_engine_config_from_env(env)
    if config is None:
        return None, diagnostic
    try:
        binding = LocalEngineFetchBinding(
            config.origin, paths=(CALENDAR_READ_ACTIVATION_PATH,), client=client
        )
        return (
            CloudflareCalendarReadActivationEngineClient(
                binding,
                caller_id=config.caller_id,
                credential=config.credential,
                request_factory=LocalEngineRequest,
            ),
            None,
        )
    except (TypeError, ValueError):
        return None, P01_DIAG_CLIENT_CONSTRUCTOR_ERROR
    except Exception:
        return None, P01_DIAG_COMPOSITION_UNAVAILABLE


def build_local_connector_tool_client(
    env: Any,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[CloudflareConnectorToolEngineClient | None, str | None]:
    """The Worker's connector READ execute client over the loopback Engine.

    Same client class and same P01 caller surface; only the transport is the
    host's loopback binding and only the private tool-execute path is
    reachable through it. Unconfigured stays unbound so the tool lane keeps
    failing closed with ``connector_tool_unavailable``.
    """

    config, diagnostic = local_p01_engine_config_from_env(env)
    if config is None:
        return None, diagnostic
    try:
        binding = LocalEngineFetchBinding(
            config.origin, paths=(TOOL_EXECUTE_ENDPOINT,), client=client
        )
        return (
            CloudflareConnectorToolEngineClient(
                binding,
                caller_id=config.caller_id,
                credential=config.credential,
                request_factory=LocalEngineRequest,
            ),
            None,
        )
    except (TypeError, ValueError):
        return None, P01_DIAG_CLIENT_CONSTRUCTOR_ERROR
    except Exception:
        return None, P01_DIAG_COMPOSITION_UNAVAILABLE


__all__ = [
    "CHAT_ENGINE_APP_ID",
    "LOCAL_P01_CALLER_ID_ENV",
    "LOCAL_P01_CREDENTIAL_ENV",
    "LOCAL_P01_ORIGIN_ENV",
    "LOCAL_P01_ORIGIN_INVALID_DIAGNOSTIC",
    "LOCAL_P01_UNBOUND_DIAGNOSTIC",
    "LocalEngineFetchBinding",
    "LocalEngineFetchResponse",
    "LocalEngineRequest",
    "LocalP01EngineConfig",
    "build_local_calendar_read_activation_client",
    "build_local_connector_tool_client",
    "build_local_engine_client",
    "build_local_p01_adapter",
    "build_local_p01_lanes",
    "local_p01_engine_config_from_env",
]
