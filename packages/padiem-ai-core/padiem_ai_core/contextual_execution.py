from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .execution_context import ExecutionContext, IdempotencyAdapter, request_fingerprint
from .execution_runtime import ExecutionRequest, ExecutionResult, ExecutionRuntime, ExecutionRuntimeError


class IdempotencyReplay(Protocol):
    """Product-owned adapter may return a previously completed canonical result."""


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
    """Bind an execution context to an exact request fingerprint.

    Authorization never participates in the fingerprint and context fields do
    not grant permission. The product/server decides whether idempotency may
    be used by injecting an adapter.
    """
    if not isinstance(context, ExecutionContext):
        raise ValueError("context must be ExecutionContext")
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id must be a non-empty string")
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")

    fingerprint_payload = dict(payload)
    fingerprint_payload.pop("authorization", None)
    fingerprint_payload.pop("credential", None)
    fingerprint_payload.pop("execution_context", None)
    fingerprint_payload["app_id"] = app_id
    return PreparedExecution(
        context=context,
        request_fingerprint=request_fingerprint(fingerprint_payload),
    )


class ContextualExecutionRunner:
    """Apply bounded execution context around the existing Core runtime."""

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

        replay = None
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
                    raise IdempotencyConflictError("idempotency adapter returned an invalid replay")
                return replay

        try:
            # asyncio cancellation is intentionally not caught. Callers must
            # observe CancelledError rather than receiving a generic failure.
            result = await asyncio.wait_for(
                self._runtime.run(request),
                timeout=context.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ExecutionRuntimeError(
                "execution_timeout",
                "Model execution exceeded the bounded timeout.",
                metadata=getattr(exc, "metadata", None),
                retryable=False,
            ) from None

        if context.idempotency_key is not None and self._idempotency is not None:
            await self._idempotency.complete(
                app_id=self._app_id,
                idempotency_key=context.idempotency_key,
                request_fingerprint=prepared.request_fingerprint,
                result=result.to_public_dict(),
            )
        return result


class IdempotencyConflictError(RuntimeError):
    """Raised when the adapter cannot safely honor the requested replay."""
