"""Trusted execution-admission enforcement for Engine orchestration runs.

This service is source-only and product-neutral. It composes the accepted
canonical idempotency/continuation service with the #1241 trusted admission gate,
but it is intentionally not wired into the active Worker until resume
non-widening and a trusted server adapter are also complete.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.execution_admission import ExecutionAdmissionError, ExecutionAdmissionRequest
from app.execution_admission_gate import resolve_and_require_trusted_admission
from app.orchestration_idempotency_service import (
    CanonicalIdempotencyOrchestrationEngineService,
    _initial_execution_fingerprint,
)
from app.orchestration_identity_service import (
    _ORCHESTRATE_ALLOWED_FIELDS,
    _reject_unknown_fields,
)
from app.orchestration_service import _parse_orchestration_options
from app.service import ServiceContractError, _service_error


ORCHESTRATION_RUN_CAPABILITY = "orchestration.run"


def _run_admission_request(payload: Any) -> ExecutionAdmissionRequest | None:
    """Build a server-owned admission query only for an otherwise parseable run.

    The request fingerprint is the canonical material logical-execution identity
    from #1235/#1594. Client entitlement/plan/credit/allow fields are not inputs
    and remain rejected by the Engine orchestration wire contract.
    """

    if not isinstance(payload, Mapping):
        return None
    try:
        _reject_unknown_fields(payload, allowed=_ORCHESTRATE_ALLOWED_FIELDS)
        fingerprint = _initial_execution_fingerprint(payload)
        if fingerprint is None:
            return None
        _, _, _, subject_id, _, _ = _parse_orchestration_options(payload)
        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return None
        return ExecutionAdmissionRequest(
            app_id=app_id,
            subject_id=subject_id,
            capability=ORCHESTRATION_RUN_CAPABILITY,
            request_fingerprint=fingerprint,
        )
    except (ServiceContractError, ExecutionAdmissionError, TypeError, ValueError):
        return None


class AdmissionBoundOrchestrationEngineService(CanonicalIdempotencyOrchestrationEngineService):
    """Require trusted server admission before any new orchestration run."""

    def __init__(self, *args: Any, admission_adapter: Any | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._admission_adapter = admission_adapter

    async def orchestrate_payload(self, payload: Any):
        # Preserve the existing wire-validation response for malformed/unsupported
        # requests rather than masking contract errors behind entitlement status.
        admission_request = _run_admission_request(payload)
        if admission_request is None:
            return await super().orchestrate_payload(payload)

        try:
            admission = await resolve_and_require_trusted_admission(
                adapter=self._admission_adapter,
                request=admission_request,
            )
            # The generic admission contract allows an unbound decision for less
            # sensitive capabilities. Engine orchestration does not: admission
            # must explicitly bind the canonical server-derived logical request.
            if (
                admission_request.request_fingerprint is None
                or admission.request_fingerprint != admission_request.request_fingerprint
            ):
                raise ExecutionAdmissionError(
                    "entitlement_request_mismatch",
                    "Trusted execution admission is not bound to this orchestration request.",
                    status_code=403,
                )
        except ExecutionAdmissionError as exc:
            return _service_error(
                exc.code,
                exc.safe_message,
                status_code=exc.status_code,
                retryable=exc.status_code >= 500,
            )

        return await super().orchestrate_payload(payload)
