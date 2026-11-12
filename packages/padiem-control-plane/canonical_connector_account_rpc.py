"""Account-keyed READ variants of the connector RPCs (#7542 P5-A).

The connector RPCs take a canonical ``session_id``. Retiring the session role
of this authority replaces that key with the product and the account number
(``canonical_subject_id``). This module adds the four read variants and the one
judgement they share. It is additive and default-off:

* the session-keyed RPCs are not touched and keep answering exactly as before;
* every method here refuses with ``connector_account_key_rpc_disabled`` until
  the deployment sets the switch named by ``CONNECTOR_ACCOUNT_KEY_RPC_SWITCH``;
* nothing here writes: no row is created, extended, revoked or deleted.

A session carried four facts for the session-keyed reads — the account exists,
it is linked to the calling product, it has exactly one tenant and the product
is a reviewed one. An account key carries none of them, so the authority reads
each of them again from its own storage on every call (see
``judge_connector_account``). The caller supplies the product and the account
number and nothing else: no tenant, role, clock or expiry is accepted.

Like the session-keyed mixin this module has no Cloudflare ``workers``/``js``
import, so standard CPython can test the contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from canonical_connector_scope_readonly import ReadOnlyExistingConnectorScope
from identity_connector_ticket import ALLOWED_PRODUCT_ID
from padiem_control_plane.connector_enrollment_owner_policy import (
    REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.tenants import TenantMembershipRole, TenantMembershipState

#: Deployment switch. Anything but the text ``true`` keeps every method closed.
CONNECTOR_ACCOUNT_KEY_RPC_SWITCH = "CONTROL_PLANE_CONNECTOR_ACCOUNT_KEY_RPC_ENABLED"
CONNECTOR_ACCOUNT_KEY_RPC_DISABLED = "connector_account_key_rpc_disabled"

#: The account-keyed read surface this module adds, by RPC name.
CONNECTOR_ACCOUNT_KEY_READ_METHODS: frozenset[str] = frozenset({
    "resolve_connector_owner_scope_for_subject",
    "resolve_connector_enrollment_consent_for_subject_device",
    "resolve_connector_workspace_for_subject",
    "resolve_connector_context_for_subject",
})

_ACCOUNT_KEYS = frozenset({"product_id", "canonical_subject_id"})
_ACCOUNT_DEVICE_KEYS = _ACCOUNT_KEYS | {"device_id"}
# The same reviewed products the session-keyed reads accept: PC registration
# reads take either login product, connector context is the Chat product only.
_ENROLLMENT_PRODUCTS: frozenset[str] = frozenset(REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS)
_CONTEXT_PRODUCTS: frozenset[str] = frozenset({ALLOWED_PRODUCT_ID})


def _refused(exc: ControlPlaneContractError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": exc.code, "message": "Canonical identity request was rejected"}}


def _closed(payload: Any, keys: frozenset[str], field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            f"{field_name} must contain exactly the reviewed fields",
        )
    if any(not isinstance(payload[key], str) or not payload[key] for key in keys):
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            f"{field_name} fields must be non-empty text",
        )
    return payload


@dataclass(frozen=True, slots=True)
class VerifiedConnectorAccount:
    """What the authority itself established about one account for one call."""

    product_id: str
    subject_id: str
    tenant_id: str
    membership: Any


def judge_connector_account(
    store: Any,
    *,
    product_id: Any,
    canonical_subject_id: Any,
    reviewed_products: frozenset[str],
    require_owner: bool,
    now: datetime,
) -> VerifiedConnectorAccount:
    """The one judgement every account-keyed connector RPC passes first.

    Each fact is read from the authority's own storage at call time; the
    caller's word is taken for nothing but which product and which account it
    is asking about. In order, and failing closed at the first miss:

    1. the product is one this connector surface reviews — a product that is
       only registered for account links is refused here and again by the
       store's own full-surface check in step 3;
    2. the account was not removed by account deletion;
    3. the account has exactly one ACTIVE link to exactly this product (the
       condition a session could only be established under);
    4. the account has exactly one active membership on an active tenant —
       none and more than one are both refused, the store never picks one;
    5. that membership is active, role-bearing and already in force, and it is
       an OWNER membership when the read is a PC registration read.

    Nothing is written and no clock is taken from the caller.
    """

    if not isinstance(product_id, str) or not isinstance(canonical_subject_id, str):
        raise ControlPlaneContractError(
            "invalid_identity_authority_rpc",
            "product and account must be text",
        )
    if product_id not in reviewed_products:
        raise ControlPlaneContractError(
            "connector_account_product_denied",
            "product is not reviewed for this connector read",
        )
    if store.account_deletion_recorded(canonical_subject_id=canonical_subject_id):
        raise ControlPlaneContractError(
            "canonical_subject_deleted",
            "canonical subject was removed by account deletion",
        )
    # Exactly one ACTIVE link for this exact product; the store also refuses a
    # product outside its full-surface set, whatever ``reviewed_products`` says.
    store.resolve_product_user_for_subject(
        product_id=product_id, canonical_subject_id=canonical_subject_id,
    )
    tenant_ids = store._active_membership_tenant_ids(canonical_subject_id)
    if not tenant_ids:
        raise ControlPlaneContractError(
            "canonical_tenant_membership_not_found",
            "canonical subject has no active tenant membership",
        )
    if len(tenant_ids) != 1:
        raise ControlPlaneContractError(
            "canonical_tenant_membership_ambiguous",
            "canonical subject has an ambiguous tenant membership",
        )
    tenant_id = tenant_ids[0]
    membership = store.resolve_active_tenant_membership(
        tenant_id=tenant_id, canonical_subject_id=canonical_subject_id, now=now,
    )
    if (
        getattr(membership, "tenant_id", None) != tenant_id
        or getattr(membership, "canonical_subject_id", None) != canonical_subject_id
        or getattr(membership, "state", None) is not TenantMembershipState.ACTIVE
        or getattr(membership, "role", None) is None
    ):
        raise ControlPlaneContractError(
            "canonical_membership_denied",
            "verified canonical tenant membership is required",
        )
    if require_owner and membership.role is not TenantMembershipRole.OWNER:
        raise ControlPlaneContractError(
            "connector_enrollment_owner_required",
            "canonical tenant OWNER is required for shared PC enrollment",
        )
    return VerifiedConnectorAccount(
        product_id=product_id,
        subject_id=canonical_subject_id,
        tenant_id=tenant_id,
        membership=membership,
    )


class CanonicalIdentityAccountConnectorRPC:
    """Account-keyed connector reads for the private Identity Durable Object.

    Composed into the same Durable Object as the session-keyed mixin, so it
    reads the same ``_store``, ``_storage``, ``_connector_context_store`` and
    ``_connector_enrollment_records``. Answers have the same shape as their
    session-keyed counterparts, so a caller can compare the two keys.
    """

    def _connector_account_key_rpc_enabled(self) -> bool:
        return str(getattr(self.env, CONNECTOR_ACCOUNT_KEY_RPC_SWITCH, "")).lower() == "true"

    def _judged_connector_account(
        self,
        payload: Any,
        keys: frozenset[str],
        field_name: str,
        *,
        reviewed_products: frozenset[str],
        require_owner: bool,
        enrollment_gated: bool,
        now: datetime,
    ) -> tuple[dict[str, Any], VerifiedConnectorAccount]:
        # The switch is read before the payload: a closed deployment answers
        # the same refusal whatever it is sent.
        if not self._connector_account_key_rpc_enabled():
            raise ControlPlaneContractError(
                CONNECTOR_ACCOUNT_KEY_RPC_DISABLED,
                "account-keyed connector RPC is disabled",
            )
        wire = _closed(payload, keys, field_name)
        if enrollment_gated:
            # The PC registration reads stay behind the same deployment gates
            # as their session-keyed counterparts; a missing gate is closed.
            gate = getattr(self, "_connector_enrollment_enabled", None)
            if not callable(gate) or not gate():
                raise ControlPlaneContractError(
                    "connector_enrollment_rpc_disabled",
                    "connector enrollment disabled",
                )
        account = judge_connector_account(
            self._store,
            product_id=wire["product_id"],
            canonical_subject_id=wire["canonical_subject_id"],
            reviewed_products=reviewed_products,
            require_owner=require_owner,
            now=now,
        )
        return wire, account

    def _connector_scope_for_account(self, account: VerifiedConnectorAccount, now: datetime):
        return ReadOnlyExistingConnectorScope(
            identity_do_storage=self._storage, membership_authority=self._store,
        ).resolve_scope(
            subject_id=account.subject_id, tenant_ref=account.tenant_id,
            now=now, membership=account.membership,
        )

    async def resolve_connector_owner_scope_for_subject(self, payload: dict) -> dict:
        """Account-keyed twin of ``resolve_connector_owner_scope``."""
        try:
            now = datetime.now(timezone.utc)
            _wire, account = self._judged_connector_account(
                payload, _ACCOUNT_KEYS, "connector owner scope read by account",
                reviewed_products=_ENROLLMENT_PRODUCTS, require_owner=True,
                enrollment_gated=True, now=now,
            )
            scope = self._connector_scope_for_account(account, now)
            return {"ok": True, "scope": {
                "account_ref": scope.account_ref, "workspace_ref": scope.workspace_ref,
                # Only the judged account's own number can appear here: it is
                # the number the authority just verified, never a second one.
                "owner_subject_id": account.subject_id,
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)

    async def resolve_connector_enrollment_consent_for_subject_device(self, payload: dict) -> dict:
        """Account-keyed twin of ``resolve_connector_enrollment_consent_for_device``."""
        try:
            now = datetime.now(timezone.utc)
            wire, account = self._judged_connector_account(
                payload, _ACCOUNT_DEVICE_KEYS, "connector enrollment consent read by account",
                reviewed_products=_ENROLLMENT_PRODUCTS, require_owner=True,
                enrollment_gated=True, now=now,
            )
            scope = self._connector_scope_for_account(account, now)
            consent = self._connector_enrollment_records.current_for_device(
                owner_subject_id=account.subject_id, device_id=wire["device_id"], now=now,
            )
            if consent is None or not consent.matches(scope) or not consent.enrolls_device(wire["device_id"]):
                raise ControlPlaneContractError(
                    "enrollment_consent_required",
                    "current consent for this device is required",
                )
            return {"ok": True, "consent": {
                "consent_id": consent.consent_id, "device_id": consent.device_id,
                "owner_subject_id": consent.owner_subject_id, "account_ref": consent.account_ref,
                "workspace_ref": consent.workspace_ref, "granted_at": consent.granted_at.isoformat(),
                "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None,
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)

    async def resolve_connector_workspace_for_subject(self, payload: dict) -> dict:
        """Account-keyed twin of ``resolve_connector_workspace``.

        ``present=False`` keeps its meaning: the connector context has not been
        created yet. Reading by account can no more mint it than reading by
        session can.
        """
        try:
            now = datetime.now(timezone.utc)
            _wire, account = self._judged_connector_account(
                payload, _ACCOUNT_KEYS, "connector workspace read by account",
                reviewed_products=_CONTEXT_PRODUCTS, require_owner=False,
                enrollment_gated=False, now=now,
            )
            context = self._connector_context_store.resolve_existing_for_subject(
                subject_id=account.subject_id,
            )
            if context is None:
                return {"ok": True, "workspace": {"present": False}}
            return {"ok": True, "workspace": {"present": True, "workspace_ref": context.workspace_ref}}
        except ControlPlaneContractError as exc:
            return _refused(exc)

    async def resolve_connector_context_for_subject(self, payload: dict) -> dict:
        """Account-keyed twin of ``resolve_connector_context``."""
        try:
            now = datetime.now(timezone.utc)
            _wire, account = self._judged_connector_account(
                payload, _ACCOUNT_KEYS, "connector context read by account",
                reviewed_products=_CONTEXT_PRODUCTS, require_owner=False,
                enrollment_gated=False, now=now,
            )
            context = self._connector_context_store.resolve_existing_for_subject(
                subject_id=account.subject_id,
            )
            if context is None:
                return {"ok": True, "context": {"present": False}}
            return {"ok": True, "context": {
                "present": True,
                "product_id": context.product_id,
                "subject_id": account.subject_id,
                "actor_ref": context.actor_ref,
                "workspace_ref": context.workspace_ref,
            }}
        except ControlPlaneContractError as exc:
            return _refused(exc)


CONNECTOR_ACCOUNT_KEY_READ_RPC = True
CONNECTOR_ACCOUNT_KEY_READ_RPC_DEFAULT_OFF = True
CONNECTOR_ACCOUNT_KEY_READ_RPC_WRITES = False
CONNECTOR_ACCOUNT_KEY_READ_RPC_ACCEPTS_TENANT = False
CONNECTOR_ACCOUNT_KEY_READ_RPC_ACCEPTS_CALLER_CLOCK = False
