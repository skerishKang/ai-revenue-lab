"""Identity and membership repository (portal-ready authorization boundary).

Two tables back the authorization model:

* ``external_identities`` maps a verified external identity
  (``provider`` + ``issuer`` + ``subject``, unique) to a product-local record.
* ``product_memberships`` grants a role (``learner`` / ``operator`` /
  ``reviewer``) to an external identity, optionally linked to a learner.

Authentication success alone never grants access: a caller needs an active
external identity AND an active membership with the correct role AND resource
ownership. Roles are never auto-granted from email, domain, or IdP claims — a
membership row must exist.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass

ROLE_LEARNER = "learner"
ROLE_OPERATOR = "operator"
ROLE_REVIEWER = "reviewer"
_ROLES = frozenset({ROLE_LEARNER, ROLE_OPERATOR, ROLE_REVIEWER})

STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class ExternalIdentityRecord:
    id: str
    provider: str
    issuer: str
    subject: str
    email: str | None
    status: str
    created_at: str
    updated_at: str

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE


@dataclass(frozen=True)
class ProductMembershipRecord:
    id: str
    external_identity_id: str
    role: str
    learner_id: str | None
    status: str
    created_at: str
    revoked_at: str | None

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE and self.revoked_at is None


_EI_COLS = ["id", "provider", "issuer", "subject", "email", "status", "created_at", "updated_at"]
_EI_SELECT = ", ".join(_EI_COLS)

_PM_COLS = ["id", "external_identity_id", "role", "learner_id", "status", "created_at", "revoked_at"]
_PM_SELECT = ", ".join(_PM_COLS)


def _ei_row(row: sqlite3.Row) -> ExternalIdentityRecord:
    return ExternalIdentityRecord(
        id=row["id"],
        provider=row["provider"],
        issuer=row["issuer"],
        subject=row["subject"],
        email=row["email"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _pm_row(row: sqlite3.Row) -> ProductMembershipRecord:
    return ProductMembershipRecord(
        id=row["id"],
        external_identity_id=row["external_identity_id"],
        role=row["role"],
        learner_id=row["learner_id"],
        status=row["status"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )


# ---------------------------------------------------------------------------
# external_identities
# ---------------------------------------------------------------------------
def get_external_identity(
    conn: sqlite3.Connection, provider: str, issuer: str, subject: str
) -> ExternalIdentityRecord | None:
    row = conn.execute(
        f"SELECT {_EI_SELECT} FROM external_identities "
        "WHERE provider = ? AND issuer = ? AND subject = ?",
        (provider, issuer, subject),
    ).fetchone()
    return _ei_row(row) if row else None


def get_external_identity_by_id(
    conn: sqlite3.Connection, identity_id: str
) -> ExternalIdentityRecord | None:
    row = conn.execute(
        f"SELECT {_EI_SELECT} FROM external_identities WHERE id = ?", (identity_id,)
    ).fetchone()
    return _ei_row(row) if row else None


def ensure_external_identity(
    conn: sqlite3.Connection,
    *,
    provider: str,
    issuer: str,
    subject: str,
    email: str | None = None,
    commit: bool = False,
) -> ExternalIdentityRecord:
    """Get-or-create an external identity (idempotent on the unique triple)."""
    existing = get_external_identity(conn, provider, issuer, subject)
    if existing is not None:
        return existing
    now = _utcnow()
    identity_id = f"eid_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO external_identities ({_EI_SELECT}) VALUES ({','.join('?' for _ in _EI_COLS)})",
        (identity_id, provider, issuer, subject, email, STATUS_ACTIVE, now, now),
    )
    if commit:
        conn.commit()
    return get_external_identity_by_id(conn, identity_id)  # type: ignore[return-value]


def revoke_external_identity(
    conn: sqlite3.Connection, identity_id: str, *, commit: bool = False
) -> bool:
    cur = conn.execute(
        "UPDATE external_identities SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
        (STATUS_REVOKED, _utcnow(), identity_id, STATUS_ACTIVE),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# product_memberships
# ---------------------------------------------------------------------------
def grant_membership(
    conn: sqlite3.Connection,
    *,
    external_identity_id: str,
    role: str,
    learner_id: str | None = None,
    commit: bool = False,
) -> ProductMembershipRecord:
    if role not in _ROLES:
        raise ValueError(f"invalid role: {role!r}")
    now = _utcnow()
    membership_id = f"mem_{secrets.token_urlsafe(16)}"
    conn.execute(
        f"INSERT INTO product_memberships ({_PM_SELECT}) VALUES ({','.join('?' for _ in _PM_COLS)})",
        (membership_id, external_identity_id, role, learner_id, STATUS_ACTIVE, now, None),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        f"SELECT {_PM_SELECT} FROM product_memberships WHERE id = ?", (membership_id,)
    ).fetchone()
    return _pm_row(row)  # type: ignore[return-value]


def get_active_membership(
    conn: sqlite3.Connection, external_identity_id: str, role: str
) -> ProductMembershipRecord | None:
    row = conn.execute(
        f"SELECT {_PM_SELECT} FROM product_memberships "
        "WHERE external_identity_id = ? AND role = ? AND status = ? AND revoked_at IS NULL",
        (external_identity_id, role, STATUS_ACTIVE),
    ).fetchone()
    return _pm_row(row) if row else None


def get_memberships_for_identity(
    conn: sqlite3.Connection, external_identity_id: str
) -> list[ProductMembershipRecord]:
    rows = conn.execute(
        f"SELECT {_PM_SELECT} FROM product_memberships "
        "WHERE external_identity_id = ? ORDER BY created_at",
        (external_identity_id,),
    ).fetchall()
    return [_pm_row(r) for r in rows]


def revoke_membership(
    conn: sqlite3.Connection, membership_id: str, *, commit: bool = False
) -> bool:
    cur = conn.execute(
        "UPDATE product_memberships SET status = ?, revoked_at = ? WHERE id = ? AND status = ?",
        (STATUS_REVOKED, _utcnow(), membership_id, STATUS_ACTIVE),
    )
    if commit:
        conn.commit()
    return cur.rowcount > 0
