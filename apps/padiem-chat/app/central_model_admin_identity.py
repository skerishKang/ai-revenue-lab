"""#4428 Global model administrator identity — independent from B66 admins.

Host-only trusted PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL plus existing D1
verified Google subject. Never accepts email, admin role or tenant from browser.
"""
from __future__ import annotations

import re
from typing import Any

from .history import _row_to_dict, _user_id

_UID = re.compile(r"usr_[0-9a-f]{32}\Z")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")


class D1CentralModelAdminAuthorizer:
    """Global administrator identity check, not a B66 membership delegation."""

    def __init__(self, db: Any, *, verified_owner_email: str):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("central model admin requires canonical auth D1")
        if not isinstance(verified_owner_email, str):
            raise ValueError("central model admin owner email must be configured")
        email = verified_owner_email.strip().lower()
        if not email or len(email) > 254 or _EMAIL.fullmatch(email) is None:
            raise ValueError("central model admin owner email must be a valid trusted setting")
        self._db = db
        self._email = email

    async def is_global_model_admin(self, *, user_id: str) -> bool:
        if not isinstance(user_id, str) or _UID.fullmatch(user_id) is None:
            return False
        sql = (
            "SELECT u.provider_subject FROM users u "
            "LEFT JOIN password_credentials pc ON pc.user_id=u.id "
            "WHERE u.id=? AND u.auth_provider='google' "
            "AND lower(u.email)=? AND pc.user_id IS NULL LIMIT 1"
        )
        result = self._db.prepare(sql).bind(user_id, self._email)
        row = _row_to_dict(await result.first())
        subject = row.get("provider_subject") if row else None
        return bool(
            isinstance(subject, str) and subject
            and not subject.startswith("password:")
            and _user_id(subject) == user_id
        )
