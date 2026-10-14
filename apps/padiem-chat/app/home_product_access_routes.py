"""Read-only Chat+Claw bundled customer Home access (#4546, Owner 2026-10-14).

The verified B62 canonical USER session is the only customer bundle authority.
There are no separate Chat/Claw enrollment steps, no B66 visibility, and no
P01/PC/file/tool grants. A presentation cookie alone never produces an allow.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from padiem_control_plane import AuthSessionSnapshot, SubjectType
from padiem_control_plane.product_access_projection import (
    PADIEM_CHAT_PRODUCT_ID,
    PADIEM_CLAW_PRODUCT_ID,
    PADIEM_HOME_PRODUCT_IDS,
    ProductAccessFinding,
    ProductAccessState,
    build_product_access_projection,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .control_plane_identity_shadow import resolve_refreshed_session


ACCESS_PATH = "/api/home/product-access"
BUNDLE_AUTHORITY_ID = "padiem-chat-claw-bundle-v1"
_HEADERS = {"cache-control": "private, no-store", "vary": "Cookie", "x-content-type-options": "nosniff"}


@dataclass(frozen=True)
class _VerifiedBundleSource:
    session: AuthSessionSnapshot
    authority: str = BUNDLE_AUTHORITY_ID

    def read_product_access(self, *, product_id, subject, now):
        if (
            product_id not in PADIEM_HOME_PRODUCT_IDS
            or subject != self.session.subject
            or subject.subject_type is not SubjectType.USER
            or self.session.product_id != PADIEM_CHAT_PRODUCT_ID
            or not self.session.is_active(now=now)
        ):
            raise ValueError("server identity or product scope no longer valid")
        return ProductAccessFinding(
            product_id=product_id,
            subject=subject,
            state=ProductAccessState.AVAILABLE,
            authority=self.authority,
            issued_at=now,
            expires_at=self.session.expires_at,
        )


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=_HEADERS)


async def home_product_access(request: Request) -> JSONResponse:
    """Server-only session reconciliation; no model/provider/storage writes.

    A signed B62 cookie, current corresponding server user, and active
    authoritative canonical session must ALL agree. No caller-supplied
    product/owner/tenant input, user tier or email can grant Home access.
    """
    if request.query_params:
        return _error(400, "unsupported_access_query")
    if not auth_ready(request):
        return _error(503, "product_access_unavailable")
    user_id = current_user_id(request)
    if not user_id:
        return _error(401, "authentication_required")
    store = request.app.state.history_store
    try:
        user = await store.get_user(user_id)
    except Exception:
        return _error(503, "product_access_unavailable")
    if user is None:
        return _error(401, "authentication_required")

    shadow = getattr(request.app.state, "identity_shadow_store", None)
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if shadow is None or authority is None:
        return _error(503, "product_access_unavailable")
    try:
        now = datetime.now(timezone.utc)
        current = await resolve_refreshed_session(
            authority=authority, store=shadow, product_user_id=user_id, now=now,
        )
        if not isinstance(current, AuthSessionSnapshot):
            raise ValueError("non-canonical session")
        source = _VerifiedBundleSource(current)
        projection = build_product_access_projection(
            current.subject,
            sources={
                PADIEM_CHAT_PRODUCT_ID: source,
                PADIEM_CLAW_PRODUCT_ID: source,
            },
            now=now,
        )
        if set(projection.available_product_ids) != set(PADIEM_HOME_PRODUCT_IDS):
            return _error(503, "product_access_unavailable")
        return JSONResponse(projection.to_browser_dict(), headers=_HEADERS)
    except Exception:
        return _error(503, "product_access_unavailable")
