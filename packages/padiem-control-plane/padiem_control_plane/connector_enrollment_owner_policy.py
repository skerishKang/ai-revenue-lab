"""Product-neutral owner admission boundary for a shared PADIEM Connector.

ONE canonical Identity/tenant membership authority and ONE canonical Broker
device registry support B66, Claw, PADIEM Chat, Engine and future PADIEM
products. Product origin must never mint another device identity or grant PC
READ/WRITE privileges. This is the owner *registration* boundary, not product
execution permission (see existing local_agent_pc_access.py).

The list below denotes product logins whose current-user-to-canonical-session
bridge has actually been reviewed for enrollment. Adding a web UI, choosing a
B14 model or knowing a product ID is NOT authorization to extend it.

B62/Chat's same-user bridge review was completed 2026-11-04
(docs/operations/CONNECTOR_ENROLLMENT_CHAT_SESSION_BRIDGE_REVIEW_261104.md);
B66/Quote and Engine still need their OWN authenticated
same-user-to-Identity-DO bridge review before their login can initiate a
shared PC registration. Do not infer authorization from plan tiers, model
access, email, or arbitrary product IDs.

SOURCE ONLY. Registration, migrations, product routes and credential handoff
remain OFF unless separately enabled in the existing canonical authorities.
"""
from __future__ import annotations

from datetime import datetime

from .auth_sessions import AuthSessionSnapshot
from .contracts import ControlPlaneContractError, SubjectType
from .tenants import TenantMembershipRole

# Reviewed canonical session bridges: the Claw engine session (the original
# reviewed bridge) and the B62/Chat login session (the same-user bridge review
# completed 2026-11-04, see docs/operations/
# CONNECTOR_ENROLLMENT_CHAT_SESSION_BRIDGE_REVIEW_261104.md). Do not infer
# authorization from plan tiers, model access, email, or arbitrary product IDs.
REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS = frozenset({"b54-padiem-claw", "b62"})
CONNECTOR_REGISTRATION_PRODUCT_NEUTRAL_AUTHORITY = True
CONNECTOR_REGISTRATION_MINTS_PRODUCT_ACCESS = False
CONNECTOR_REGISTRATION_GRANTS_P01_READ = False
CONNECTOR_REGISTRATION_GRANTS_P01_WRITE = False


def require_canonical_connector_owner_session(
    *, session: AuthSessionSnapshot, membership_role: object, now: datetime
) -> AuthSessionSnapshot:
    """Verify shared PC registration authorization from a canonical session.

    The caller MUST resolve `session` and active tenant membership from the
    *existing* canonical Identity Durable Object. This function neither
    accepts client-supplied subject/tenant/workspace nor creates an identity.
    The product id is a reviewed login bridge discriminator, never a scope.
    """
    if (
        not isinstance(session, AuthSessionSnapshot)
        or session.product_id not in REVIEWED_CONNECTOR_ENROLLMENT_LOGIN_PRODUCTS
        or session.subject.subject_type is not SubjectType.USER
        or not isinstance(session.tenant_id, str)
        or not session.tenant_id
        or not session.is_active(now=now)
    ):
        raise ControlPlaneContractError(
            "connector_enrollment_consent_session_denied",
            "a reviewed active canonical owner login session is required",
        )
    if membership_role is not TenantMembershipRole.OWNER:
        raise ControlPlaneContractError(
            "connector_enrollment_owner_required",
            "canonical tenant OWNER is required for shared PC enrollment",
        )
    return session
