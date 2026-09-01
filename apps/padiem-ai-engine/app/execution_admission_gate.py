"""Fail-closed execution admission gate helpers for Engine orchestration.

This module is the server-side bridge between Engine request handling and the
trusted admission contract. It deliberately resolves admission only through an
injected trusted adapter; browser/client shaped entitlement, plan, quota, credit,
or allow fields are never accepted as an admission decision.

The helper is network-free and product-neutral. Live Control Plane wiring and
Worker composition injection remain separate #1241 slices.
"""

from __future__ import annotations

import inspect
from typing import Any

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
    require_trusted_admission,
)


async def resolve_and_require_trusted_admission(
    *,
    adapter: Any | None,
    request: ExecutionAdmissionRequest,
    now: Any | None = None,
) -> TrustedExecutionAdmission:
    """Resolve and validate trusted execution admission through a server adapter.

    Missing adapters, missing methods, adapter exceptions, malformed adapter
    returns, denied decisions, stale decisions, and mismatched decisions all fail
    closed as :class:`ExecutionAdmissionError`. The caller can map the bounded
    error code/status into the Engine service response without executing Core.
    """

    if adapter is None or not callable(getattr(adapter, "resolve_admission", None)):
        raise ExecutionAdmissionError(
            "entitlement_unavailable",
            "Trusted execution admission authority is unavailable.",
            status_code=503,
        )

    try:
        admission = adapter.resolve_admission(request)
        if inspect.isawaitable(admission):
            admission = await admission
    except ExecutionAdmissionError:
        raise
    except Exception as exc:
        raise ExecutionAdmissionError(
            "entitlement_unavailable",
            "Trusted execution admission authority is unavailable.",
            status_code=503,
        ) from exc

    return require_trusted_admission(
        request=request,
        admission=admission,
        now=now,
    )
