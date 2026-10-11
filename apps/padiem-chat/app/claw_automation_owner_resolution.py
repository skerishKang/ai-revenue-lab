"""Owner-resolution authority boundary for B54 Claw scheduled automation (#2833 S-2).

Scheduled automation carries an ``owner_ref``: an **opaque provenance token**, not a
product identity. It is not a product user id, it is not a principal ref, and it grants
no authority by itself. This module is the single boundary that turns that opaque token
into a bounded, trusted owner context, so a later slice can project automation outcomes
into ``HistoryStore.record_claw_run`` / ``D1ClawTaskAlertStore`` without ever inferring an
identity from the token.

Fail-closed chain, and no step is optional:

```text
opaque owner_ref
  -> injected trusted owner authority        (missing / client-minted -> refuse)
  -> TrustedAutomationOwnerProjection        (typed, bounded, time-boxed)
  -> product_user_id
  -> identity shadow projection              (a pointer, never the authority)
  -> current canonical auth session refresh  (trusted Control Plane authority)
  -> canonical subject equality check
  -> ResolvedAutomationOwner                 (bounded, mints no authority)
```

Deliberately refused here:

* deriving a user id from ``owner_ref`` (no prefix guessing, no shape inference);
* treating the identity shadow row as canonical authority;
* minting execution or approval authority.

This slice performs **no** write: no run-history write, no task write, no alert write,
no P01 call, no background dispatch, no provider call, no scheduler activation.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.b54_identity_bridge import (
    B54IdentityBridgeError,
    resolve_current_b54_canonical_session,
)
from padiem_control_plane.tenants import TenantMembership, TenantMembershipState

from .control_plane_identity import PADIEM_CHAT_PRODUCT_ID, IdentityBridgeError
from .control_plane_identity_shadow import (
    CurrentCanonicalSessionAuthority,
    IdentityShadowStore,
    resolve_refreshed_session,
)
from .workspace_storage import _safe_identifier

__all__ = [
    "AutomationOwnerAuthority",
    "CANONICAL_AUTOMATION_OWNER_PRODUCT_ID",
    "CanonicalAutomationOwnerAuthority",
    "ClawAutomationOwnerResolver",
    "ResolvedAutomationOwner",
    "TrustedAutomationOwnerProjection",
]

_MAX_PRODUCT_USER_ID = 80
_MAX_OPAQUE_TOKEN = 256
_MAX_AUTHORITY_LIFETIME = timedelta(hours=24)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# #3247: the canonical shapes a background rule must already carry. They mirror
# the Control Plane's own minted reference grammar (tenant_/sub_ + 32 hex) and
# are re-checked here so the resolver never accepts a looser shape than the
# rule-authority gate did.
_CANONICAL_TENANT_ID_RE = re.compile(r"^tenant_[0-9a-f]{32}$")
_CANONICAL_SUBJECT_ID_RE = re.compile(r"^sub_[0-9a-f]{32}$")
# The Task/Alert Web inbox contract is keyed by the signed B62 product user id.
# This module pins the product server-side; a caller cannot choose it.
CANONICAL_AUTOMATION_OWNER_PRODUCT_ID = PADIEM_CHAT_PRODUCT_ID


def _opaque_token(name: str, value: object) -> str:
    """Validate an opaque provenance token: bounded, non-control, no shape assumption."""

    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    if not value or len(value) > _MAX_OPAQUE_TOKEN or _CONTROL_RE.search(value):
        raise ValueError(f"{name} must be a bounded opaque token")
    return value


def _product_user_id(value: object) -> str:
    """Validate a B62 product user id with the existing canonical contract.

    Deliberately identical to ``TrustedProductAuthEvidence.__post_init__`` and to the
    ``auth.py`` session user-id read contract: a ``usr_`` prefix plus a bounded length.
    No new identifier grammar is introduced here.
    """

    if (
        not isinstance(value, str)
        or not value.startswith("usr_")
        or len(value) > _MAX_PRODUCT_USER_ID
    ):
        raise ValueError("product_user_id must be a bounded B62 user identifier")
    return value


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True, slots=True)
class TrustedAutomationOwnerProjection:
    """A trusted, bounded projection of an opaque ``owner_ref``.

    Every field is issued by the injected authority; none of it is derived from the
    caller, from ``owner_ref``'s shape, or from the product-local shadow row.
    """

    owner_ref: str
    workspace_id: str
    product_user_id: str
    member_id: str
    canonical_subject_id: str
    authority_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_ref", _opaque_token("owner_ref", self.owner_ref))
        object.__setattr__(self, "workspace_id", _safe_identifier("workspace_id", self.workspace_id))
        object.__setattr__(self, "product_user_id", _product_user_id(self.product_user_id))
        object.__setattr__(self, "member_id", _safe_identifier("member_id", self.member_id))
        object.__setattr__(
            self, "canonical_subject_id", _opaque_token("canonical_subject_id", self.canonical_subject_id)
        )
        object.__setattr__(self, "authority_ref", _opaque_token("authority_ref", self.authority_ref))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("owner projection lifetime must be positive")
        if expires - issued > _MAX_AUTHORITY_LIFETIME:
            raise ValueError("owner projection lifetime must be at most 24 hours")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def valid_at(self, now: datetime) -> bool:
        return self.issued_at <= now < self.expires_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "owner_ref": self.owner_ref,
            "workspace_id": self.workspace_id,
            "product_user_id": self.product_user_id,
            "member_id": self.member_id,
            "canonical_subject_id": self.canonical_subject_id,
            "authority_ref": self.authority_ref,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            # Provenance only: the projection never carries authority material.
            "client_asserted": False,
            "grants_authority": False,
        }


class AutomationOwnerAuthority(Protocol):
    """Trusted authority that maps an opaque owner token to a bounded projection."""

    def resolve_automation_owner(
        self,
        *,
        owner_ref: str,
        workspace_id: str,
        now: datetime,
    ) -> TrustedAutomationOwnerProjection | None: ...


class CanonicalAutomationOwnerAuthority(Protocol):
    """Server-owned canonical facts authority for background owner identity (#3247).

    One production identity authority: the private Control Plane. Every method
    is a read-only re-validation of server-persisted facts; none of them
    accepts identity material from the caller, and none of them writes.
    """

    async def resolve_active_tenant_membership(
        self,
        *,
        tenant_id: str,
        canonical_subject_id: str,
        now: datetime,
    ) -> TenantMembership: ...

    async def resolve_product_user_for_subject(
        self,
        *,
        product_id: str,
        canonical_subject_id: str,
    ) -> str: ...

    async def resolve_current_auth_session(
        self,
        *,
        product_id: str,
        product_user_id: str,
    ) -> AuthSessionSnapshot: ...


@dataclass(frozen=True, slots=True)
class ResolvedAutomationOwner:
    """Bounded owner context for later projections. Mints no authority."""

    workspace_id: str
    owner_ref: str
    product_user_id: str
    member_id: str
    canonical_subject_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _safe_identifier("workspace_id", self.workspace_id))
        object.__setattr__(self, "owner_ref", _opaque_token("owner_ref", self.owner_ref))
        object.__setattr__(self, "product_user_id", _product_user_id(self.product_user_id))
        object.__setattr__(self, "member_id", _safe_identifier("member_id", self.member_id))
        object.__setattr__(
            self, "canonical_subject_id", _opaque_token("canonical_subject_id", self.canonical_subject_id)
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "owner_ref": self.owner_ref,
            "product_user_id": self.product_user_id,
            "member_id": self.member_id,
            "canonical_subject_id": self.canonical_subject_id,
            # Bounded, non-secret projection: no credential material, no raw session,
            # no provider subject, and no minted execution/approval authority.
            "credentials": 0,
            "raw_auth_session": 0,
            "provider_subject": 0,
            "secrets": 0,
            "execution_authority": 0,
            "approval_authority": 0,
            "authority_minted": False,
        }


class ClawAutomationOwnerResolver:
    """Resolve an opaque ``owner_ref`` into a trusted owner context, or fail closed.

    Two modes, one production path:

    * **canonical** (``canonical_subject_id`` supplied) — #3247. The owner is
      derived exclusively from server-persisted canonical rule facts and the
      private Control Plane: exact active role-bearing tenant membership, the
      B62 product-user reverse link, and the current B54 canonical session.
      ``owner_ref`` is validated as bounded opaque text and carried as
      provenance only; its content never selects an identity.
    * **legacy** (no canonical subject) — the pre-#3247 injected-projection
      chain. Kept only for legacy/test compatibility; it is never the
      production identity source, and background execution gates it out via
      ``classify_rule_background_authority()``.
    """

    def __init__(
        self,
        *,
        owner_authority: AutomationOwnerAuthority | None,
        session_authority: CurrentCanonicalSessionAuthority | None,
        shadow_store: IdentityShadowStore | None,
        canonical_owner_authority: CanonicalAutomationOwnerAuthority | None = None,
    ) -> None:
        self._owner_authority = owner_authority
        self._session_authority = session_authority
        self._shadow_store = shadow_store
        self._canonical_owner_authority = canonical_owner_authority

    async def resolve_owner(
        self,
        *,
        owner_ref: str,
        workspace_id: str,
        canonical_subject_id: str | None = None,
        now: datetime | None = None,
    ) -> ResolvedAutomationOwner:
        owner = _opaque_token("owner_ref", owner_ref)
        workspace = _safe_identifier("workspace_id", workspace_id)
        effective_now = _aware(
            now if now is not None else datetime.now(timezone.utc), "now"
        )

        if canonical_subject_id is not None:
            return await self._resolve_owner_from_canonical_facts(
                owner_ref=owner,
                workspace_id=workspace,
                canonical_subject_id=canonical_subject_id,
                now=effective_now,
            )

        if self._owner_authority is None or self._session_authority is None or self._shadow_store is None:
            raise IdentityBridgeError(
                503,
                "automation_owner_authority_unavailable",
                "Trusted automation owner authority is unavailable.",
            )

        try:
            projection = await _maybe_await(
                self._owner_authority.resolve_automation_owner(
                    owner_ref=owner,
                    workspace_id=workspace,
                    now=effective_now,
                )
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "automation_owner_authority_unavailable",
                "Trusted automation owner authority is unavailable.",
            ) from exc

        # A client-supplied mapping, a bare dict or any look-alike is not authority.
        if projection is None or not isinstance(projection, TrustedAutomationOwnerProjection):
            raise IdentityBridgeError(
                503,
                "automation_owner_projection_invalid",
                "Trusted automation owner authority returned no valid projection.",
            )

        if projection.owner_ref != owner:
            raise IdentityBridgeError(
                403,
                "automation_owner_mismatch",
                "Owner projection does not cover the requested owner.",
            )
        if projection.workspace_id != workspace:
            raise IdentityBridgeError(
                403,
                "automation_owner_workspace_mismatch",
                "Owner projection does not cover the requested workspace.",
            )
        if not projection.valid_at(effective_now):
            raise IdentityBridgeError(
                401,
                "automation_owner_projection_inactive",
                "Owner projection is expired or not yet valid.",
            )

        # The product-local shadow is a pointer, never the authority: the current
        # canonical session is re-read and validated before any identity is trusted.
        session = await resolve_refreshed_session(
            authority=self._session_authority,
            store=self._shadow_store,
            product_user_id=projection.product_user_id,
            now=effective_now,
        )

        if session.subject.subject_id != projection.canonical_subject_id:
            raise IdentityBridgeError(
                403,
                "automation_owner_subject_mismatch",
                "Current canonical subject does not match the trusted owner projection.",
            )

        return ResolvedAutomationOwner(
            workspace_id=projection.workspace_id,
            owner_ref=owner,
            product_user_id=projection.product_user_id,
            member_id=projection.member_id,
            canonical_subject_id=projection.canonical_subject_id,
        )

    async def _resolve_owner_from_canonical_facts(
        self,
        *,
        owner_ref: str,
        workspace_id: str,
        canonical_subject_id: str,
        now: datetime,
    ) -> ResolvedAutomationOwner:
        """Derive the owner from canonical rule facts and the Control Plane only.

        Fail-closed chain, and no step is optional:

        ```text
        bounded opaque owner_ref                       (provenance only)
        canonical tenant-shaped workspace_id           (rule.server-persisted)
        canonical subject-shaped canonical_subject_id  (rule.server-persisted)
          -> exact ACTIVE role-bearing tenant membership revalidation
          -> B62 product-user reverse link (exactly one ACTIVE)
          -> current B54 canonical session re-read (#3243)
          -> B54 session subject == rule subject
          -> B54 session tenant  == rule workspace
        -> ResolvedAutomationOwner(member_id = B62 product_user_id)
        ```

        ``owner_ref`` never enters the chain: changing it cannot change the
        resolved identity, and no identity can be recovered from it.
        """

        authority = self._canonical_owner_authority
        if authority is None:
            raise IdentityBridgeError(
                503,
                "automation_owner_authority_unavailable",
                "Canonical automation owner authority is unavailable.",
            )
        if not _CANONICAL_TENANT_ID_RE.fullmatch(workspace_id):
            raise IdentityBridgeError(
                403,
                "automation_owner_workspace_invalid",
                "Automation owner requires a canonical tenant workspace.",
            )
        subject = canonical_subject_id
        if not isinstance(subject, str) or not _CANONICAL_SUBJECT_ID_RE.fullmatch(subject):
            raise IdentityBridgeError(
                403,
                "automation_owner_subject_invalid",
                "Automation owner requires a canonical rule subject.",
            )

        try:
            membership = await _maybe_await(
                authority.resolve_active_tenant_membership(
                    tenant_id=workspace_id,
                    canonical_subject_id=subject,
                    now=now,
                )
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "automation_owner_authority_unavailable",
                "Canonical tenant membership is unavailable.",
            ) from exc
        if (
            not isinstance(membership, TenantMembership)
            or membership.tenant_id != workspace_id
            or membership.canonical_subject_id != subject
            or membership.state is not TenantMembershipState.ACTIVE
            or membership.role is None
        ):
            raise IdentityBridgeError(
                403,
                "automation_owner_membership_invalid",
                "Canonical tenant membership is not active for this owner.",
            )

        try:
            product_user = await _maybe_await(
                authority.resolve_product_user_for_subject(
                    product_id=CANONICAL_AUTOMATION_OWNER_PRODUCT_ID,
                    canonical_subject_id=subject,
                )
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "automation_owner_authority_unavailable",
                "Canonical product link resolution is unavailable.",
            ) from exc
        if (
            not isinstance(product_user, str)
            or not product_user.startswith("usr_")
            or len(product_user) > _MAX_PRODUCT_USER_ID
        ):
            raise IdentityBridgeError(
                503,
                "automation_owner_product_user_invalid",
                "Canonical product link did not yield a bounded B62 product user.",
            )

        # #3243 reuse: the current B54 session is re-read for the server-derived
        # product user; the bridge pins the product to b54-padiem-claw, rejects a
        # non-USER subject, a tenant-less session and an inactive one.
        try:
            current = await resolve_current_b54_canonical_session(
                authority, product_user, now=now
            )
        except B54IdentityBridgeError as exc:
            raise IdentityBridgeError(exc.status_code, exc.code, exc.safe_message) from exc
        except Exception as exc:
            raise IdentityBridgeError(
                503,
                "automation_owner_authority_unavailable",
                "Current canonical B54 session is unavailable.",
            ) from exc
        session = current.auth_session
        if session.subject.subject_id != subject:
            raise IdentityBridgeError(
                403,
                "automation_owner_subject_mismatch",
                "Current B54 canonical subject does not match the rule owner.",
            )
        if session.tenant_id != workspace_id:
            raise IdentityBridgeError(
                403,
                "automation_owner_workspace_mismatch",
                "Current B54 canonical tenant does not match the rule workspace.",
            )

        # member_id = product_user_id is the existing claw_inbox_routes ownership
        # contract, not a new identity inference.
        return ResolvedAutomationOwner(
            workspace_id=workspace_id,
            owner_ref=owner_ref,
            product_user_id=product_user,
            member_id=product_user,
            canonical_subject_id=subject,
        )
