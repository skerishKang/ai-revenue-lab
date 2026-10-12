"""#4139 CENTRAL server integration seam for S1 enrollment (HOLD / no live binding).

This module composes the existing S1 canonical enrollment functions; it does
NOT authenticate a user, create a device registry/consent store, expose an HTTP
route, or provision a device credential. Those authorities belong to the
existing host and Broker. A missing authority MUST refuse before mint/mutation.

Issuance: server-resolved current session -> canonical durable consent ->
S1 issue -> server-only challenge/session continuity record.
Redemption: challenge -> SERVER-OWNED session continuity -> S1 binding ->
fresh durable consent -> credential sink preflight -> S1 scoped redemption ->
ONE-TIME delivery into an existing protected credential store.

The Connector passes only challenge_id, device_id, proof_ref for redemption.
In particular, it never supplies auth_session, consent, owner or workspace.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Protocol

from .auth_sessions import AuthSessionSnapshot
from .contracts import ControlPlaneContractError
from .padiem_connector_enrollment import (
    CanonicalEnrollmentScopePort,
    ConnectorEnrollmentChallengeReceipt,
    ConnectorEnrollmentConsent,
    ConnectorEnrollmentReceipt,
    issue_connector_enrollment_challenge,
    redeem_connector_enrollment,
)

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
SERVER_ENROLLMENT_HTTP_BOUND = False
DURABLE_CONSENT_AUTHORITY_WIRED = False
CANONICAL_SESSION_CONTINUITY_WIRED = False
PROTECTED_CREDENTIAL_HANDOFF_WIRED = False
PRODUCTION_ACTIVATION = False


def _ref(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF.fullmatch(value) is None:
        raise ControlPlaneContractError("connector_enrollment_invalid_request", f"invalid {name}")
    return value


def _now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError("connector_enrollment_invalid_time", "server timestamp required")
    return value


def _missing() -> ControlPlaneContractError:
    return ControlPlaneContractError(
        "enrollment_server_dependency_unavailable",
        "reviewed server enrollment authorities are not wired",
    )


class DurableEnrollmentConsentAuthority(Protocol):
    """Adapter over the EXISTING canonical durable consent grant/revoke store.

    No second database is created by this protocol. The two reads MUST observe
    the same authoritative record (including withdrawal) at their call times.
    """

    def current_for_device(
        self, *, owner_subject_id: str, device_id: str, now: datetime
    ) -> ConnectorEnrollmentConsent | None: ...

    def current_consent(
        self, *, consent_id: str, now: datetime
    ) -> ConnectorEnrollmentConsent | None: ...


class CanonicalSessionContinuityAuthority(Protocol):
    """SERVER-ONLY persisted issuance/session relationship, not a bearer token.

    The issuing web session is captured server-side. At redemption the server
    re-resolves its CURRENT state, including expiration and revocation. The
    unauthenticated Connector cannot provide or select any session identifier.
    """

    def bind_challenge(
        self, *, challenge_id: str, session: AuthSessionSnapshot, expires_at: datetime,
        now: datetime
    ) -> None: ...

    def current_session(
        self, *, challenge_id: str, now: datetime
    ) -> AuthSessionSnapshot | None: ...


class ProtectedDeviceCredentialHandoff(Protocol):
    """Existing canonical device credential authority / trusted transport only.

    The sink must prove authenticated destination + capability BEFORE the
    irreversible Broker registration, then install the returned raw credential
    exactly once in the EXISTING protected device credential store. Never log,
    publish, persist into enrollment.json or return it in a safe HTTP projection.
    """

    def ready(
        self, *, challenge_id: str, device_id: str, now: datetime
    ) -> bool: ...

    def deliver_once(
        self, *, challenge_id: str, device_id: str,
        credential: bytes, receipt: ConnectorEnrollmentReceipt, now: datetime
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class CanonicalServerEnrollmentResult:
    """Only metadata after protected credential handoff already succeeded."""

    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    consent_id: str
    credential_generation: int
    credential_expires_at: datetime

    def safe_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "consent_id": self.consent_id,
            "credential_generation": self.credential_generation,
            "credential_expires_at": self.credential_expires_at.isoformat(),
            "credential_installed_by_canonical_handoff": True,
            "raw_device_credential": False,
            "lifecycle": "paired_offline",
            "dispatch_authorized": False,
        }


class CanonicalConnectorEnrollmentServer:
    """Trusted host composition of the existing S1 enrollment authority.

    This server service is NOT a network listener. It may only be exposed by a
    host that verifies browser login/CSRF for issuance, TLS/gateway authenticity
    for device redemption, and derives allowed products/scope from the server.
    No capability is active until all real durable authorities are composed.
    """

    def __init__(
        self,
        *,
        allowed_product_ids: frozenset[str],
        scope_resolver: CanonicalEnrollmentScopePort | None = None,
        pairing_authority: Any = None,
        consent_authority: DurableEnrollmentConsentAuthority | None = None,
        session_authority: CanonicalSessionContinuityAuthority | None = None,
        credential_handoff: ProtectedDeviceCredentialHandoff | None = None,
    ) -> None:
        self._products = allowed_product_ids
        self._scope = scope_resolver
        self._pairing = pairing_authority
        self._consent = consent_authority
        self._session = session_authority
        self._handoff = credential_handoff

    def _dependencies(self) -> None:
        if not isinstance(self._products, frozenset) or not self._products:
            raise _missing()
        for port, methods in (
            (self._scope, ("resolve_scope",)),
            (self._pairing, ("issue_enrollment_challenge", "enrollment_binding", "redeem_enrollment")),
            (self._consent, ("current_for_device", "current_consent")),
            (self._session, ("bind_challenge", "current_session")),
            (self._handoff, ("ready", "deliver_once")),
        ):
            if port is None or any(not callable(getattr(port, name, None)) for name in methods):
                raise _missing()

    def issue(
        self, *, verified_session: AuthSessionSnapshot, device_id: str,
        now: datetime, ttl_seconds: int = 300,
    ) -> ConnectorEnrollmentChallengeReceipt:
        """Only the authenticated browser host passes its verified session."""
        self._dependencies()  # NO challenge minted when authority is absent.
        moment = _now(now)
        device = _ref(device_id, "device_id")
        if not isinstance(verified_session, AuthSessionSnapshot):
            raise ControlPlaneContractError("canonical_session_required", "server session required")
        try:
            consent = self._consent.current_for_device(
                owner_subject_id=verified_session.subject.subject_id, device_id=device, now=moment
            )
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise _missing() from exc
        receipt = issue_connector_enrollment_challenge(
            auth_session=verified_session,
            allowed_product_ids=self._products,
            scope_resolver=self._scope,
            consent=consent,
            device_id=device,
            pairing_authority=self._pairing,
            consent_liveness_authority=self._consent,
            now=moment,
            ttl_seconds=ttl_seconds,
        )
        try:
            self._session.bind_challenge(
                challenge_id=receipt.challenge.challenge_id,
                session=verified_session,
                expires_at=receipt.expires_at,
                now=moment,
            )
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            # An orphan unconsumed challenge is safe: no session lookup can
            # release it. Critically, no one-time code is disclosed on failure.
            raise _missing() from exc
        return receipt

    def redeem(
        self, *, challenge_id: str, device_id: str, proof_ref: str,
        now: datetime,
    ) -> CanonicalServerEnrollmentResult:
        """No client-side identity inputs. S1 performs final scoped mutation."""
        self._dependencies()
        moment = _now(now)
        challenge = _ref(challenge_id, "challenge_id")
        device = _ref(device_id, "device_id")
        proof = _ref(proof_ref, "proof_ref")
        try:
            session = self._session.current_session(challenge_id=challenge, now=moment)
            binding = self._pairing.enrollment_binding(challenge_id=challenge, now=moment)
        except ControlPlaneContractError:
            raise
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise _missing() from exc
        if not isinstance(session, AuthSessionSnapshot):
            raise ControlPlaneContractError("canonical_session_required", "current server session unavailable")
        if binding.device_id != device or binding.owner_ref != session.subject.subject_id:
            raise ControlPlaneContractError(
                "enrollment_device_or_owner_mismatch", "server challenge/device/owner mismatch"
            )
        # Bind lookup to the ORIGINAL consent ID rather than accepting a new
        # currently-active consent supplied from elsewhere.
        try:
            consent = self._consent.current_consent(consent_id=binding.consent_ref, now=moment)
            ready = self._handoff.ready(challenge_id=challenge, device_id=device, now=moment)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            raise _missing() from exc
        if ready is not True:
            # Fail BEFORE consuming the one-time challenge or creating a Broker
            # binding when the actual protected credential sink is unavailable.
            raise _missing()
        receipt = redeem_connector_enrollment(
            auth_session=session,
            allowed_product_ids=self._products,
            scope_resolver=self._scope,
            consent=consent,
            pairing_authority=self._pairing,
            consent_liveness_authority=self._consent,
            challenge_id=challenge,
            device_id=device,
            proof_ref=proof,
            now=moment,
        )
        try:
            delivered = self._handoff.deliver_once(
                challenge_id=challenge,
                device_id=device,
                credential=receipt.credential,
                receipt=receipt,
                now=moment,
            )
        except Exception as exc:
            # The canonical Broker binding may already have been minted. Never
            # claim success. Owner must reconcile/revoke before another attempt.
            raise ControlPlaneContractError(
                "enrollment_credential_handoff_failed", "canonical credential delivery failed"
            ) from exc
        if delivered is not True:
            raise ControlPlaneContractError(
                "enrollment_credential_handoff_failed", "canonical credential delivery was not confirmed"
            )
        return CanonicalServerEnrollmentResult(
            binding_ref=receipt.binding_ref,
            device_id=receipt.device_id,
            account_ref=receipt.scope.account_ref,
            workspace_ref=receipt.scope.workspace_ref,
            consent_id=receipt.consent_id,
            credential_generation=receipt.credential_generation,
            credential_expires_at=receipt.credential_expires_at,
        )
