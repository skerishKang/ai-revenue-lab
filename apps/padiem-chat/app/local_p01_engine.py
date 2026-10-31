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

import httpx
from kagent.p01_adapter import P01_APP_ID
from kagent.p01_approval_continuation import P01EngineApprovalContinuationClient
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from padiem_ai_engine_client import PadiemAiEngineClient

from .claw_p01_composition import compose_p01_lanes
from .orchestration_composition import CHAT_ENGINE_APP_ID
from .local_engine_transport import (
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
) -> tuple[
    Any | None,
    P01EngineApprovalContinuationClient | None,
    str | None,
]:
    """Compose both B54 P01 lanes over one loopback transport, or fail closed."""

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
            engine_client, allow_subject_identity=False
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


__all__ = [
    "CHAT_ENGINE_APP_ID",
    "LOCAL_P01_CALLER_ID_ENV",
    "LOCAL_P01_CREDENTIAL_ENV",
    "LOCAL_P01_ORIGIN_ENV",
    "LOCAL_P01_ORIGIN_INVALID_DIAGNOSTIC",
    "LOCAL_P01_UNBOUND_DIAGNOSTIC",
    "LocalP01EngineConfig",
    "build_local_engine_client",
    "build_local_p01_adapter",
    "build_local_p01_lanes",
    "local_p01_engine_config_from_env",
]
