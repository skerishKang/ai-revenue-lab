"""Worker-native composition of the Claw P01/Engine client (#2229).

Builds the existing B54 P01 adapter/client from trusted B62 Worker bindings and
a Pyodide-compatible Service Binding transport. This module never reads
``os.environ``: the deployed Python Worker has no process environment carrying
``P01_ENGINE_*`` values, so the previous ``p01_adapter_from_environment`` path
was production-dead. A missing or malformed binding fails closed to ``None``
before any network transport is constructed.

The Engine target is the fixed ``P01_ENGINE_SERVICE`` Service Binding reused
through ``CloudflareEngineServiceTransport`` (the same bounded, Worker-compatible
transport already proven for the orchestration bridge), not a browser-supplied
base URL and not a stdlib ``urllib`` socket that cannot run in Pyodide.
"""

from __future__ import annotations

from typing import Any

from kagent.p01_adapter import P01_APP_ID, P01CoreOrchestrationAdapter
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from padiem_ai_engine_client import PadiemAiEngineClient

from .worker_config import (
    P01_DIAG_CLIENT_CONSTRUCTOR_ERROR,
    P01_DIAG_COMPOSITION_UNAVAILABLE,
    p01_engine_binding_diagnostic,
    p01_engine_config_from_worker_bindings,
)
from .worker_orchestration import CloudflareEngineServiceTransport


def build_claw_p01_adapter(
    env: Any,
    *,
    request_factory: Any,
) -> P01CoreOrchestrationAdapter | None:
    """Compose the Claw P01 adapter from Worker bindings, or fail closed to None.

    ``request_factory`` is the Worker ``Request`` constructor used by the Service
    Binding transport; it is supplied by the caller (``worker.py``) so this module
    stays free of any runtime import of the ``workers`` package.
    """
    adapter, _ = build_claw_p01_adapter_with_diagnostic(env, request_factory=request_factory)
    return adapter


def build_claw_p01_adapter_with_diagnostic(
    env: Any,
    *,
    request_factory: Any,
) -> tuple[P01CoreOrchestrationAdapter | None, str | None]:
    """Same fail-closed composition as ``build_claw_p01_adapter``, plus one
    bounded public-safe diagnostic (#2413).

    On success returns ``(adapter, None)`` exactly as before. On failure returns
    ``(None, diagnostic)`` where the diagnostic is one fixed constant from
    ``worker_config`` describing *which* composition step failed. Exception
    messages, types, and any binding values are never propagated: the
    diagnostic vocabulary is closed and non-secret.
    """
    try:
        config = p01_engine_config_from_worker_bindings(env)
    except Exception:
        return None, P01_DIAG_COMPOSITION_UNAVAILABLE
    if config is None:
        try:
            binding_diagnostic = p01_engine_binding_diagnostic(env)
        except Exception:
            binding_diagnostic = None
        return None, binding_diagnostic or P01_DIAG_COMPOSITION_UNAVAILABLE
    try:
        transport = CloudflareEngineServiceTransport(
            config.service_binding,
            request_factory=request_factory,
        )
        client = PadiemAiEngineClient(
            transport=transport,
            app_id=P01_APP_ID,
            caller_id=config.caller_id,
            credential=config.credential,
        )
    except (TypeError, ValueError):
        return None, P01_DIAG_CLIENT_CONSTRUCTOR_ERROR
    except Exception:
        return None, P01_DIAG_COMPOSITION_UNAVAILABLE
    try:
        return P01CoreOrchestrationAdapter(P01EngineOrchestrationClient(client)), None
    except Exception:
        return None, P01_DIAG_COMPOSITION_UNAVAILABLE


__all__ = ["build_claw_p01_adapter", "build_claw_p01_adapter_with_diagnostic"]
