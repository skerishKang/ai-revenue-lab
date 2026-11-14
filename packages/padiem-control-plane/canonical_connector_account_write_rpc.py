"""Default-off account-keyed connector mutations using the shared authority judgement."""
from __future__ import annotations

from datetime import datetime, timezone
import secrets

from canonical_connector_account_rpc import (
    _ACCOUNT_KEYS, _CONTEXT_PRODUCTS, _ENROLLMENT_PRODUCTS, _refused,
    CONNECTOR_ACCOUNT_KEY_RPC_DISABLED,
)
from canonical_connector_enrollment_consent_rpc import _CONNECTOR_ENROLLMENT_CONFIRMATION_VERSION
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentConsent

CONNECTOR_ACCOUNT_KEY_WRITE_METHODS = frozenset({
    "grant_connector_enrollment_consent_for_subject",
    "revoke_connector_enrollment_consent_for_subject",
    "bind_connector_enrollment_challenge_for_subject",
    "authorize_connector_enrollment_redeem_for_subject",
    "issue_google_connect_ticket_for_subject",
})
CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH = "CONTROL_PLANE_CONNECTOR_ACCOUNT_KEY_WRITE_RPC_ENABLED"
CONNECTOR_ACCOUNT_KEY_WRITE_RPC_DISABLED = "connector_account_key_write_rpc_disabled"
_CONFIRM_KEYS = frozenset({"confirmed", "confirmation_version"})


class CanonicalIdentityAccountConnectorWriteRPC:
    def _judged_connector_write(self, payload, business_keys, *, now, enrollment=True, confirmed=False):
        if str(getattr(self.env, CONNECTOR_ACCOUNT_KEY_WRITE_RPC_SWITCH, "")).lower() != "true":
            raise ControlPlaneContractError(CONNECTOR_ACCOUNT_KEY_WRITE_RPC_DISABLED, "account-keyed writes are disabled")
        if not self._connector_account_key_rpc_enabled():
            raise ControlPlaneContractError(CONNECTOR_ACCOUNT_KEY_RPC_DISABLED, "account-keyed RPC is disabled")
        keys = _ACCOUNT_KEYS | business_keys | (_CONFIRM_KEYS if confirmed else frozenset())
        if not isinstance(payload, dict) or set(payload) != keys:
            raise ControlPlaneContractError("invalid_identity_authority_rpc", "invalid connector fields")
        if any(not isinstance(payload[key], str) or not payload[key] for key in keys - {"confirmed"}):
            raise ControlPlaneContractError("invalid_identity_authority_rpc", "invalid connector fields")
        if confirmed and (payload["confirmed"] is not True or
                          payload["confirmation_version"] != _CONNECTOR_ENROLLMENT_CONFIRMATION_VERSION):
            raise ControlPlaneContractError("connector_enrollment_explicit_consent_required", "explicit consent required")
        _, account = self._judged_connector_account(
            {key: payload[key] for key in _ACCOUNT_KEYS}, _ACCOUNT_KEYS, "connector account write",
            reviewed_products=_ENROLLMENT_PRODUCTS if enrollment else _CONTEXT_PRODUCTS,
            require_owner=enrollment, enrollment_gated=enrollment, now=now,
        )
        return account

    async def grant_connector_enrollment_consent_for_subject(self, payload):
        try:
            now = datetime.now(timezone.utc)
            account = self._judged_connector_write(payload, {"device_id"}, now=now, confirmed=True)
            scope = self._connector_scope_for_account(account, now)
            consent = ConnectorEnrollmentConsent(
                consent_id="consent." + secrets.token_hex(16), owner_subject_id=account.subject_id,
                account_ref=scope.account_ref, workspace_ref=scope.workspace_ref,
                device_id=payload["device_id"], granted_at=now,
            )
            self._connector_enrollment_records.persist_preverified_consent(consent=consent, now=now)
            return {"ok": True, "consent": {
                "consent_id": consent.consent_id, "device_id": consent.device_id,
                "granted_at": now.isoformat(), "withdrawn_at": None,
                "dispatch_authorized": False, "grants_read": False, "grants_write": False,
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)
        except (TypeError, ValueError):
            return _refused(ControlPlaneContractError("invalid_connector_enrollment_consent", "invalid consent"))

    async def revoke_connector_enrollment_consent_for_subject(self, payload):
        try:
            now = datetime.now(timezone.utc)
            account = self._judged_connector_write(payload, {"consent_id"}, now=now, confirmed=True)
            scope = self._connector_scope_for_account(account, now)
            consent = self._connector_enrollment_records.current_consent(consent_id=payload["consent_id"], now=now)
            if consent is None or consent.owner_subject_id != account.subject_id or not consent.matches(scope):
                raise ControlPlaneContractError("enrollment_consent_required", "current owner's consent required")
            self._connector_enrollment_records.withdraw_preverified_consent(
                consent_id=consent.consent_id, owner_subject_id=account.subject_id, now=now,
            )
            return {"ok": True, "consent": {
                "consent_id": consent.consent_id, "device_id": consent.device_id,
                "granted_at": consent.granted_at.isoformat(), "withdrawn_at": now.isoformat(),
                "dispatch_authorized": False, "grants_read": False, "grants_write": False,
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)

    async def bind_connector_enrollment_challenge_for_subject(self, payload):
        try:
            now = datetime.now(timezone.utc)
            account = self._judged_connector_write(payload, {"challenge_id"}, now=now)
            expiry = self._connector_enrollment_records.bind_account_challenge(
                challenge_id=payload["challenge_id"], account=account, now=now,
            )
            return {"ok": True, "binding": {
                "challenge_id": payload["challenge_id"], "account_bound": True, "expires_at": expiry.isoformat(),
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)

    async def authorize_connector_enrollment_redeem_for_subject(self, payload):
        try:
            now = datetime.now(timezone.utc)
            account = self._judged_connector_write(payload, {"challenge_id", "consent_id", "device_id"}, now=now)
            records = self._connector_enrollment_records
            records.require_account_challenge(challenge_id=payload["challenge_id"], account=account, now=now)
            scope = self._connector_scope_for_account(account, now)
            consent = records.current_consent(consent_id=payload["consent_id"], now=now)
            if (consent is None or not consent.is_active(now=now) or
                    consent.owner_subject_id != account.subject_id or not consent.matches(scope) or
                    not consent.enrolls_device(payload["device_id"])):
                raise ControlPlaneContractError("enrollment_consent_withdrawn", "current consent required")
            records.consume_account_challenge(challenge_id=payload["challenge_id"], account=account, now=now)
            return {"ok": True, "authorization": {
                "challenge_id": payload["challenge_id"], "consent_id": consent.consent_id,
                "device_id": consent.device_id, "owner_subject_id": account.subject_id,
                "account_ref": consent.account_ref, "workspace_ref": consent.workspace_ref,
                "authorized_at": now.isoformat(), "dispatch_authorized": False,
                "grants_read": False, "grants_write": False,
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)

    async def issue_google_connect_ticket_for_subject(self, payload):
        try:
            now = datetime.now(timezone.utc)
            account = self._judged_connector_write(payload, {"connector_id"}, now=now, enrollment=False)
            receipt = self._connect_ticket_issuer.issue_for_account(account=account, connector_id=payload["connector_id"])
            return {"ok": True, "ticket": receipt.to_private_rpc_dict()}
        except ControlPlaneContractError as exc:
            return _refused(exc)
