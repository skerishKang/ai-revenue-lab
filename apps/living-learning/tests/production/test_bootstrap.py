"""Staging bootstrap idempotency contracts.

The ensure_* steps are convergent/idempotent: re-running creates nothing new and
never overwrites existing rows. Membership is created explicitly (login alone
never creates a membership). Tested against SQLite (the ensure_* steps use the
backend-neutral repositories); the advisory-lock wrapper is PostgreSQL-only.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db import apply_migrations
from app.production.bootstrap import (
    STAGING_LEARNER_SUBJECT,
    STAGING_OPERATOR_SUBJECT,
    STAGING_OUTSIDER_SUBJECT,
    ensure_learner,
    ensure_operator,
    ensure_outsider,
)
from app.identity import FIREBASE_ISSUER
from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    get_active_membership,
    get_external_identity,
    get_memberships_for_identity,
)


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "bootstrap.db")
    apply_migrations(db_path)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    yield c
    c.close()


def test_ensure_learner_idempotent(conn):
    learner_id_1 = ensure_learner(conn)
    learner_id_2 = ensure_learner(conn)
    # Re-run returns the same learner; no duplicate identity/membership.
    assert learner_id_1 == learner_id_2
    identity = get_external_identity(conn, "firebase", FIREBASE_ISSUER, STAGING_LEARNER_SUBJECT)
    memberships = get_memberships_for_identity(conn, identity.id)
    learner_memberships = [m for m in memberships if m.role == ROLE_LEARNER and m.status == "active"]
    assert len(learner_memberships) == 1
    assert learner_memberships[0].learner_id == learner_id_1


def test_ensure_operator_idempotent(conn):
    op_1 = ensure_operator(conn)
    op_2 = ensure_operator(conn)
    assert op_1 == op_2
    identity = get_external_identity(conn, "firebase", FIREBASE_ISSUER, STAGING_OPERATOR_SUBJECT)
    memberships = get_memberships_for_identity(conn, identity.id)
    operator_memberships = [m for m in memberships if m.role == ROLE_OPERATOR and m.status == "active"]
    assert len(operator_memberships) == 1
    # Operator membership has no learner_id (role invariant).
    assert operator_memberships[0].learner_id is None


def test_outsider_has_no_membership(conn):
    outsider_id = ensure_outsider(conn)
    ensure_outsider(conn)  # idempotent
    identity = get_external_identity(conn, "firebase", FIREBASE_ISSUER, STAGING_OUTSIDER_SUBJECT)
    assert identity.id == outsider_id
    # No membership => authentication alone grants nothing.
    assert get_memberships_for_identity(conn, identity.id) == []
    assert get_active_membership(conn, identity.id, ROLE_LEARNER) is None
    assert get_active_membership(conn, identity.id, ROLE_OPERATOR) is None
