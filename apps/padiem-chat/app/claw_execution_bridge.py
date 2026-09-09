"""Server-only B62 composition for the B54 Claw real P01 execution path (#2215).

B62 supplies only the trusted Worker transport and server-held Engine caller
credential.  B54 owns the product task/P01 composition; Engine/Core/B14 retain
runtime and provider authority.
"""

from __future__ import annotations

from typing import Any

from padiem_ai_engine_client import PadiemAiEngineClient

from kagent.manual_intake import ManualIntakeRequest
from kagent.manual_intake_p01 import build_manual_intake_p01_task
from kagent.p01_adapter import P01_APP_ID, P01AdapterError, P01CoreOrchestrationAdapter
from kagent.p01_orchestration_client import P01EngineOrchestrationClient

from .worker_config import binding_value
from .worker_orchestration import CloudflareEngineServiceTransport, ENGINE_SERVICE_BINDING_NAME


CLAW_ENGINE_CALLER_ID_ENV = "PADIEM_CLAW_ENGINE_CALLER_ID"
CLAW_ENGINE_CALLER_SECRET_ENV = "PADIEM_CLAW_ENGINE_CALLER_SECRET"


def _server_text(env: Any, name: str) -> str:
    value = binding_value(env, name)
    return value.strip() if isinstance(value, str) else ""


class ClawWebExecutionBridge:
    """Run one bounded manual intake through the existing B54 P01 adapter."""

    def __init__(self, adapter: P01CoreOrchestrationAdapter) -> None:
        if not isinstance(adapter, P01CoreOrchestrationAdapter):
            raise ValueError("P01CoreOrchestrationAdapter is required")
        self._adapter = adapter

    async def execute(self, request: ManualIntakeRequest) -> dict[str, object]:
        task = build_manual_intake_p01_task(request)
        outcome = await self._adapter.execute(task.run)
        public = outcome.safe_dict()
        return {
            "request_id": request.request_id,
            "channel": request.channel.value,
            "action": request.action.value,
            "answer": public["answer"],
            "projection": public["projection"],
            "p01_run_id": public["p01_run_id"],
            "p01_event_count": public["p01_event_count"],
            "direct_kakao_send": False,
            "direct_sms_send": False,
            "connector_write": False,
            "memory_durable_write": False,
        }


def build_claw_execution_bridge(
    env: Any,
    *,
    request_factory: Any,
) -> ClawWebExecutionBridge | None:
    """Fail closed unless the private Engine binding and Claw caller are present."""

    engine_binding = binding_value(env, ENGINE_SERVICE_BINDING_NAME)
    caller_id = _server_text(env, CLAW_ENGINE_CALLER_ID_ENV)
    caller_secret = _server_text(env, CLAW_ENGINE_CALLER_SECRET_ENV)
    if engine_binding is None or not caller_id or not caller_secret or not callable(request_factory):
        return None
    try:
        client = PadiemAiEngineClient(
            transport=CloudflareEngineServiceTransport(
                engine_binding,
                request_factory=request_factory,
            ),
            app_id=P01_APP_ID,
            caller_id=caller_id,
            credential=caller_secret,
        )
        adapter = P01CoreOrchestrationAdapter(P01EngineOrchestrationClient(client))
        return ClawWebExecutionBridge(adapter)
    except (P01AdapterError, TypeError, ValueError):
        return None


__all__ = [
    "CLAW_ENGINE_CALLER_ID_ENV",
    "CLAW_ENGINE_CALLER_SECRET_ENV",
    "ClawWebExecutionBridge",
    "build_claw_execution_bridge",
]
