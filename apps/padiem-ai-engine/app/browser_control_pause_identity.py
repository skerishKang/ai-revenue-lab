"""#3782: a trusted, original-admission-bound identity for a browser P01 pause.

This is a validated projection, NOT a user-approval issuer or credentials.
The authoritative execution identity and run admission must be supplied by
the server-side owner; no browser tool arguments, wire request or model output
can mint the underlying admitted run.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.continuation_identity import ContinuationExecutionIdentity
from app.execution_admission_resume import OriginalAdmissionBinding


@dataclass(frozen=True, slots=True)
class TrustedBrowserControlPauseIdentity:
    execution_identity: ContinuationExecutionIdentity
    original_admission: OriginalAdmissionBinding

    def assert_matches(self, app_id: str) -> None:
        identity = self.execution_identity
        admission = self.original_admission
        if (
            type(identity) is not ContinuationExecutionIdentity
            or type(admission) is not OriginalAdmissionBinding
            or not app_id
            or admission.app_id != app_id
            or not identity.subject_id
            or admission.subject_id != identity.subject_id
            or admission.request_fingerprint != identity.request_fingerprint
            or not admission.authority_ref
            or not admission.decision_id
            or not admission.policy_revision
        ):
            raise ValueError("browser.control P01 requires exact trusted original run admission")
