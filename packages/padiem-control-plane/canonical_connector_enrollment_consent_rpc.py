"""Pure-Python private Identity DO consent RPC mixin (#4139).

This module has no Cloudflare workers/js import so the security contract can be
tested by standard CPython. Methods are invoked only through the existing
private Identity Durable Object Service Binding. They remain fail-closed unless
explicit deployment gates and the already-reviewed canonical authorities exist.
"""
from __future__ import annotations

from datetime import datetime, timezone
import secrets
from typing import Any

from canonical_connector_enrollment_durable import IdentityDurableConnectorEnrollmentRecords
from canonical_connector_scope_readonly import ReadOnlyExistingConnectorScope
from padiem_control_plane.contracts import ControlPlaneContractError, SubjectType
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentConsent

_CONNECTOR_ENROLLMENT_GRANT_KEYS = frozenset({"session_id", "device_id", "confirmed", "confirmation_version"})
_CONNECTOR_ENROLLMENT_REVOKE_KEYS = frozenset({"session_id", "consent_id", "confirmed", "confirmation_version"})
_CONNECTOR_ENROLLMENT_SCHEMA_KEYS = frozenset({"migration_id"})
_CONNECTOR_ENROLLMENT_CONFIRMATION_VERSION = "pc-enrollment-consent-v1"
_CONNECTOR_ENROLLMENT_SCHEMA_VERSION = "connector-enrollment-v1"
_CONNECTOR_CONSENT_RESOLVE_KEYS = frozenset({"session_id", "device_id"})
_CONNECTOR_CHALLENGE_BIND_KEYS = frozenset({"session_id", "challenge_id", "expires_at"})
_CONNECTOR_REDEEM_AUTHORIZE_KEYS = frozenset({
    "challenge_id", "consent_id", "device_id", "owner_ref", "account_ref", "workspace_ref",
})


