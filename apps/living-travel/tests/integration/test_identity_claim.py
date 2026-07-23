"""Integration tests for external identity mapping and invitation claim."""

from __future__ import annotations

import sqlite3

import pytest

from app import external_identity_repository as eid_repo
from app.firebase import PROVIDER_FIREBASE
from app.invitation_claim import claim_invitation
from app.security import create_traveler_token
from app.traveler_repository import create_traveler


def _make_traveler_with_code(conn: sqlite3.Connection, name: str = "T") -> tuple[str, str]:
    rec = create_traveler(conn, display_name=name, destination="Seoul")
    _token_id, raw_code = create_traveler_token(conn, rec.id)
    return rec.id, raw_code


class TestExternalIdentityRepository:
    def test_ensure_identity_idempotent(self, temp_db):
        a = eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-1")
        b = eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-1")
        assert a.id == b.id

    def test_provider_subject_unique(self, temp_db):
        eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-1")
        with pytest.raises(Exception):
            temp_db.execute(
                "INSERT INTO external_identities "
                "(id, provider, subject, principal_type, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("eid_dup", PROVIDER_FIREBASE, "uid-1", "pending", "2025-01-01T00:00:00Z"),
            )
        temp_db.rollback()

    def test_cannot_link_both_traveler_and_operator(self, temp_db):
        rec = create_traveler(temp_db, display_name="X", destination="Seoul")
        identity = eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-2")
        eid_repo.link_traveler(temp_db, identity.id, rec.id)
        # operator link must be refused once traveler is linked
        assert eid_repo.link_operator(temp_db, identity.id, "op_x") is None

    def test_revoke_marks_identity(self, temp_db):
        identity = eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-3")
        assert eid_repo.revoke_identity(temp_db, identity.id)
        assert eid_repo.get_identity_by_id(temp_db, identity.id).is_revoked


class TestInvitationClaim:
    def test_valid_claim_links_identity(self, temp_db):
        traveler_id, code = _make_traveler_with_code(temp_db)
        result = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-a", invitation_code=code
        )
        assert result.ok
        assert result.traveler_id == traveler_id
        identity = eid_repo.get_identity(temp_db, PROVIDER_FIREBASE, "uid-a")
        assert identity is not None
        assert identity.traveler_id == traveler_id

    def test_invalid_code_rejected(self, temp_db):
        _make_traveler_with_code(temp_db)
        result = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-b", invitation_code="wrong"
        )
        assert not result.ok
        assert result.error == "invalid_invitation"

    def test_claim_replay_rejected(self, temp_db):
        traveler_id, code = _make_traveler_with_code(temp_db)
        first = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-c", invitation_code=code
        )
        assert first.ok
        # The code is consumed; replaying it must fail.
        second = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-c", invitation_code=code
        )
        assert not second.ok
        assert second.error == "invalid_invitation"

    def test_foreign_uid_reclaim_rejected(self, temp_db):
        traveler_id, code = _make_traveler_with_code(temp_db)
        first = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-d", invitation_code=code
        )
        assert first.ok
        # Issue a fresh code for the SAME traveler; a different UID tries to claim.
        _tid, code2 = create_traveler_token(temp_db, traveler_id)
        second = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-other", invitation_code=code2
        )
        assert not second.ok
        assert second.error == "invalid_invitation"

    def test_same_identity_idempotent(self, temp_db):
        traveler_id, code = _make_traveler_with_code(temp_db)
        first = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-e", invitation_code=code
        )
        assert first.ok
        _tid, code2 = create_traveler_token(temp_db, traveler_id)
        second = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-e", invitation_code=code2
        )
        assert second.ok
        assert second.traveler_id == traveler_id

    def test_inactive_traveler_rejected(self, temp_db):
        traveler_id, code = _make_traveler_with_code(temp_db)
        temp_db.execute(
            "UPDATE travelers SET status = 'inactive' WHERE id = ?", (traveler_id,)
        )
        temp_db.commit()
        result = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-f", invitation_code=code
        )
        assert not result.ok
        assert result.error == "traveler_inactive"

    def test_revoked_identity_rejected(self, temp_db):
        _traveler_id, code = _make_traveler_with_code(temp_db)
        identity = eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-g")
        eid_repo.revoke_identity(temp_db, identity.id)
        result = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-g", invitation_code=code
        )
        assert not result.ok
        assert result.error == "identity_revoked"

    def test_operator_cannot_claim(self, temp_db):
        _traveler_id, code = _make_traveler_with_code(temp_db)
        identity = eid_repo.ensure_identity(temp_db, PROVIDER_FIREBASE, "uid-op")
        eid_repo.link_operator(temp_db, identity.id, "op_uid-op")
        result = claim_invitation(
            temp_db, provider=PROVIDER_FIREBASE, subject="uid-op", invitation_code=code
        )
        assert not result.ok
        assert result.error == "invalid_invitation"
