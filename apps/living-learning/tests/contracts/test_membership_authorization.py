"""Membership authorization: Firebase auth alone never grants access.

Access requires an active external identity AND an active product membership
with the correct role. Roles are never auto-granted; a membership row must exist
and can be revoked.
"""

from __future__ import annotations

import sqlite3

from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    ensure_external_identity,
    get_active_membership,
    get_external_identity,
    grant_membership,
    revoke_external_identity,
    revoke_membership,
)

from tests.contracts.conftest import bootstrap_learner


def _conn(file_db):
    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_ensure_external_identity_is_idempotent(file_db):
    conn = _conn(file_db)
    try:
        a = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="sub-1", commit=True)
        b = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="sub-1", commit=True)
        assert a.id == b.id
        # A different subject is a distinct identity.
        c = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="sub-2", commit=True)
        assert c.id != a.id
    finally:
        conn.close()


def test_unique_provider_issuer_subject_enforced(file_db):
    conn = _conn(file_db)
    try:
        ensure_external_identity(conn, provider="firebase", issuer="iss", subject="dup", commit=True)
        try:
            conn.execute(
                "INSERT INTO external_identities (id, provider, issuer, subject, status) "
                "VALUES ('x', 'firebase', 'iss', 'dup', 'active')"
            )
            conn.commit()
            assert False, "expected unique constraint failure"
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_membership_grants_role(file_db):
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="learner-1", commit=True)
        grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, commit=True)
        membership = get_active_membership(conn, identity.id, ROLE_LEARNER)
        assert membership is not None
        assert membership.role == ROLE_LEARNER
        # No operator membership was auto-granted.
        assert get_active_membership(conn, identity.id, ROLE_OPERATOR) is None
    finally:
        conn.close()


def test_revoked_membership_is_not_active(file_db):
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="learner-2", commit=True)
        membership = grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, commit=True)
        assert get_active_membership(conn, identity.id, ROLE_LEARNER) is not None
        revoke_membership(conn, membership.id, commit=True)
        assert get_active_membership(conn, identity.id, ROLE_LEARNER) is None
    finally:
        conn.close()


def test_revoked_identity_is_inactive(file_db):
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="learner-3", commit=True)
        assert identity.is_active
        revoke_external_identity(conn, identity.id, commit=True)
        refreshed = get_external_identity(conn, "firebase", "iss", "learner-3")
        assert not refreshed.is_active
    finally:
        conn.close()


def test_learner_membership_can_link_to_real_learner(file_db):
    learner_id, _ = bootstrap_learner(file_db)
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="learner-4", commit=True)
        grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, learner_id=learner_id, commit=True)
        membership = get_active_membership(conn, identity.id, ROLE_LEARNER)
        assert membership.learner_id == learner_id
    finally:
        conn.close()
