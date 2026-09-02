"""Non-widening trusted admission contract for orchestration resume.

A paused run may resume only when two independent trusted facts hold:

1. the continuation belongs to the exact material execution that was admitted
   when the run started; and
2. current trusted Control Plane authority still admits `orchestration.resume`
   for that same app, subject, and material execution fingerprint.

A later entitlement expansion may change policy revision, but it cannot widen the
paused execution because the exact continuation identity and original material
request fingerprint remain fixed. Revocation or mismatch fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
    require_trusted_admission,
)


ORCHESTRATION_RUN_CAPABILITY = "orchestration.run"
ORCHESTRATION_RESUME_CAPABILITY = "orchestration.resume"


@dataclass(frozen=True, slots=True)
class OriginalAdmissionBinding:
    """Bounded evidence persisted with a paused originally-admitted run."""

    decision_id: str
    app_id: str
    subject_id: str | None
    authority_ref: str
    policy_revision: str
    request_fingerprint: str

    @classmethod
    def from_run_admission(cls, admission: TrustedExecutionAdmission) -> "OriginalAdmissionBinding":
        if not isinstance(admission, TrustedExecutionAdmission):
            raise ExecutionAdmissionError(
                "invalid_admission",
                "Original execution admission is invalid.",
            )
        if not admission.allowed:
            raise ExecutionAdmissionError(
                "entitlement_denied",
                "Original execution admission did not authorize the run.",
            )
        if admission.capability != ORCHESTRATION_RUN_CAPABILITY:
            raise ExecutionAdmissionError(
                "entitlement_capability_mismatch",
                "Original admission is not an orchestration.run decision.",
            )
        if not isinstance(admission.request_fingerprint, str) or len(admission.request_fingerprint) != 64:
            raise ExecutionAdmissionError(
                "entitlement_request_mismatch",
                "Original execution admission is not bound to a material request identity.",
            )
        return cls(
            decision_id=admission.decision_id,
            app_id=admission.app_id,
            subject_id=admission.subject_id,
            authority_ref=admission.authority_ref,
            policy_revision=admission.policy_revision,
            request_fingerprint=admission.request_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class ResumeAdmissionAuthority:
    """Auditable intersection of original-run and current-resume authority."""

    app_id: str
    subject_id: str | None
    request_fingerprint: str
    original_decision_id: str
    original_authority_ref: str
    original_policy_revision: str
    current_decision_id: str
    current_authority_ref: str
    current_policy_revision: str


def require_non_widening_resume_admission(
    *,
    original: OriginalAdmissionBinding,
    current: TrustedExecutionAdmission | None,
    expected_request_fingerprint: str,
    now: datetime | None = None,
) -> ResumeAdmissionAuthority:
    """Intersect original admitted execution with current trusted resume authority.

    Policy revision equality is intentionally *not* required. A newer trusted
    policy may revoke or expand product entitlement. Revocation fails through the
    current admission check; expansion cannot widen the paused execution because
    both decisions must bind the same original material request fingerprint.
    """

    if not isinstance(original, OriginalAdmissionBinding):
        raise ExecutionAdmissionError(
            "invalid_admission",
            "Original admission binding is unavailable.",
            status_code=503,
        )
    if original.request_fingerprint != expected_request_fingerprint:
        raise ExecutionAdmissionError(
            "continuation_admission_mismatch",
            "Paused execution admission does not match the continuation request identity.",
            status_code=409,
        )

    resume_request = ExecutionAdmissionRequest(
        app_id=original.app_id,
        subject_id=original.subject_id,
        capability=ORCHESTRATION_RESUME_CAPABILITY,
        request_fingerprint=expected_request_fingerprint,
    )
    validated = require_trusted_admission(
        request=resume_request,
        admission=current,
        now=now,
    )
    if validated.request_fingerprint != expected_request_fingerprint:
        raise ExecutionAdmissionError(
            "entitlement_request_mismatch",
            "Trusted resume admission is not bound to the paused execution request.",
            status_code=403,
        )

    return ResumeAdmissionAuthority(
        app_id=original.app_id,
        subject_id=original.subject_id,
        request_fingerprint=expected_request_fingerprint,
        original_decision_id=original.decision_id,
        original_authority_ref=original.authority_ref,
        original_policy_revision=original.policy_revision,
        current_decision_id=validated.decision_id,
        current_authority_ref=validated.authority_ref,
        current_policy_revision=validated.policy_revision,
    )
