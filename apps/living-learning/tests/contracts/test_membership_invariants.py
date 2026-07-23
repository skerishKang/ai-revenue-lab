"""P1: membership invariants.

DB-level role/learner_id constraints, one-active-learner-per-identity, and
issuer validation at the identity boundary.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import apply_migrations
from app.factory import create_app
from app.identity import FakeIdentityVerifier, IdentityPrincipal, reset_identity_verifier, set_identity_verifier
from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    ensure_external_identity,
    grant_membership,
)

from tests.contracts.conftest import bootstrap_learner


def _conn(file_db):
    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_learner_membership_requires_learner_id(file_db):
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="s1", commit=True)
        with pytest.raises(ValueError):
            grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, learner_id=None, commit=True)
    finally:
        conn.close()


def test_operator_membership_rejects_learner_id(file_db):
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="s2", commit=True)
        with pytest.raises(ValueError):
            grant_membership(conn, external_identity_id=identity.id, role=ROLE_OPERATOR, learner_id="L1", commit=True)
    finally:
        conn.close()


def test_duplicate_active_learner_membership_rejected(file_db):
    """One external identity may hold at most one active learner membership."""
    learner_id, _ = bootstrap_learner(file_db)
    learner_id_2, _ = bootstrap_learner(file_db)
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="s3", commit=True)
        grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, learner_id=learner_id, commit=True)
        with pytest.raises(sqlite3.IntegrityError):
            grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, learner_id=learner_id_2, commit=True)
    finally:
        conn.close()


def test_learner_db_check_enforced_at_schema_level(file_db):
    """The CHECK constraint rejects a learner row with NULL learner_id even via raw SQL."""
    conn = _conn(file_db)
    try:
        identity = ensure_external_identity(conn, provider="firebase", issuer="iss", subject="s4", commit=True)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO product_memberships (id, external_identity_id, role, learner_id, status) "
                "VALUES ('m_bad', ?, 'learner', NULL, 'active')",
                (identity.id,),
            )
    finally:
        conn.close()


def test_wrong_firebase_issuer_rejected():
    """A verified principal whose issuer is not the expected identity project is rejected."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    apply_migrations(path)
    learner_id, _ = bootstrap_learner(path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # Provision an identity + membership for the subject (so only the issuer is wrong).
    identity = ensure_external_identity(
        conn, provider="firebase", issuer="evil-issuer", subject="wrong-iss-sub", commit=True
    )
    grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, learner_id=learner_id, commit=True)
    conn.close()

    verifier = FakeIdentityVerifier(
        {
            "wrong-issuer-token": IdentityPrincipal(
                issuer="evil-issuer", subject="wrong-iss-sub", email_verified=True
            )
        }
    )
    set_identity_verifier(verifier)
    try:
        settings = Settings(database_url=path, provider_type="mock", provider_model="mock-fixture")
        app = create_app(settings)
        client = TestClient(app)
        resp = client.get("/api/v1/me", headers={"Authorization": "Bearer wrong-issuer-token"})
        assert resp.status_code == 401
    finally:
        reset_identity_verifier()
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                if os.path.exists(path + suffix):
                    os.unlink(path + suffix)
            except PermissionError:
                pass
