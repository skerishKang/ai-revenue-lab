"""Subject identity classification and public presentation contract.

P01 treats the subject used for admission/entitlement/runtime authority as a
server-trusted internal identity. That internal identifier is not automatically a
public response field. Products that need a public subject reference must supply
a trusted, app-scoped opaque reference instead of reflecting account identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_PUBLIC_REF_RE = re.compile(r"^psub_[A-Za-z0-9_-]{12,64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 .()\-]{6,31}$")
_EXTERNAL_ACCOUNT_RE = re.compile(
    r"(?:^|[._:-])(email|phone|account|acct|kakao|naver|google|apple|oauth|credential|token)(?:$|[._:-])",
    re.IGNORECASE,
)


class SubjectIdentityClass(str, Enum):
    """Classification for subject identifiers at the Core boundary."""

    INTERNAL_CANONICAL_SUBJECT = "internal_canonical_subject"
    TENANT_APP_SCOPED_PSEUDONYM = "tenant_app_scoped_pseudonym"
    PUBLIC_SAFE_OPAQUE_REFERENCE = "public_safe_opaque_reference"
    PROHIBITED_DIRECT_IDENTIFIER = "prohibited_direct_identifier"


class SubjectIdentityError(ValueError):
    """Raised when a subject identity contract is violated."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def _require_safe_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise SubjectIdentityError("invalid_subject_identity", f"{name} must be a bounded safe identifier")
    return value


def is_direct_account_identifier(value: str) -> bool:
    """Return True for identifiers that must never be public subject refs."""

    if not isinstance(value, str) or not value:
        return True
    normalized = value.strip()
    if _EMAIL_RE.fullmatch(normalized):
        return True
    if _PHONE_RE.fullmatch(normalized):
        return True
    if _EXTERNAL_ACCOUNT_RE.search(normalized):
        return True
    return False


def classify_subject_identity(value: str) -> SubjectIdentityClass:
    """Classify one subject-like identifier without converting trust level."""

    if is_direct_account_identifier(value):
        return SubjectIdentityClass.PROHIBITED_DIRECT_IDENTIFIER
    if _PUBLIC_REF_RE.fullmatch(value):
        return SubjectIdentityClass.PUBLIC_SAFE_OPAQUE_REFERENCE
    if isinstance(value, str) and value.startswith(("tenant_", "subj_")) and _SAFE_ID_RE.fullmatch(value):
        return SubjectIdentityClass.TENANT_APP_SCOPED_PSEUDONYM
    if isinstance(value, str) and _SAFE_ID_RE.fullmatch(value):
        return SubjectIdentityClass.INTERNAL_CANONICAL_SUBJECT
    return SubjectIdentityClass.PROHIBITED_DIRECT_IDENTIFIER


@dataclass(frozen=True, slots=True)
class PublicSubjectReference:
    """Trusted adapter-produced, app-scoped presentation identity.

    A public subject reference is never authority. It is only safe presentation
    metadata and must remain scoped to one app/product boundary.
    """

    app_id: str
    subject_ref: str
    policy: str = "app_scoped_unlinkable"

    def __post_init__(self) -> None:
        object.__setattr__(self, "app_id", _require_safe_id("app_id", self.app_id))
        if classify_subject_identity(self.subject_ref) is not SubjectIdentityClass.PUBLIC_SAFE_OPAQUE_REFERENCE:
            raise SubjectIdentityError(
                "invalid_public_subject_reference",
                "public subject reference must be a bounded opaque adapter reference",
            )
        if self.policy != "app_scoped_unlinkable":
            raise SubjectIdentityError(
                "invalid_public_subject_policy",
                "public subject reference policy must be app_scoped_unlinkable",
            )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "subject_ref": self.subject_ref,
            "scope": "app",
            "policy": self.policy,
        }


def public_subject_reference_from_trusted_adapter(
    *,
    app_id: str,
    adapter_subject_ref: str | None,
) -> PublicSubjectReference | None:
    """Validate an optional trusted adapter public reference.

    Absence means default public minimization. The internal canonical subject is
    intentionally not an input because this function must not derive or expose
    presentation identity from authority identity.
    """

    if adapter_subject_ref is None:
        return None
    return PublicSubjectReference(app_id=app_id, subject_ref=adapter_subject_ref)


def assert_cross_app_unlinkable(left: PublicSubjectReference, right: PublicSubjectReference) -> None:
    """Fail closed if two app-scoped public refs are globally correlatable."""

    if left.app_id != right.app_id and left.subject_ref == right.subject_ref:
        raise SubjectIdentityError(
            "cross_app_subject_correlation",
            "public subject references for different apps must not share the same opaque value",
        )
