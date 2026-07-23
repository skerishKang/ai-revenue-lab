"""Staging bootstrap for Living Learning (operator-only, idempotent).

Creates the synthetic identities needed for staging acceptance:
  * a controlled learner (external_identity + learner + learner membership)
  * a controlled operator/reviewer (external_identity + operator membership)
  * an optional unauthorized outsider (external_identity only, NO membership)

Membership is created EXPLICITLY here; login alone never creates a membership.
Each step is convergent/idempotent — an interrupted bootstrap converges to the
complete state on re-run. The whole bootstrap is serialized with an advisory
lock. No real email or Firebase UID is used; subjects are synthetic placeholders.

Usage:
    python -m app.production.bootstrap
"""

from __future__ import annotations

import hashlib
import secrets
from contextlib import contextmanager

from app.identity import FIREBASE_ISSUER
from app.production.database import ConfigurationError, connect_postgres
from app.repositories.identity_repository import (
    ROLE_LEARNER,
    ROLE_OPERATOR,
    ensure_external_identity,
    get_active_membership,
    grant_membership,
)
from app.repositories.learner_repository import create_learner

PROVIDER = "firebase"

# Synthetic, non-real subjects (placeholders; not real emails or Firebase UIDs).
STAGING_LEARNER_SUBJECT = "staging-learner"
STAGING_OPERATOR_SUBJECT = "staging-operator"
STAGING_OUTSIDER_SUBJECT = "staging-outsider"

BOOTSTRAP_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"living-learning:operator-bootstrap").digest()[:8], "big", signed=True
)


@contextmanager
def bootstrap_lock(conn):
    raw = getattr(conn, "raw", conn)
    raw.execute("SELECT pg_advisory_lock(%s)", (BOOTSTRAP_LOCK_KEY,))
    try:
        yield
    finally:
        raw.execute("SELECT pg_advisory_unlock(%s)", (BOOTSTRAP_LOCK_KEY,))


def ensure_learner(conn) -> str:
    """Ensure the controlled learner identity + learner row + membership."""
    identity = ensure_external_identity(
        conn, provider=PROVIDER, issuer=FIREBASE_ISSUER, subject=STAGING_LEARNER_SUBJECT, commit=True
    )
    existing = get_active_membership(conn, identity.id, ROLE_LEARNER)
    if existing and existing.learner_id:
        return existing.learner_id
    learner = create_learner(conn, topic="Python", display_name="스테이징 학습자", commit=True)
    grant_membership(conn, external_identity_id=identity.id, role=ROLE_LEARNER, learner_id=learner.id, commit=True)
    return learner.id


def ensure_operator(conn) -> str:
    """Ensure the controlled operator identity + operator membership."""
    identity = ensure_external_identity(
        conn, provider=PROVIDER, issuer=FIREBASE_ISSUER, subject=STAGING_OPERATOR_SUBJECT, commit=True
    )
    if not get_active_membership(conn, identity.id, ROLE_OPERATOR):
        grant_membership(conn, external_identity_id=identity.id, role=ROLE_OPERATOR, commit=True)
    return identity.id


def ensure_outsider(conn) -> str:
    """Ensure an unauthorized outsider identity (NO membership)."""
    identity = ensure_external_identity(
        conn, provider=PROVIDER, issuer=FIREBASE_ISSUER, subject=STAGING_OUTSIDER_SUBJECT, commit=True
    )
    return identity.id


def run_bootstrap(conn) -> dict:
    with bootstrap_lock(conn):
        learner_id = ensure_learner(conn)
        operator_id = ensure_operator(conn)
        outsider_id = ensure_outsider(conn)
        return {"learner_id": learner_id, "operator_identity_id": operator_id, "outsider_identity_id": outsider_id}


def main() -> None:
    from app.config import get_settings

    settings = get_settings()
    url = settings.effective_migration_url
    if not url or not (url.startswith("postgresql://") or url.startswith("postgres://")):
        raise ConfigurationError("bootstrap requires a postgresql:// LL_MIGRATION_DATABASE_URL")
    conn = connect_postgres(url, autocommit=True)
    try:
        result = run_bootstrap(conn)
        # Print only non-secret logical ids.
        print(f"bootstrap complete: learner_id={result['learner_id']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
