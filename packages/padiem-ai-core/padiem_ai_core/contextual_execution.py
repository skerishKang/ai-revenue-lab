from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ErrorClass, RunMetadata, RunStatus, UsageMetadata
from .execution_context import (
    ExecutionContext,
    IdempotencyAdapter,
    IdempotencyConflictError,
    request_fingerprint,
)
from .execution_runtime import ExecutionRequest, ExecutionResult, ExecutionRuntime, ExecutionRuntimeError


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    context: ExecutionContext
    request_fingerprint: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.context.trace_id,
            "timeout_seconds": self.context.timeout_seconds,
            "idempotency_present": self.context.idempotency_key is not None,
            "request_fingerprint": self.request_fingerprint,
        }


def prepare_execution(
    *,
    context: ExecutionContext,
    app_id: str,
    payload: Mapping[str, Any],
) -> PreparedExecution:
    """Bind execution metadata to an exact request fingerprint.

    Authorization material is deliberately excluded from the fingerprint.
    Context fields do not grant authorization.
    """
    if not isinstance(context, ExecutionContext):
        raise ValueError("context must be ExecutionContext")
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id must be a non-empty string")
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    fingerprint_payload = dict(payload)
    for sensitive_key in ("authorization", "credential", "service_credential"):
        fingerprint_payload.pop(sensitive_key, None)
    fingerprint_payload.pop("execution_context", None)
    fingerprint_payload["app_id"] = app_id
    return PreparedExecution(
        context=context,
        request_fingerprint=request_fingerprint(fingerprint_payload),
    )


class ContextualExecutionRunner:
    """Apply bounded context around the existing Core execution runtime."""

    def __init__(
        self,
        *,
        runtime: ExecutionRuntime,
        app_id: str,
        idempotency: IdempotencyAdapter | None = None,
    ) -> None:
        if not isinstance(runtime, ExecutionRuntime):
            raise ValueError("runtime must be ExecutionRuntime")
        if runtime.app_id != app_id:
            raise ValueError("runtime app_id must match contextual app_id")
        self._runtime = runtime
        self._app_id = app_id
        self._idempotency = idempotency

    async def run(
        self,
        request: ExecutionRequest,
        *,
        context: ExecutionContext,
        request_payload: Mapping[str, Any],
    ) -> ExecutionResult:
        prepared = prepare_execution(
            context=context,
            app_id=self._app_id,
            payload=request_payload,
        )

        if context.idempotency_key is not None:
            if self._idempotency is None:
                raise ValueError("idempotency_key requires an injected IdempotencyAdapter")
            replay = await self._idempotency.begin(
                app_id=self._app_id,
                idempotency_key=context.idempotency_key,
                request_fingerprint=prepared.request_fingerprint,
            )
            if replay is not None:
                if not isinstance(replay, ExecutionResult):
                    raise IdempotencyConflictError(
                        "idempotency adapter returned an invalid replay"
                    )
                return replay

        try:
            result = await asyncio.wait_for(
                self._runtime.run(request),
                timeout=context.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            metadata = RunMetadata(
                trace_id=context.trace_id,
                app_id=self._app_id,
                agent_id=request.agent.id,
                session_id=request.session_id,
                status=RunStatus.TIMEOUT,
                usage=UsageMetadata(),
                error_class=ErrorClass.CONTEXT_ERROR,
            )
            raise ExecutionRuntimeError(
                "execution_timeout",
                "Model execution exceeded the bounded timeout.",
                metadata=metadata,
                retryable=False,
            ) from exc

        if context.idempotency_key is not None and self._idempotency is not None:
            await self._idempotency.complete(
                app_id=self._app_id,
                idempotency_key=context.idempotency_key,
                request_fingerprint=prepared.request_fingerprint,
                result=result.to_public_dict(),
            )
        return result
