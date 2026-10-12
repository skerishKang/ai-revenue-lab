"""#4139 S1 — PADIEM Connector server-side enrollment contract.

Goal: after the PADIEM Connector is installed on a Windows computer, signing in
with the **same PADIEM account** must be enough for that PC to be registered in
the existing Canonical Broker — safely, once, and shared by every product.

This module is the missing *server-side* seam. It does not replace anything that
already exists:

```text
canonical identity        = control_plane.identity_authority AuthSessionSnapshot
                            (resolved through the existing B54 / B62 session
                            resolvers).  This module never authenticates a user,
                            never verifies a password, never mints a session.
server-owned scope refs   = an injected CanonicalEnrollmentScopePort.  A single
                            PC id shared by all products requires one
                            product-neutral (account, workspace) scope, so the
                            refs come from the existing Control Plane owner
                            resolver — never from the Connector, the browser or a
                            product route.
device lifecycle +        = padiem_control_plane.local_agent_broker_pairing
enrollment + credential     (InMemoryBrokerPairingAuthority and its routes)
binding / rotation /      = padiem_control_plane.local_agent_broker
revocation                  (InMemoryLocalAgentBrokerAuthority.register_binding /
                             rotate_credential / revoke_binding)
lifecycle vocabulary      = kagent.local_agent_pairing (untouched here)
ONLINE truth              = kagent.local_agent_server_projection (untouched here)
READ/WRITE approval       = the existing P01 approval path (untouched here)
```

What this module deliberately does **not** create:

* a second login / identity / session system — the only identity input is an
  already-verified canonical :class:`AuthSessionSnapshot`;
* a second device database or device registry — the only device fact input is
  the canonical Broker binding the pairing authority mints;
* a second pairing authority, credential store, rotation path or revocation
  path — all four are delegated, and the delegation is declared in
  :func:`connector_enrollment_dependencies`;
* a product-scoped registration — one physical PC has exactly one canonical
  binding, so Claw, Quote, Chat and Engine resolve the *same* PC id;
* a new authentication method for the Connector (device-code, mTLS client
  certificate, SSO/SAML, ...) — unsupported methods are *recorded as
  dependencies* rather than invented, and the Connector must present an existing
  canonical PADIEM session;
* any execution authority.  Issuing or redeeming an enrollment is **not**
  approval to read or write files on the computer, and
  ``dispatch_authorized`` is hard-wired ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Protocol

from .auth_sessions import AuthSessionState, AuthSessionSnapshot
from .contracts import ControlPlaneContractError, SubjectType
from .local_agent_broker_pairing import (
    MAX_PAIRING_TTL_SECONDS,
    MIN_PAIRING_TTL_SECONDS,
    PAIRING_CODE_HEX_CHARS,
    PAIRING_PROOF_TRANSCRIPT,
    PROOF_REF_RE,
    BrokerPairingAuthorityPort,
    BrokerPairingChallenge,
    BrokerPairingEnrollment,
)
from .local_agent_pc_access import P01_APPROVAL_OWNER, PRODUCT_PC_ACCESS_DEFAULT

CONNECTOR_ENROLLMENT_CONTRACT_VERSION = "padiem.connector-enrollment.v1"
CONNECTOR_ENROLLMENT_CONSENT_VERSION = "padiem.connector-enrollment-consent.v1"

#: The pairing authority's own safe-reference grammar, re-stated here so this
#: contract validates the refs it hands to that authority.  A drift test asserts
#: this pattern still matches ``local_agent_broker_pairing._SAFE_REF_RE``.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PAIRING_CODE_RE = re.compile(rf"^[0-9a-f]{{{PAIRING_CODE_HEX_CHARS}}}$")

#: The one-time enrollment-code length, referenced from the canonical pairing
#: authority instead of being re-declared.
ENROLLMENT_CODE_HEX_CHARS = PAIRING_CODE_HEX_CHARS

# --- reused authorities (names only; nothing is duplicated) -------------------
CANONICAL_IDENTITY_AUTHORITY = "control_plane.identity_authority.AuthSessionSnapshot"
CANONICAL_SESSION_RESOLVER = "control_plane.resolve_current_auth_session"
CANONICAL_PRODUCT_REGISTRY = "identity_authority.allowed_product_ids"
CANONICAL_SCOPE_AUTHORITY = "control_plane.padiem_connector_enrollment.CanonicalEnrollmentScopePort"
CANONICAL_PAIRING_AUTHORITY = (
    "padiem_control_plane.local_agent_broker_pairing.InMemoryBrokerPairingAuthority"
)
CANONICAL_BINDING_AUTHORITY = (
    "padiem_control_plane.local_agent_broker.InMemoryLocalAgentBrokerAuthority.register_binding"
)
CANONICAL_ROTATION_AUTHORITY = (
    "padiem_control_plane.local_agent_broker.InMemoryLocalAgentBrokerAuthority.rotate_credential"
)
CANONICAL_REVOCATION_AUTHORITY = (
    "padiem_control_plane.local_agent_broker.InMemoryLocalAgentBrokerAuthority.revoke_binding"
)
DEVICE_LIFECYCLE_AUTHORITY = "kagent.local_agent_pairing"
ONLINE_PROOF_AUTHORITY = "canonical_broker_fresh_online_projection"
ENROLLMENT_SURFACE_OWNER = "control_plane.padiem_connector_enrollment"

SECOND_LOGIN_SYSTEM = False
SECOND_DEVICE_DB = False
SECOND_PAIRING_AUTHORITY = False
SECOND_DEVICE_AUTHORITY = False
SECOND_CREDENTIAL_STORE = False
SECOND_ROTATION_AUTHORITY = False
SECOND_REVOCATION_AUTHORITY = False
NEW_AUTHORITY_CREATED = False
NEW_AUTH_METHOD_INVENTED = False

# --- enrollment consent is NOT execution approval -----------------------------
#: Initial device enrollment consent and READ/WRITE execution approval are two
#: different decisions with two different owners.  Consenting to enroll a PC
#: never grants a file read, a file write or a command execution.
ENROLLMENT_CONSENT_REQUIRED = True
ENROLLMENT_CONSENT_IS_EXECUTION_APPROVAL = False
ENROLLMENT_CONSENT_GRANTS_READ = False
ENROLLMENT_CONSENT_GRANTS_WRITE = False
ENROLLMENT_CONSENT_GRANTS_DISPATCH = False
EXECUTION_APPROVAL_OWNER = P01_APPROVAL_OWNER
EXECUTION_APPROVAL_SEPARATE_FROM_ENROLLMENT = True
EXECUTION_APPROVAL_MINTED_HERE = False

# --- one PC id shared by every product ---------------------------------------
#: Enrollment is owner-scoped and product-neutral, so a second product re-using
#: the same physical PC is a *duplicate* registration the canonical Broker
#: refuses — never a second binding.
PRODUCT_SCOPED_ENROLLMENT = False
SHARED_DEVICE_IDENTITY_ACROSS_PRODUCTS = True
DEVICE_REENROLLMENT_WITHOUT_REVOKE_ALLOWED = False
CANONICAL_DUPLICATE_BINDING_REFUSAL = "duplicate_device_binding"

# --- ownership proof ----------------------------------------------------------
#: Device ownership is proven by possession of the one-time enrollment code
#: (the canonical HMAC-SHA256 pairing proof), never by a self-asserted device id.
DEVICE_POSSESSION_PROOF_REQUIRED = True
SELF_ASSERTED_DEVICE_OWNERSHIP = False
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
PROOF_TRANSCRIPT = PAIRING_PROOF_TRANSCRIPT

# --- posture (unchanged from #4429) ------------------------------------------
#: This slice keeps the shipped product default OFF and authorizes no execution.
PRODUCT_PC_ACCESS_DEFAULT_UNCHANGED = PRODUCT_PC_ACCESS_DEFAULT == "off"
DISPATCH_AUTHORIZED_BY_THIS_CONTRACT = False
PC_EXECUTION_PATH_NEWLY_WIRED = False
PRODUCTION_ACTIVATION = False
PRODUCTION_READY = False

# --- bounded refusal vocabulary ----------------------------------------------
#: Every refusal this contract reports is one of its own bounded reasons.  The
#: canonical pairing / Broker ``error.code`` / ``error.message`` text is mapped,
#: never echoed.
ENROLLMENT_REASON_ELIGIBLE = "enrollment_eligible"
ENROLLMENT_REASON_SESSION_REQUIRED = "canonical_session_required"
ENROLLMENT_REASON_SESSION_INACTIVE = "canonical_session_inactive"
ENROLLMENT_REASON_SUBJECT_NOT_USER = "canonical_subject_not_user"
ENROLLMENT_REASON_TENANT_REQUIRED = "canonical_tenant_required"
ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED = "canonical_session_product_not_reviewed"
ENROLLMENT_REASON_SCOPE_UNAVAILABLE = "enrollment_scope_unavailable"
ENROLLMENT_REASON_SCOPE_UNVERIFIED = "enrollment_scope_unverified"
ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH = "enrollment_scope_owner_mismatch"
ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE = "enrollment_scope_product_scoped_denied"
ENROLLMENT_REASON_CONSENT_REQUIRED = "enrollment_consent_required"
ENROLLMENT_REASON_CONSENT_WITHDRAWN = "enrollment_consent_withdrawn"
ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH = "enrollment_consent_scope_mismatch"
#: A canonical dependency refused/unavailable (e.g. an unconfigured pairing
#: authority).  Reported as its own bounded reason instead of a raw RuntimeError.
ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE = "enrollment_dependency_unavailable"

#: Canonical pairing / Broker refusal codes accepted as inputs, mapped to this
#: contract's bounded reasons.  The mapping is deliberately a closed table: an
#: unrecognised canonical code becomes ``enrollment_dependency_refused`` instead
#: of leaking upstream text.
ENROLLMENT_REFUSAL_BY_CANONICAL_CODE: dict[str, str] = {
    "pairing_challenge_not_found": "enrollment_challenge_not_found",
    "pairing_challenge_expired": "enrollment_challenge_expired",
    "pairing_challenge_already_redeemed": "enrollment_duplicate_redeem_denied",
    "invalid_pairing_proof": "enrollment_proof_invalid",
    "invalid_pairing_code": "enrollment_proof_invalid",
    "pairing_issuance_rate_limited": "enrollment_rate_limited",
    "pairing_issuance_scope_capacity_exhausted": "enrollment_rate_limited",
    "pairing_capacity_exhausted": "enrollment_capacity_exhausted",
    "duplicate_device_binding": "enrollment_duplicate_device_denied",
    "device_binding_revoked": "enrollment_binding_revoked_denied",
    "device_credential_expired": "enrollment_credential_expired_denied",
    "invalid_device_credential": "enrollment_proof_invalid",
}
ENROLLMENT_REFUSAL_FALLBACK = "enrollment_dependency_refused"
REFUSAL_TEXT_ECHOED = False

#: Unsupported Connector authentication methods, recorded as **dependencies**.
#: Each entry is ``(method, why it is not implemented here)``.  No device-code
#: flow, client-certificate identity or federated login is invented by this
#: slice; the Connector must present an existing canonical PADIEM session.
UNSUPPORTED_AUTH_METHODS: tuple[tuple[str, str], ...] = (
    (
        "oidc_device_authorization_grant_rfc8628",
        "no canonical server-side device-code authority exists; the Connector must present an existing PADIEM session",
    ),
    (
        "mtls_client_certificate_identity",
        "no canonical certificate identity authority exists",
    ),
    (
        "saml_or_sso_federation",
        "no canonical federation authority exists",
    ),
    (
        "connector_local_password_store",
        "the Connector must never hold a PADIEM password; identity stays server-side",
    ),
)
UNSUPPORTED_AUTH_METHOD_COUNT = len(UNSUPPORTED_AUTH_METHODS)


def _safe_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_connector_enrollment_reference",
            f"{label} must be a bounded safe reference",
        )
    return value


def _aware(value: Any, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_connector_enrollment_timestamp",
            f"{label} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


def _positive_int(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ControlPlaneContractError(
            "invalid_connector_enrollment_value",
            f"{label} must be an integer between {minimum} and {maximum} without coercion",
        )
    return value


@dataclass(frozen=True, slots=True)
class ConnectorEnrollmentScope:
    """The server-owned, product-neutral scope one PC is enrolled under.

    ``account_ref`` / ``workspace_ref`` come from the injected Control Plane
    owner resolver, never from the Connector, the browser or a product route.
    ``product_scoped`` exists so a resolver cannot quietly hand this contract a
    per-product scope: one physical PC must carry exactly one canonical binding
    that every product resolves to the same device id.
    """

    owner_subject_id: str
    account_ref: str
    workspace_ref: str
    product_scoped: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.owner_subject_id, str)
            or not self.owner_subject_id.strip()
            or len(self.owner_subject_id) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in self.owner_subject_id)
        ):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_scope",
                "owner_subject_id must be a bounded canonical identifier",
            )
        object.__setattr__(self, "account_ref", _safe_ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        if self.product_scoped is not False:
            raise ControlPlaneContractError(
                ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE,
                "connector enrollment scope must be product-neutral",
            )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "owner_subject_ref": _owner_ref(self.owner_subject_id),
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "product_scoped": False,
            "shared_by_products": True,
            "client_asserted": False,
        }


def _owner_ref(owner_subject_id: str) -> str:
    """A stable, non-reversible owner label for support evidence.

    The canonical subject id is an opaque identifier, not a secret, but a support
    projection never needs it in the clear — and never needs the raw session id.
    """

    digest = hashlib.sha256(owner_subject_id.encode("utf-8")).hexdigest()[:16]
    return f"owner.{digest}"


class CanonicalEnrollmentScopePort(Protocol):
    """The existing Control Plane owner resolver this contract consumes.

    A deployment implements this over the canonical owner/tenant authorities.
    The contract passes only the *verified* canonical facts (subject id and, when
    present, the canonical tenant) and refuses a scope that does not belong to
    that same subject.
    """

    def resolve_scope(
        self,
        *,
        subject_id: str,
        tenant_ref: str | None,
        now: datetime,
    ) -> ConnectorEnrollmentScope:
        ...


class UnconfiguredCanonicalEnrollmentScopePort:
    """Fail-closed default: no owner resolver, no enrollment."""

    def resolve_scope(
        self,
        *,
        subject_id: str,
        tenant_ref: str | None,
        now: datetime,
    ) -> ConnectorEnrollmentScope:
        del subject_id, tenant_ref, now
        raise RuntimeError("canonical PADIEM connector enrollment scope authority is not configured")


@dataclass(frozen=True, slots=True)
class ConnectorEnrollmentConsent:
    """Explicit, revocable consent to enroll **one** computer.

    This record is the first-registration consent only.  It is not a file
    permission and not an execution approval: see the module-level
    ``ENROLLMENT_CONSENT_*`` constants.  Consent is scoped to the exact
    server-owned scope, so a consent granted for one account/workspace cannot be
    reused by another user or another workspace.
    """

    consent_id: str
    owner_subject_id: str
    account_ref: str
    workspace_ref: str
    granted_at: datetime
    withdrawn_at: datetime | None = None
    contract_version: str = CONNECTOR_ENROLLMENT_CONSENT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "consent_id", _safe_ref(self.consent_id, "consent_id"))
        if (
            not isinstance(self.owner_subject_id, str)
            or not self.owner_subject_id.strip()
            or len(self.owner_subject_id) > 256
        ):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_consent",
                "owner_subject_id must be a bounded canonical identifier",
            )
        object.__setattr__(self, "account_ref", _safe_ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "workspace_ref", _safe_ref(self.workspace_ref, "workspace_ref"))
        granted = _aware(self.granted_at, "granted_at")
        object.__setattr__(self, "granted_at", granted)
        if self.withdrawn_at is not None:
            withdrawn = _aware(self.withdrawn_at, "withdrawn_at")
            if withdrawn < granted:
                raise ControlPlaneContractError(
                    "invalid_connector_enrollment_consent",
                    "consent withdrawal must not precede the grant",
                )
            object.__setattr__(self, "withdrawn_at", withdrawn)
        if self.contract_version != CONNECTOR_ENROLLMENT_CONSENT_VERSION:
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_consent",
                "unsupported enrollment consent version",
            )

    def is_active(self, *, now: datetime) -> bool:
        observed_at = _aware(now, "now")
        if self.withdrawn_at is not None and observed_at >= self.withdrawn_at:
            return False
        return observed_at >= self.granted_at

    def matches(self, scope: ConnectorEnrollmentScope) -> bool:
        return (
            isinstance(scope, ConnectorEnrollmentScope)
            and self.owner_subject_id == scope.owner_subject_id
            and self.account_ref == scope.account_ref
            and self.workspace_ref == scope.workspace_ref
        )

    def safe_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "consent_id": self.consent_id,
            "owner_subject_ref": _owner_ref(self.owner_subject_id),
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "granted_at": _iso(self.granted_at),
            "withdrawn_at": _iso(self.withdrawn_at) if self.withdrawn_at is not None else None,
            "contract_version": self.contract_version,
            "enrollment_consent": True,
            "execution_approval": False,
            "grants_read": False,
            "grants_write": False,
            "execution_approval_owner": EXECUTION_APPROVAL_OWNER,
        }
        if now is not None:
            payload["consent_active"] = self.is_active(now=now)
        return payload


@dataclass(frozen=True, slots=True)
class ConnectorEnrollmentDecision:
    """Bounded, secret-free enrollment eligibility decision.

    ``eligible`` means *the canonical preconditions this contract can check
    passed* — nothing more.  It is not a device registration, not a file
    permission and not an execution authorization:
    ``dispatch_authorized`` is a property that always returns ``False``.
    """

    eligible: bool
    reason: str
    scope: ConnectorEnrollmentScope | None = None
    consent_id: str | None = None

    @property
    def dispatch_authorized(self) -> bool:
        return False

    @property
    def creates_login(self) -> bool:
        return False

    @property
    def creates_device_registry(self) -> bool:
        return False

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
            "eligible": self.eligible,
            "reason": self.reason,
            "scope": None if self.scope is None else self.scope.safe_dict(),
            "consent_id": self.consent_id,
            "dispatch_authorized": False,
            "creates_login": False,
            "creates_device_registry": False,
            "execution_approval_minted": False,
            "execution_approval_owner": EXECUTION_APPROVAL_OWNER,
            "product_scoped_enrollment": False,
        }


def _decision(
    *,
    eligible: bool,
    reason: str,
    scope: ConnectorEnrollmentScope | None = None,
    consent_id: str | None = None,
) -> ConnectorEnrollmentDecision:
    return ConnectorEnrollmentDecision(
        eligible=eligible,
        reason=reason,
        scope=scope,
        consent_id=consent_id,
    )


def evaluate_connector_enrollment(
    *,
    auth_session: Any,
    allowed_product_ids: Any,
    scope_resolver: CanonicalEnrollmentScopePort,
    consent: ConnectorEnrollmentConsent | None,
    now: datetime,
) -> ConnectorEnrollmentDecision:
    """Decide whether this verified PADIEM account may enroll a computer now.

    The chain, in order, refusing on the first failure:

    1. a canonical :class:`AuthSessionSnapshot` is present;
    2. it is effective ACTIVE at ``now`` (a revoked or expired session is
       refused, so a withdrawn sign-in cannot enroll and an account change
       cannot reuse an old session);
    3. its subject is a ``USER`` — never a machine or account pseudo-subject;
    4. it carries a canonical tenant;
    5. its ``product_id`` is one of the canonical reviewed product ids supplied
       by the existing identity authority (this contract declares no second
       product registry);
    6. the injected owner resolver returns a server-owned scope **for that same
       subject**, and the scope is product-neutral;
    7. an active enrollment consent exists and is scoped to exactly that same
       owner/account/workspace.

    The Connector supplies none of these facts.  The device id is deliberately
    absent from this decision: it is proven later, by the one-time enrollment
    code, and never asserted by the caller.
    """

    observed_at = _aware(now, "now")

    if not isinstance(auth_session, AuthSessionSnapshot):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SESSION_REQUIRED)
    if auth_session.effective_state(now=observed_at) is not AuthSessionState.ACTIVE:
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SESSION_INACTIVE)
    if auth_session.subject.subject_type is not SubjectType.USER:
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SUBJECT_NOT_USER)
    if not auth_session.tenant_id:
        return _decision(eligible=False, reason=ENROLLMENT_REASON_TENANT_REQUIRED)
    if (
        not isinstance(allowed_product_ids, frozenset)
        or not allowed_product_ids
        or auth_session.product_id not in allowed_product_ids
    ):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED)

    try:
        scope = scope_resolver.resolve_scope(
            subject_id=auth_session.subject.subject_id,
            tenant_ref=auth_session.tenant_id,
            now=observed_at,
        )
    except ControlPlaneContractError as exc:
        if exc.code == ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE:
            return _decision(eligible=False, reason=ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE)
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SCOPE_UNAVAILABLE)
    except (RuntimeError, KeyError, TypeError, ValueError):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SCOPE_UNAVAILABLE)

    if not isinstance(scope, ConnectorEnrollmentScope):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SCOPE_UNVERIFIED)
    # Another user's scope can never be consumed by this session: the resolver is
    # a dependency, so its answer is re-checked rather than trusted.
    if scope.owner_subject_id != auth_session.subject.subject_id:
        return _decision(eligible=False, reason=ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH)

    if consent is None:
        return _decision(eligible=False, reason=ENROLLMENT_REASON_CONSENT_REQUIRED)
    if not isinstance(consent, ConnectorEnrollmentConsent):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_CONSENT_REQUIRED)
    if not consent.is_active(now=observed_at):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_CONSENT_WITHDRAWN)
    if not consent.matches(scope):
        return _decision(eligible=False, reason=ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH)

    return _decision(
        eligible=True,
        reason=ENROLLMENT_REASON_ELIGIBLE,
        scope=scope,
        consent_id=consent.consent_id,
    )


def _require_eligible(decision: ConnectorEnrollmentDecision) -> ConnectorEnrollmentScope:
    if not decision.eligible or decision.scope is None:
        raise ControlPlaneContractError(decision.reason, "connector enrollment is not eligible")
    return decision.scope


def _refusal_code(canonical_code: Any) -> str:
    """Map one canonical pairing/Broker refusal code to this contract's reason.

    Unrecognised codes become ``enrollment_dependency_refused``; the upstream
    code text is never returned to a caller.
    """

    if isinstance(canonical_code, str):
        return ENROLLMENT_REFUSAL_BY_CANONICAL_CODE.get(canonical_code, ENROLLMENT_REFUSAL_FALLBACK)
    return ENROLLMENT_REFUSAL_FALLBACK


def enrollment_refusal_reason(canonical_code: Any) -> str:
    """Public, bounded projection of :func:`_refusal_code` for callers/tests."""

    return _refusal_code(canonical_code)


@dataclass(frozen=True, slots=True)
class ConnectorEnrollmentChallengeReceipt:
    """One server-issued enrollment challenge, plus its one-time code.

    ``pairing_code`` is a credential: it is returned exactly once, is never part
    of :meth:`safe_dict`, and must never be logged or persisted by a caller.
    """

    challenge: BrokerPairingChallenge
    pairing_code: str
    scope: ConnectorEnrollmentScope
    consent_id: str
    owner_subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.challenge, BrokerPairingChallenge):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_challenge",
                "challenge must be BrokerPairingChallenge",
            )
        if not isinstance(self.pairing_code, str) or not _PAIRING_CODE_RE.fullmatch(self.pairing_code):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_challenge",
                "pairing code must be canonical lowercase hexadecimal enrollment-code text",
            )
        if not isinstance(self.scope, ConnectorEnrollmentScope):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_challenge",
                "scope must be ConnectorEnrollmentScope",
            )
        if (
            self.challenge.account_ref != self.scope.account_ref
            or self.challenge.workspace_ref != self.scope.workspace_ref
        ):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_challenge",
                "challenge escaped the server-derived enrollment scope",
            )

    @property
    def expires_at(self) -> datetime:
        return self.challenge.expires_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
            "challenge": self.challenge.safe_dict(),
            "scope": self.scope.safe_dict(),
            "consent_id": self.consent_id,
            "owner_subject_ref": _owner_ref(self.owner_subject_id),
            "expires_at": _iso(self.challenge.expires_at),
            "pairing_code": None,
            "pairing_code_returned_once": True,
            "pairing_code_is_a_credential": True,
            "proof_transcript": PROOF_TRANSCRIPT,
            "device_possession_proof_required": True,
            "execution_approval_minted": False,
            "dispatch_authorized": False,
        }


def issue_connector_enrollment_challenge(
    *,
    auth_session: Any,
    allowed_product_ids: Any,
    scope_resolver: CanonicalEnrollmentScopePort,
    consent: ConnectorEnrollmentConsent | None,
    pairing_authority: BrokerPairingAuthorityPort,
    now: datetime,
    ttl_seconds: int = MAX_PAIRING_TTL_SECONDS,
) -> ConnectorEnrollmentChallengeReceipt:
    """Issue one enrollment challenge for the verified account's own scope.

    This is the integration path CENTRAL wires: the Connector asks the Control
    Plane for an enrollment, and this contract turns the *verified canonical
    session* into the (account, workspace) scope the canonical pairing authority
    requires.  A Connector, a browser or a product route can never supply that
    scope, so a signed-in account cannot enroll another account's or another
    workspace's computer.
    """

    observed_at = _aware(now, "now")
    decision = evaluate_connector_enrollment(
        auth_session=auth_session,
        allowed_product_ids=allowed_product_ids,
        scope_resolver=scope_resolver,
        consent=consent,
        now=observed_at,
    )
    scope = _require_eligible(decision)
    assert decision.consent_id is not None
    ttl = _positive_int(
        ttl_seconds,
        "ttl_seconds",
        minimum=MIN_PAIRING_TTL_SECONDS,
        maximum=MAX_PAIRING_TTL_SECONDS,
    )

    for method_name in ("issue_challenge", "redeem"):
        if not callable(getattr(pairing_authority, method_name, None)):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_authority",
                "pairing authority must implement issue_challenge and redeem",
            )

    try:
        challenge, pairing_code = pairing_authority.issue_challenge(
            account_ref=scope.account_ref,
            workspace_ref=scope.workspace_ref,
            now=observed_at,
            ttl_seconds=ttl,
        )
    except ControlPlaneContractError as exc:
        raise ControlPlaneContractError(
            _refusal_code(exc.code),
            "canonical pairing authority refused the enrollment challenge",
        ) from exc
    except RuntimeError as exc:
        raise ControlPlaneContractError(
            ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE,
            "canonical pairing authority is unavailable",
        ) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlPlaneContractError(
            ENROLLMENT_REFUSAL_FALLBACK,
            "canonical pairing authority refused the enrollment challenge",
        ) from exc

    return ConnectorEnrollmentChallengeReceipt(
        challenge=challenge,
        pairing_code=pairing_code,
        scope=scope,
        consent_id=decision.consent_id,
        owner_subject_id=auth_session.subject.subject_id,
    )


@dataclass(frozen=True, slots=True)
class ConnectorEnrollmentReceipt:
    """One redeemed enrollment, bound to the canonical Broker binding.

    The raw device credential is returned exactly once and is never part of
    :meth:`safe_dict`.  The receipt is a *registration* fact: it is not an
    execution approval, and the device's lifecycle/ONLINE state stays with the
    canonical ``kagent.local_agent_pairing`` / server projection authorities.
    """

    enrollment: BrokerPairingEnrollment
    credential: bytes
    scope: ConnectorEnrollmentScope
    consent_id: str
    owner_subject_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.enrollment, BrokerPairingEnrollment):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_receipt",
                "enrollment must be BrokerPairingEnrollment",
            )
        if not isinstance(self.credential, bytes) or not self.credential:
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_receipt",
                "device credential must be non-empty bytes",
            )
        if not isinstance(self.scope, ConnectorEnrollmentScope):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_receipt",
                "scope must be ConnectorEnrollmentScope",
            )
        if (
            self.enrollment.account_ref != self.scope.account_ref
            or self.enrollment.workspace_ref != self.scope.workspace_ref
        ):
            raise ControlPlaneContractError(
                "invalid_connector_enrollment_receipt",
                "enrollment escaped the server-derived enrollment scope",
            )

    @property
    def binding_ref(self) -> str:
        return self.enrollment.binding_ref

    @property
    def device_id(self) -> str:
        return self.enrollment.device_id

    @property
    def credential_generation(self) -> int:
        return self.enrollment.credential_generation

    @property
    def credential_expires_at(self) -> datetime:
        return self.enrollment.credential_expires_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
            "enrollment": self.enrollment.safe_dict(),
            "scope": self.scope.safe_dict(),
            "consent_id": self.consent_id,
            "owner_subject_ref": _owner_ref(self.owner_subject_id),
            "device_id": self.enrollment.device_id,
            "binding_ref": self.enrollment.binding_ref,
            "credential_generation": self.enrollment.credential_generation,
            "credential_expires_at": _iso(self.enrollment.credential_expires_at),
            "credential_returned_once": True,
            "raw_device_credential": False,
            "product_scoped_enrollment": False,
            "shared_device_identity": True,
            "device_lifecycle_authority": DEVICE_LIFECYCLE_AUTHORITY,
            "online_proof_authority": ONLINE_PROOF_AUTHORITY,
            "rotation_authority": CANONICAL_ROTATION_AUTHORITY,
            "revocation_authority": CANONICAL_REVOCATION_AUTHORITY,
            "execution_approval_minted": False,
            "grants_read": False,
            "grants_write": False,
            "execution_approval_owner": EXECUTION_APPROVAL_OWNER,
            "dispatch_authorized": False,
        }


def redeem_connector_enrollment(
    *,
    auth_session: Any,
    allowed_product_ids: Any,
    scope_resolver: CanonicalEnrollmentScopePort,
    consent: ConnectorEnrollmentConsent | None,
    pairing_authority: BrokerPairingAuthorityPort,
    challenge_id: Any,
    device_id: Any,
    proof_ref: Any,
    now: datetime,
) -> ConnectorEnrollmentReceipt:
    """Redeem one enrollment challenge into a canonical Broker binding.

    The verified session and the enrollment consent are re-checked **at
    redemption time**, not only at issuance: a session revoked or a consent
    withdrawn in between refuses the redemption.  The device id is proven by the
    canonical one-time code proof (``proof_ref``) and is never trusted as a
    self-asserted ownership claim.
    """

    observed_at = _aware(now, "now")
    challenge_id = _safe_ref(challenge_id, "challenge_id")
    device_id = _safe_ref(device_id, "device_id")
    if not isinstance(proof_ref, str) or not PROOF_REF_RE.fullmatch(proof_ref):
        raise ControlPlaneContractError(
            "enrollment_proof_invalid",
            "device ownership proof must be a canonical HMAC-SHA256 proof reference",
        )

    decision = evaluate_connector_enrollment(
        auth_session=auth_session,
        allowed_product_ids=allowed_product_ids,
        scope_resolver=scope_resolver,
        consent=consent,
        now=observed_at,
    )
    scope = _require_eligible(decision)
    assert decision.consent_id is not None

    try:
        enrollment, credential = pairing_authority.redeem(
            challenge_id=challenge_id,
            device_id=device_id,
            proof_ref=proof_ref,
            now=observed_at,
        )
    except ControlPlaneContractError as exc:
        raise ControlPlaneContractError(
            _refusal_code(exc.code),
            "canonical pairing authority refused the enrollment redemption",
        ) from exc
    except RuntimeError as exc:
        raise ControlPlaneContractError(
            ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE,
            "canonical pairing authority is unavailable",
        ) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlPlaneContractError(
            ENROLLMENT_REFUSAL_FALLBACK,
            "canonical pairing authority refused the enrollment redemption",
        ) from exc

    if not isinstance(enrollment, BrokerPairingEnrollment):
        raise ControlPlaneContractError(
            "enrollment_dependency_refused",
            "canonical pairing authority returned an invalid enrollment",
        )
    if enrollment.device_id != device_id or enrollment.challenge_id != challenge_id:
        raise ControlPlaneContractError(
            "enrollment_dependency_refused",
            "canonical enrollment does not correlate with the redeemed challenge",
        )
    if (
        enrollment.account_ref != scope.account_ref
        or enrollment.workspace_ref != scope.workspace_ref
    ):
        raise ControlPlaneContractError(
            ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH,
            "canonical enrollment escaped the server-derived enrollment scope",
        )
    if not isinstance(credential, bytes) or not credential:
        raise ControlPlaneContractError(
            "enrollment_dependency_refused",
            "canonical pairing authority returned invalid credential material",
        )

    return ConnectorEnrollmentReceipt(
        enrollment=enrollment,
        credential=credential,
        scope=scope,
        consent_id=decision.consent_id,
        owner_subject_id=auth_session.subject.subject_id,
    )


def connector_enrollment_dependencies() -> dict[str, Any]:
    """Secret-free declaration of what this contract reuses and what it lacks.

    The unsupported authentication methods are recorded, not implemented: this
    slice must not invent an authentication mechanism the server does not
    support, so the gap is surfaced as an explicit dependency instead.
    """

    return {
        "contract_version": CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
        "canonical_identity_authority": CANONICAL_IDENTITY_AUTHORITY,
        "canonical_session_resolver": CANONICAL_SESSION_RESOLVER,
        "canonical_product_registry": CANONICAL_PRODUCT_REGISTRY,
        "canonical_scope_authority": CANONICAL_SCOPE_AUTHORITY,
        "canonical_pairing_authority": CANONICAL_PAIRING_AUTHORITY,
        "canonical_binding_authority": CANONICAL_BINDING_AUTHORITY,
        "canonical_rotation_authority": CANONICAL_ROTATION_AUTHORITY,
        "canonical_revocation_authority": CANONICAL_REVOCATION_AUTHORITY,
        "device_lifecycle_authority": DEVICE_LIFECYCLE_AUTHORITY,
        "online_proof_authority": ONLINE_PROOF_AUTHORITY,
        "execution_approval_owner": EXECUTION_APPROVAL_OWNER,
        "second_login_system": False,
        "second_device_db": False,
        "second_pairing_authority": False,
        "second_credential_store": False,
        "second_rotation_authority": False,
        "second_revocation_authority": False,
        "new_authority_created": False,
        "new_auth_method_invented": False,
        "unsupported_auth_methods": [
            {"method": method, "dependency": reason} for method, reason in UNSUPPORTED_AUTH_METHODS
        ],
        "unsupported_auth_method_count": UNSUPPORTED_AUTH_METHOD_COUNT,
        "enrollment_consent_required": True,
        "enrollment_consent_is_execution_approval": False,
        "product_scoped_enrollment": False,
        "shared_device_identity_across_products": True,
        "dispatch_authorized": False,
        "production_activation": False,
    }


def connector_enrollment_boundary() -> dict[str, Any]:
    """The flat posture projection asserted by the regression tests."""

    return {
        "contract_version": CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
        "product_pc_access_default": PRODUCT_PC_ACCESS_DEFAULT,
        "product_scoped_enrollment": PRODUCT_SCOPED_ENROLLMENT,
        "shared_device_identity_across_products": SHARED_DEVICE_IDENTITY_ACROSS_PRODUCTS,
        "enrollment_consent_required": ENROLLMENT_CONSENT_REQUIRED,
        "enrollment_consent_is_execution_approval": ENROLLMENT_CONSENT_IS_EXECUTION_APPROVAL,
        "enrollment_consent_grants_read": ENROLLMENT_CONSENT_GRANTS_READ,
        "enrollment_consent_grants_write": ENROLLMENT_CONSENT_GRANTS_WRITE,
        "enrollment_consent_grants_dispatch": ENROLLMENT_CONSENT_GRANTS_DISPATCH,
        "execution_approval_owner": EXECUTION_APPROVAL_OWNER,
        "execution_approval_minted_here": EXECUTION_APPROVAL_MINTED_HERE,
        "device_possession_proof_required": DEVICE_POSSESSION_PROOF_REQUIRED,
        "self_asserted_device_ownership": SELF_ASSERTED_DEVICE_OWNERSHIP,
        "self_asserted_account_workspace_authority": SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY,
        "second_login_system": SECOND_LOGIN_SYSTEM,
        "second_device_db": SECOND_DEVICE_DB,
        "second_pairing_authority": SECOND_PAIRING_AUTHORITY,
        "second_device_authority": SECOND_DEVICE_AUTHORITY,
        "second_credential_store": SECOND_CREDENTIAL_STORE,
        "second_rotation_authority": SECOND_ROTATION_AUTHORITY,
        "second_revocation_authority": SECOND_REVOCATION_AUTHORITY,
        "new_authority_created": NEW_AUTHORITY_CREATED,
        "new_auth_method_invented": NEW_AUTH_METHOD_INVENTED,
        "dispatch_authorized_by_this_contract": DISPATCH_AUTHORIZED_BY_THIS_CONTRACT,
        "pc_execution_path_newly_wired": PC_EXECUTION_PATH_NEWLY_WIRED,
        "production_activation": PRODUCTION_ACTIVATION,
        "production_ready": PRODUCTION_READY,
        "refusal_text_echoed": REFUSAL_TEXT_ECHOED,
    }


__all__ = [
    "CANONICAL_BINDING_AUTHORITY",
    "CANONICAL_IDENTITY_AUTHORITY",
    "CANONICAL_PAIRING_AUTHORITY",
    "CANONICAL_PRODUCT_REGISTRY",
    "CANONICAL_REVOCATION_AUTHORITY",
    "CANONICAL_ROTATION_AUTHORITY",
    "CANONICAL_SCOPE_AUTHORITY",
    "CONNECTOR_ENROLLMENT_CONSENT_VERSION",
    "CONNECTOR_ENROLLMENT_CONTRACT_VERSION",
    "CanonicalEnrollmentScopePort",
    "ConnectorEnrollmentChallengeReceipt",
    "ConnectorEnrollmentConsent",
    "ConnectorEnrollmentDecision",
    "ConnectorEnrollmentReceipt",
    "ConnectorEnrollmentScope",
    "DEVICE_LIFECYCLE_AUTHORITY",
    "ENROLLMENT_REASON_CONSENT_REQUIRED",
    "ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH",
    "ENROLLMENT_REASON_CONSENT_WITHDRAWN",
    "ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE",
    "ENROLLMENT_REASON_ELIGIBLE",
    "ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED",
    "ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE",
    "ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH",
    "ENROLLMENT_REASON_SCOPE_UNAVAILABLE",
    "ENROLLMENT_REASON_SCOPE_UNVERIFIED",
    "ENROLLMENT_REASON_SESSION_INACTIVE",
    "ENROLLMENT_REASON_SESSION_REQUIRED",
    "ENROLLMENT_REASON_SUBJECT_NOT_USER",
    "ENROLLMENT_REASON_TENANT_REQUIRED",
    "ENROLLMENT_REFUSAL_BY_CANONICAL_CODE",
    "ENROLLMENT_REFUSAL_FALLBACK",
    "ONLINE_PROOF_AUTHORITY",
    "UNSUPPORTED_AUTH_METHODS",
    "UnconfiguredCanonicalEnrollmentScopePort",
    "connector_enrollment_boundary",
    "connector_enrollment_dependencies",
    "enrollment_refusal_reason",
    "evaluate_connector_enrollment",
    "issue_connector_enrollment_challenge",
    "redeem_connector_enrollment",
]
