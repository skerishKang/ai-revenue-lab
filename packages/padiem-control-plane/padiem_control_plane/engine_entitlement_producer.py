"""Canonical E7 EntitlementSnapshot producer for authenticated users (#3300).

Frozen owner policy (2026-10-01):
- supported products: b62 and b54-padiem-claw;
- every currently ACTIVE canonical signed-in USER may run orchestration;
- anonymous and app-level ACCOUNT subjects are not eligible;
- orchestration.run has no product limit yet;
- usage remains shadow/non-billable;
- canonical Control Plane identity/session truth is the sole upstream authority.

This module creates no second entitlement schema and accepts no browser plan,
role, paid-state, credit-balance, provider, model, or routing assertion.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from .auth_sessions import AuthSessionSnapshot, AuthSessionState
from .contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from .entitlements import EntitlementGrant, EntitlementSnapshot


SUPPORTED_ENGINE_PRODUCTS = frozenset({"b62", "b54-padiem-claw"})
ENGINE_ORCHESTRATION_GRANT = "orchestration.run"
ENGINE_ENTITLEMENT_POLICY_REVISION = "authenticated-users-v1"
ENGINE_ENTITLEMENT_POLICY_EFFECTIVE_AT = datetime(
    2026,
    10,
    1,
    0,
    0,
    tzinfo=UTC,
)

_SUBJECT_KEYS = frozenset({"subject_type", "subject_id"})
_SESSION_REQUIRED_KEYS = frozenset(
    {
        "session_id",
        "product_id",
        "subject",
        "issued_at",
        "expires_at",
        "state",
        "revision",
    }
)
_SESSION_OPTIONAL_KEYS = frozenset({"tenant_id"})


class EngineEntitlementStore(Protocol):
    def install_entitlement_snapshot(
        self,
        snapshot: EntitlementSnapshot,
        *,
        now: datetime,
    ) -> EntitlementSnapshot: ...


class CanonicalIdentityClient(Protocol):
    async def resolve_product_user_for_subject(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]: ...

    async def resolve_current_auth_session(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]: ...


def _error(
    code: str,
    message: str,
) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message)


def _aware(
    value: Any,
    label: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _error(
            "invalid_engine_entitlement_producer",
            f"{label} must be timezone-aware",
        )
    return value.astimezone(UTC)


def _parse_time(
    value: Any,
    label: str,
) -> datetime:
    if not isinstance(value, str) or not value:
        raise _error(
            "invalid_engine_entitlement_producer",
            f"{label} must be ISO-8601 text",
        )
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise _error(
            "invalid_engine_entitlement_producer",
            f"{label} must be valid ISO-8601 text",
        ) from exc
    return _aware(parsed, label)


def _closed(
    payload: Any,
    keys: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if (
        not isinstance(payload, Mapping)
        or frozenset(payload) != keys
    ):
        raise _error(
            "invalid_engine_entitlement_producer",
            f"{label} has an invalid shape",
        )
    return dict(payload)


def canonical_user_subject_from_wire(
    payload: Any,
) -> CanonicalSubjectRef:
    wire = _closed(
        payload,
        _SUBJECT_KEYS,
        "canonical subject",
    )
    try:
        subject_type = SubjectType(
            wire["subject_type"]
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "engine_entitlement_subject_not_eligible",
            "subject type is not eligible for Engine entitlement",
        ) from exc

    subject = CanonicalSubjectRef(
        subject_type=subject_type,
        subject_id=wire["subject_id"],
    )
    if (
        subject.subject_type
        is not SubjectType.USER
    ):
        raise _error(
            "engine_entitlement_subject_not_eligible",
            "only an authenticated canonical user is eligible",
        )
    return subject


def auth_session_from_private_rpc(
    payload: Any,
) -> AuthSessionSnapshot:
    if not isinstance(payload, Mapping):
        raise _error(
            "engine_entitlement_identity_unavailable",
            "identity session response is invalid",
        )
    keys = frozenset(payload)
    if keys not in {
        _SESSION_REQUIRED_KEYS,
        _SESSION_REQUIRED_KEYS
        | _SESSION_OPTIONAL_KEYS,
    }:
        raise _error(
            "engine_entitlement_identity_unavailable",
            "identity session response has an invalid shape",
        )

    wire = dict(payload)
    subject = canonical_user_subject_from_wire(
        wire["subject"]
    )
    try:
        state = AuthSessionState(wire["state"])
        session = AuthSessionSnapshot(
            session_id=wire["session_id"],
            product_id=wire["product_id"],
            subject=subject,
            issued_at=_parse_time(
                wire["issued_at"],
                "session issued_at",
            ),
            expires_at=_parse_time(
                wire["expires_at"],
                "session expires_at",
            ),
            state=state,
            revision=wire["revision"],
            tenant_id=wire.get("tenant_id"),
        )
    except (
        ControlPlaneContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise _error(
            "engine_entitlement_identity_unavailable",
            "identity session response is invalid",
        ) from exc
    return session


def _require_product(
    product_id: Any,
) -> str:
    if (
        not isinstance(product_id, str)
        or product_id
        not in SUPPORTED_ENGINE_PRODUCTS
    ):
        raise _error(
            "engine_entitlement_product_not_eligible",
            "product is not eligible for the current Engine entitlement policy",
        )
    return product_id


async def resolve_authenticated_user_session(
    identity: CanonicalIdentityClient,
    *,
    product_id: str,
    subject: CanonicalSubjectRef,
    now: datetime,
) -> AuthSessionSnapshot:
    """Re-read current login truth from the private identity authority."""

    product = _require_product(product_id)
    observed_at = _aware(now, "now")
    if (
        not isinstance(
            subject,
            CanonicalSubjectRef,
        )
        or subject.subject_type
        is not SubjectType.USER
    ):
        raise _error(
            "engine_entitlement_subject_not_eligible",
            "only an authenticated canonical user is eligible",
        )

    try:
        reverse = (
            await identity.resolve_product_user_for_subject(
                {
                    "product_id": product,
                    "canonical_subject_id": (
                        subject.subject_id
                    ),
                }
            )
        )
    except Exception as exc:
        raise _error(
            "engine_entitlement_identity_unavailable",
            "canonical product identity is unavailable",
        ) from exc

    if (
        not isinstance(reverse, Mapping)
        or frozenset(reverse)
        != {"ok", "product_user_id"}
        or reverse.get("ok") is not True
        or not isinstance(
            reverse.get("product_user_id"),
            str,
        )
        or not reverse["product_user_id"]
    ):
        raise _error(
            "engine_entitlement_identity_unavailable",
            "canonical product identity is unavailable",
        )

    try:
        current = (
            await identity.resolve_current_auth_session(
                {
                    "product_id": product,
                    "product_user_id": (
                        reverse[
                            "product_user_id"
                        ]
                    ),
                }
            )
        )
    except Exception as exc:
        raise _error(
            "engine_entitlement_identity_unavailable",
            "current authenticated session is unavailable",
        ) from exc

    if (
        not isinstance(current, Mapping)
        or frozenset(current)
        != {"ok", "session"}
        or current.get("ok") is not True
    ):
        raise _error(
            "engine_entitlement_identity_unavailable",
            "current authenticated session is unavailable",
        )

    session = auth_session_from_private_rpc(
        current["session"]
    )
    if (
        session.product_id != product
        or session.subject != subject
    ):
        raise _error(
            "engine_entitlement_identity_mismatch",
            "current session does not match the requested product subject",
        )
    if not session.is_active(
        now=observed_at
    ):
        raise _error(
            "engine_entitlement_session_inactive",
            "current authenticated session is not active",
        )
    return session


def produce_authenticated_user_engine_entitlement(
    session: AuthSessionSnapshot,
    *,
    now: datetime,
) -> EntitlementSnapshot:
    """Map one current ACTIVE canonical login to the frozen MVP grant."""

    observed_at = _aware(now, "now")
    if not isinstance(
        session,
        AuthSessionSnapshot,
    ):
        raise _error(
            "invalid_engine_entitlement_producer",
            "session must be AuthSessionSnapshot",
        )

    product = _require_product(
        session.product_id
    )
    if (
        session.subject.subject_type
        is not SubjectType.USER
    ):
        raise _error(
            "engine_entitlement_subject_not_eligible",
            "only an authenticated canonical user is eligible",
        )
    if (
        observed_at
        < ENGINE_ENTITLEMENT_POLICY_EFFECTIVE_AT
    ):
        raise _error(
            "engine_entitlement_policy_not_active",
            "Engine entitlement policy is not active yet",
        )
    if not session.is_active(
        now=observed_at
    ):
        raise _error(
            "engine_entitlement_session_inactive",
            "current authenticated session is not active",
        )

    issued_at = max(
        session.issued_at.astimezone(UTC),
        ENGINE_ENTITLEMENT_POLICY_EFFECTIVE_AT,
    )
    expires_at = (
        session.expires_at.astimezone(UTC)
    )
    if expires_at <= issued_at:
        raise _error(
            "engine_entitlement_session_inactive",
            "authenticated session does not overlap the entitlement policy window",
        )

    material = "|".join(
        (
            "engine-e7-entitlement-v1",
            ENGINE_ENTITLEMENT_POLICY_REVISION,
            product,
            session.subject.subject_type.value,
            session.subject.subject_id,
            session.session_id,
            str(session.revision),
        )
    )
    digest = hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()

    return EntitlementSnapshot(
        snapshot_id=(
            f"ent-e7-{digest[:40]}"
        ),
        product_id=product,
        subject=session.subject,
        revision=(
            f"{ENGINE_ENTITLEMENT_POLICY_REVISION}."
            f"s{session.revision}."
            f"{digest[:16]}"
        ),
        issued_at=issued_at,
        expires_at=expires_at,
        grants=(
            EntitlementGrant(
                key=ENGINE_ORCHESTRATION_GRANT,
                allowed=True,
                limit=None,
            ),
        ),
    )


async def ensure_authenticated_user_engine_entitlement(
    store: EngineEntitlementStore,
    identity: CanonicalIdentityClient,
    *,
    product_id: str,
    subject: CanonicalSubjectRef,
    now: datetime,
) -> EntitlementSnapshot:
    """Resolve login truth, produce, and install through the CP-owned seam."""

    observed_at = _aware(now, "now")
    session = (
        await resolve_authenticated_user_session(
            identity,
            product_id=product_id,
            subject=subject,
            now=observed_at,
        )
    )
    snapshot = (
        produce_authenticated_user_engine_entitlement(
            session,
            now=observed_at,
        )
    )
    return store.install_entitlement_snapshot(
        snapshot,
        now=observed_at,
    )


CANONICAL_UPSTREAM_ENTITLEMENT_POLICY = (
    "authenticated-canonical-user"
)
CLIENT_PLAN_ROLE_CREDIT_FIELDS_ARE_AUTHORITY = (
    False
)
ENGINE_CAN_INSTALL_ENTITLEMENT = False
B14_PROVIDER_AUTHORITY_WIDENED = False
