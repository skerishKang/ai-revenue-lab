"""#5118 capability composition for the integrated administrator role.

The integrated role is one platform authority; product authorities stay
separate. A stored ADMIN may operate platform model management (Chat, Claw,
B14 and the B66 model policy), because those are the existing management
surfaces. It never inherits B66 customer-data administration, which remains
bound to the existing verified B66 owner account.

Read failures of the role table degrade to "no stored role" so the existing
trusted central operator keeps its authority before migration 052 is applied.
That is fail-closed for everyone else: no role, no platform authority.
"""
from __future__ import annotations

import inspect
from typing import Any

from .platform_admin_roles import ROLE_SUPER_ADMIN, ROLES


async def _call(authority: object, method: str, *args: Any, keyword: bool = False) -> bool:
    verify = getattr(authority, method, None) if authority is not None else None
    if not callable(verify):
        return False
    try:
        result = verify(user_id=args[0]) if keyword else verify(args[0])
        result = await result if inspect.isawaitable(result) else result
    except Exception:
        return False
    return result is True


class PlatformAdminAuthority:
    def __init__(self, *, role_store, legacy_model_admin, legacy_b66_admin):
        self._role_store = role_store
        self._legacy_model_admin = legacy_model_admin
        self._legacy_b66_admin = legacy_b66_admin

    async def _stored_role(self, user_id: str) -> str | None:
        if self._role_store is None:
            return None
        try:
            role = await self._role_store.role_for(user_id)
        except Exception:
            return None
        return role if role in ROLES else None

    async def role_for(self, user_id: str) -> str | None:
        if await _call(
            self._legacy_model_admin, "is_global_model_admin", user_id, keyword=True
        ):
            return ROLE_SUPER_ADMIN
        return await self._stored_role(user_id)

    async def is_super_admin(self, *, user_id: str) -> bool:
        return await self.role_for(user_id) == ROLE_SUPER_ADMIN

    async def is_global_model_admin(self, *, user_id: str) -> bool:
        """Existing central model-management guard: ADMIN or SUPER_ADMIN."""
        return await self.role_for(user_id) in ROLES

    async def is_b66_platform_admin(self, user_id: str) -> bool:
        """B66 platform policy management, never B66 customer data."""
        if await self.role_for(user_id) in ROLES:
            return True
        return await _call(self._legacy_b66_admin, "is_google_admin", user_id)

    async def is_b66_customer_admin(self, user_id: str) -> bool:
        """Customer roster/inquiry authority stays with the B66 owner only."""
        return await _call(self._legacy_b66_admin, "is_google_admin", user_id)


def platform_authority_for(request) -> PlatformAdminAuthority:
    authority = getattr(request.app.state, "platform_admin_authority", None)
    if isinstance(authority, PlatformAdminAuthority):
        return authority
    return PlatformAdminAuthority(
        role_store=getattr(request.app.state, "platform_admin_role_store", None),
        legacy_model_admin=getattr(
            request.app.state, "central_model_admin_authorizer", None
        ),
        legacy_b66_admin=getattr(request.app.state, "b66_member_admin_store", None),
    )
