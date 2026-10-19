"""#5118 integrated administrator roles over the existing PADIEM_CHAT_DB.

The product session already identifies a canonical ``usr_`` account. This
module adds only the role mapping that the existing users table does not have.
It never creates an account, credential, or browser-supplied identity.

A stored role is usable only when the user row still proves the canonical id:
a Google row whose id hashes from its provider subject, or a password
compatibility row whose id hashes from its password username. An arbitrary
users row with a hand-written id can never gain a role.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .history import _password_user_id, _row_to_dict, _user_id

ROLE_ADMIN = "ADMIN"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLES = frozenset((ROLE_ADMIN, ROLE_SUPER_ADMIN))
_UID = re.compile(r"usr_[0-9a-f]{32}\Z")


class AdminRoleTargetMissing(Exception):
    """The requested user is absent or is not a canonical product account."""


class AdminRoleActorMissing(Exception):
    """The authenticated actor row no longer proves its canonical identity."""


@dataclass(frozen=True, slots=True)
class AdminRoleAssignment:
    user_id: str
    role: str
    previous_role: str | None
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "role": self.role,
            "previous_role": self.previous_role,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class AdminRoleRevocation:
    user_id: str
    revoked: bool
    previous_role: str | None
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "revoked": self.revoked,
            "previous_role": self.previous_role,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _valid_uid(value: object) -> bool:
    return isinstance(value, str) and _UID.fullmatch(value) is not None


class D1PlatformAdminRoleStore:
    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("platform admin role store requires canonical D1")
        if not callable(getattr(db, "batch", None)):
            raise ValueError("platform admin role store requires D1 batch()")
        self._db = db

    async def _first(self, sql: str, *params: Any) -> dict[str, Any] | None:
        statement = self._db.prepare(sql)
        return _row_to_dict(await statement.bind(*params).first())

    async def _canonical_user(self, user_id: object) -> dict[str, Any] | None:
        if not _valid_uid(user_id):
            return None
        row = await self._first(
            "SELECT u.auth_provider, u.provider_subject, pc.username "
            "FROM users u LEFT JOIN password_credentials pc ON pc.user_id=u.id "
            "WHERE u.id=? LIMIT 1",
            user_id,
        )
        if row is None or row.get("auth_provider") != "google":
            return None
        subject = row.get("provider_subject")
        if not isinstance(subject, str) or not subject:
            return None
        if subject.startswith("password:"):
            username = row.get("username")
            if not isinstance(username, str) or subject != "password:" + username:
                return None
            return row if _password_user_id(username) == user_id else None
        return row if _user_id(subject) == user_id else None

    async def _stored_role(self, user_id: str) -> str | None:
        row = await self._first(
            "SELECT role FROM platform_admin_roles WHERE user_id=?", user_id
        )
        role = row.get("role") if row else None
        return role if role in ROLES else None

    async def _stored_assignment(self, user_id: str) -> tuple[str | None, str | None]:
        row = await self._first(
            "SELECT role, updated_at FROM platform_admin_roles WHERE user_id=?",
            user_id,
        )
        if row is None:
            return None, None
        role = row.get("role") if row.get("role") in ROLES else None
        updated = row.get("updated_at")
        return role, updated if isinstance(updated, str) else None

    async def role_for(self, user_id: str) -> str | None:
        """Return the stored role only for a currently canonical account."""
        if await self._canonical_user(user_id) is None:
            return None
        return await self._stored_role(user_id)

    async def assign(
        self, *, actor_user_id: str, target_user_id: str, role: str
    ) -> AdminRoleAssignment:
        if role not in ROLES:
            raise ValueError("unsupported admin role")
        if await self._canonical_user(actor_user_id) is None:
            raise AdminRoleActorMissing("actor is not a canonical account")
        if await self._canonical_user(target_user_id) is None:
            raise AdminRoleTargetMissing("target is not a canonical account")
        previous, previous_updated = await self._stored_assignment(target_user_id)
        now = _now()
        if previous == role:
            return AdminRoleAssignment(
                target_user_id, role, previous, previous_updated or now
            )
        statements = [
            self._db.prepare(
                "INSERT INTO platform_admin_roles "
                "(user_id, role, granted_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "role=excluded.role, granted_by=excluded.granted_by, "
                "updated_at=excluded.updated_at"
            ).bind(target_user_id, role, actor_user_id, now, now),
            self._db.prepare(
                "INSERT INTO platform_admin_role_audit "
                "(target_user_id, actor_user_id, previous_role, current_role, changed_at) "
                "VALUES (?, ?, ?, ?, ?)"
            ).bind(target_user_id, actor_user_id, previous, role, now),
        ]
        await self._db.batch(statements)
        return AdminRoleAssignment(target_user_id, role, previous, now)

    async def revoke(
        self, *, actor_user_id: str, target_user_id: str
    ) -> AdminRoleRevocation:
        if await self._canonical_user(actor_user_id) is None:
            raise AdminRoleActorMissing("actor is not a canonical account")
        previous, previous_updated = await self._stored_assignment(target_user_id)
        now = _now()
        if previous is None:
            return AdminRoleRevocation(target_user_id, False, None, now)
        statements = [
            self._db.prepare(
                "DELETE FROM platform_admin_roles WHERE user_id=?"
            ).bind(target_user_id),
            self._db.prepare(
                "INSERT INTO platform_admin_role_audit "
                "(target_user_id, actor_user_id, previous_role, current_role, changed_at) "
                "VALUES (?, ?, ?, NULL, ?)"
            ).bind(target_user_id, actor_user_id, previous, now),
        ]
        await self._db.batch(statements)
        return AdminRoleRevocation(
            target_user_id, True, previous, previous_updated or now
        )
