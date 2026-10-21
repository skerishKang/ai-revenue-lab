"""#5483 one server authority for the administrator model entitlement.

The administrator hub and the model tier ceiling were judged by two different
authorities. The hub reads the integrated platform role (#5118), while the
model ceiling read only the B66 member-admin store. An account the server
already proves to be a platform administrator therefore saw the administrator
menu while the model picker still reported the ordinary member grade, so every
paid tier was presented as an upgrade and the account could not use the
highest model it was entitled to.

This module reuses the existing platform authority instead of adding a new
role, table, email allowlist or session claim:

* the stored platform role (ADMIN/SUPER_ADMIN) and the existing trusted
  central-model-admin binding are read exactly as the administrator hub reads
  them;
* the existing verified operator account keeps the model administrator
  entitlement it already had.

Fail-closed: a missing binding, an unreadable role table or an exception
never becomes a paid model entitlement. The result is derived only from
server state, never from a browser flag, a tier, a username or a client-sent
email.
"""
from __future__ import annotations

from .platform_admin_authority import platform_authority_for


async def is_model_admin(request, user_id: str) -> bool:
    """Whether the signed account holds administrator model entitlement.

    The union of the integrated platform administrator role and the existing
    verified operator account. Customer-data authority stays separate and is
    never derived from this result.
    """
    if not isinstance(user_id, str) or not user_id:
        return False
    try:
        authority = platform_authority_for(request)
        if await authority.is_global_model_admin(user_id=user_id):
            return True
    except Exception:
        return False
    store = getattr(request.app.state, "b66_member_admin_store", None)
    verify = getattr(store, "is_google_admin", None) if store is not None else None
    if not callable(verify):
        return False
    try:
        return await verify(user_id) is True
    except Exception:
        return False