def _enrollment_enrollment_safe_error(exc: ControlPlaneContractError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": exc.code, "message": "Canonical identity request was rejected"}}


def _closed(payload: Any, keys: frozenset[str], field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ControlPlaneContractError("invalid_identity_authority_rpc", f"{field_name} must contain exactly the reviewed fields")
    return payload


class CanonicalIdentityEnrollmentConsentRPC:
    def _connector_enrollment_enabled(self) -> bool:
        return (
            str(getattr(self.env, "CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED", "")).lower() == "true"
            and str(getattr(self.env, "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED", "")).lower() == "true"
            and str(getattr(self.env, "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED", "")).lower() == "true"
        )

    def _connector_session_for_consent(self, session_id: str, now: datetime):
        session = self._store.resolve_auth_session(session_id=session_id)
        if (
            session.product_id != "b54-padiem-claw"
            or session.effective_state(now=now).value != "active"
            or session.subject.subject_type is not SubjectType.USER
            or not session.tenant_id
        ):
            raise ControlPlaneContractError(
                "connector_enrollment_consent_session_denied",
                "an active canonical Padiem Claw owner session is required",
            )
        # Membership validation is server-only and shares the canonical Identity DO.
        self._store.resolve_active_tenant_membership(
            tenant_id=session.tenant_id,
            canonical_subject_id=session.subject.subject_id,
            now=now,
        )
        return session

    async def resolve_connector_enrollment_consent_for_device(self, payload: dict) -> dict:
        """Private current-consent lookup; input identity comes only from the active session."""
        try:
            wire = _closed(payload, _CONNECTOR_CONSENT_RESOLVE_KEYS, "connector enrollment consent resolve RPC")
            if not self._connector_enrollment_enabled():
                raise ControlPlaneContractError("connector_enrollment_rpc_disabled", "connector enrollment consent RPC is disabled")
            now = datetime.now(timezone.utc)
            session = self._connector_session_for_consent(wire["session_id"], now)
            scope = ReadOnlyExistingConnectorScope(
                identity_do_storage=self._storage, membership_authority=self._store
            ).resolve_scope(subject_id=session.subject.subject_id, tenant_ref=session.tenant_id, now=now)
            consent = self._connector_enrollment_records.current_for_device(
                owner_subject_id=session.subject.subject_id, device_id=wire["device_id"], now=now,
            )
            if consent is None or not consent.matches(scope) or not consent.enrolls_device(wire["device_id"]):
                raise ControlPlaneContractError("enrollment_consent_required", "current consent for this device is required")
            return {"ok": True, "consent": {
                "consent_id": consent.consent_id, "device_id": consent.device_id,
                "owner_subject_id": consent.owner_subject_id, "account_ref": consent.account_ref,
                "workspace_ref": consent.workspace_ref, "granted_at": consent.granted_at.isoformat(),
                "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None,
            }}
        except ControlPlaneContractError as exc:
            return _enrollment_safe_error(exc)

    async def bind_connector_enrollment_challenge(self, payload: dict) -> dict:
        """Persist a broker-issued challenge against the original canonical session."""
        try:
            wire = _closed(payload, _CONNECTOR_CHALLENGE_BIND_KEYS, "connector enrollment challenge bind RPC")
            if not self._connector_enrollment_enabled():
                raise ControlPlaneContractError("connector_enrollment_rpc_disabled", "connector enrollment consent RPC is disabled")
            now = datetime.now(timezone.utc)
            session = self._connector_session_for_consent(wire["session_id"], now)
            expires_at = _dt(wire["expires_at"])
            self._connector_enrollment_records.bind_challenge(
                challenge_id=wire["challenge_id"], session=session, expires_at=expires_at, now=now,
            )
            return {"ok": True, "binding": {
                "challenge_id": wire["challenge_id"], "session_id_bound": True,
                "expires_at": expires_at.isoformat(), "raw_session_id_returned": False,
            }}
        except ControlPlaneContractError as exc:
            return _enrollment_safe_error(exc)

    async def authorize_connector_enrollment_redeem(self, payload: dict) -> dict:
        """Revalidate the original session + current grant against broker-owned binding facts."""
        try:
            wire = _closed(payload, _CONNECTOR_REDEEM_AUTHORIZE_KEYS, "connector enrollment redeem authorization RPC")
            if not self._connector_enrollment_enabled():
                raise ControlPlaneContractError("connector_enrollment_rpc_disabled", "connector enrollment consent RPC is disabled")
            now = datetime.now(timezone.utc)
            session = self._connector_enrollment_records.current_session(
                challenge_id=wire["challenge_id"], now=now,
            )
            if not isinstance(session, AuthSessionSnapshot) or not session.is_active(now=now):
                raise ControlPlaneContractError("canonical_session_required", "original canonical session is no longer active")
            self._store.resolve_active_tenant_membership(
                tenant_id=session.tenant_id, canonical_subject_id=session.subject.subject_id, now=now,
            )
            scope = ReadOnlyExistingConnectorScope(
                identity_do_storage=self._storage, membership_authority=self._store
            ).resolve_scope(subject_id=session.subject.subject_id, tenant_ref=session.tenant_id, now=now)
            consent = self._connector_enrollment_records.current_consent(
                consent_id=wire["consent_id"], now=now,
            )
            if (
                consent is None or not consent.is_active(now=now)
                or consent.owner_subject_id != session.subject.subject_id
                or consent.owner_subject_id != wire["owner_ref"]
                or consent.account_ref != wire["account_ref"]
                or consent.workspace_ref != wire["workspace_ref"]
                or consent.device_id != wire["device_id"]
                or not consent.matches(scope)
            ):
                raise ControlPlaneContractError("enrollment_consent_withdrawn", "current enrollment consent no longer matches")
            return {"ok": True, "authorization": {
                "challenge_id": wire["challenge_id"], "consent_id": consent.consent_id,
                "device_id": consent.device_id, "owner_subject_id": consent.owner_subject_id,
                "account_ref": consent.account_ref, "workspace_ref": consent.workspace_ref,
                "authorized_at": now.isoformat(), "dispatch_authorized": False,
                "grants_read": False, "grants_write": False,
            }}
        except ControlPlaneContractError as exc:
            return _enrollment_safe_error(exc)

    async def install_connector_enrollment_schema(self, payload: dict) -> dict:
        """Explicit, separately gated private migration RPC; never called on startup."""
        try:
            wire = _closed(payload, _CONNECTOR_ENROLLMENT_SCHEMA_KEYS, "connector-enrollment schema RPC")
            if wire["migration_id"] != _CONNECTOR_ENROLLMENT_SCHEMA_VERSION:
                raise ControlPlaneContractError("invalid_connector_enrollment_migration", "reviewed migration id required")
            if str(getattr(self.env, "CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED", "")).lower() != "true":
                raise ControlPlaneContractError("connector_enrollment_schema_install_disabled", "explicit operator migration gate is off")
            self._connector_enrollment_records.install_schema()
            return {"ok": True, "schema": _CONNECTOR_ENROLLMENT_SCHEMA_VERSION, "installed_by_default": False}
        except ControlPlaneContractError as exc:
            return _enrollment_enrollment_safe_error(exc)

    async def grant_connector_enrollment_consent(self, payload: dict) -> dict:
        """Private RPC called only after explicit owner UI action + CSRF verification."""
        try:
            wire = _closed(payload, _CONNECTOR_ENROLLMENT_GRANT_KEYS, "connector-enrollment consent-grant RPC")
            if not self._connector_enrollment_enabled():
                raise ControlPlaneContractError("connector_enrollment_rpc_disabled", "connector enrollment consent RPC is disabled")
            if wire["confirmed"] is not True or wire["confirmation_version"] != _CONNECTOR_ENROLLMENT_CONFIRMATION_VERSION:
                raise ControlPlaneContractError("connector_enrollment_explicit_consent_required", "explicit owner consent is required")
            now = datetime.now(timezone.utc)
            session = self._connector_session_for_consent(wire["session_id"], now)
            scope = ReadOnlyExistingConnectorScope(
                identity_do_storage=self._storage, membership_authority=self._store
            ).resolve_scope(
                subject_id=session.subject.subject_id, tenant_ref=session.tenant_id, now=now
            )
            device_id = wire["device_id"]
            consent = ConnectorEnrollmentConsent(
                consent_id="consent." + secrets.token_hex(16),
                owner_subject_id=session.subject.subject_id,
                account_ref=scope.account_ref, workspace_ref=scope.workspace_ref,
                device_id=device_id, granted_at=now,
            )
            self._connector_enrollment_records.persist_preverified_consent(consent=consent, now=now)
            return {"ok": True, "consent": {
                "consent_id": consent.consent_id, "device_id": consent.device_id,
                "granted_at": consent.granted_at.isoformat(), "withdrawn_at": None,
                "dispatch_authorized": False, "grants_read": False, "grants_write": False,
            }}
        except ControlPlaneContractError as exc:
            return _enrollment_enrollment_safe_error(exc)
        except (TypeError, ValueError) as exc:
            return _enrollment_safe_error(ControlPlaneContractError("invalid_connector_enrollment_consent", "consent request was refused"))

    async def revoke_connector_enrollment_consent(self, payload: dict) -> dict:
        """Private RPC; only the currently authenticated canonical owner may revoke."""
        try:
            wire = _closed(payload, _CONNECTOR_ENROLLMENT_REVOKE_KEYS, "connector-enrollment consent-revoke RPC")
            if not self._connector_enrollment_enabled():
                raise ControlPlaneContractError("connector_enrollment_rpc_disabled", "connector enrollment consent RPC is disabled")
            if wire["confirmed"] is not True or wire["confirmation_version"] != _CONNECTOR_ENROLLMENT_CONFIRMATION_VERSION:
                raise ControlPlaneContractError("connector_enrollment_explicit_consent_required", "explicit owner revocation is required")
            now = datetime.now(timezone.utc)
            session = self._connector_session_for_consent(wire["session_id"], now)
            current = self._connector_enrollment_records.current_consent(
                consent_id=wire["consent_id"], now=now
            )
            if current is None or current.owner_subject_id != session.subject.subject_id:
                raise ControlPlaneContractError("enrollment_consent_required", "owner's current consent was not found")
            self._connector_enrollment_records.withdraw_preverified_consent(
                consent_id=wire["consent_id"], owner_subject_id=session.subject.subject_id, now=now
            )
            return {"ok": True, "consent": {
                "consent_id": current.consent_id, "device_id": current.device_id,
                "granted_at": current.granted_at.isoformat(), "withdrawn_at": now.isoformat(),
                "dispatch_authorized": False, "grants_read": False, "grants_write": False,
            }}
        except ControlPlaneContractError as exc:
            return _enrollment_enrollment_safe_error(exc)


