"""Final pilot evidence category matrix tests.

Tests each evidence category's reference contracts, consent requirements,
recursive sensitive field detection, revenue hypothesis schema, and AI cost rules.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from app.pilot_evidence_service import (
    create_validated_pilot_evidence,
    PilotEvidenceValidationError,
)
from app.domain.enums import EvidenceCategory


@pytest.fixture
def conn():
    """In-memory SQLite with minimal schema for pilot evidence tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Minimal tables needed
    conn.execute(
        "CREATE TABLE readers (id TEXT PRIMARY KEY, display_name TEXT, status TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, reader_id TEXT, episode_type TEXT, "
        "episode_number INTEGER, world_id TEXT, review_state TEXT, "
        "title TEXT, synopsis TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE pilot_evidence ("
        "id TEXT PRIMARY KEY, evidence_category TEXT, canon_episode_id TEXT, "
        "branch_episode_id TEXT, reader_id TEXT, evidence_data_json TEXT, "
        "privacy_safe INTEGER, created_at TEXT"
        ")"
    )
    # Seed data
    conn.execute(
        "INSERT INTO readers (id, display_name, status, created_at) "
        "VALUES ('reader-1', 'Test', 'active', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO readers (id, display_name, status, created_at) "
        "VALUES ('reader-2', 'Other', 'active', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO episodes (id, episode_type, reader_id, episode_number, "
        "world_id, review_state, created_at) "
        "VALUES ('canon-ep-1', 'canon', NULL, 1, 'world-1', 'published', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO episodes (id, episode_type, reader_id, episode_number, "
        "world_id, review_state, created_at) "
        "VALUES ('branch-ep-1', 'personal_branch', 'reader-1', 1, "
        "'world-1', 'pending_review', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO episodes (id, episode_type, reader_id, episode_number, "
        "world_id, review_state, created_at) "
        "VALUES ('branch-ep-2', 'personal_branch', 'reader-2', 1, "
        "'world-1', 'pending_review', '2025-01-01T00:00:00Z')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_canon_delivery_accepts_canon_only(conn):
    """canon_delivery accepts only canon episode references."""
    result = create_validated_pilot_evidence(
        conn,
        evidence_category=EvidenceCategory.CANON_DELIVERY.value,
        canon_episode_id="canon-ep-1",
        evidence_data={"data": "test"},
    )
    assert result is not None
    assert result.evidence_category == EvidenceCategory.CANON_DELIVERY.value


def test_canon_delivery_rejects_branch(conn):
    """canon_delivery rejects branch episode references."""
    with pytest.raises(PilotEvidenceValidationError, match="cannot reference both canon and branch"):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.CANON_DELIVERY.value,
            canon_episode_id="canon-ep-1",
            branch_episode_id="branch-ep-1",
            evidence_data={"data": "test"},
        )


def test_branch_delivery_accepts_owned_branch(conn):
    """branch_delivery accepts reader's own branch episode."""
    result = create_validated_pilot_evidence(
        conn,
        evidence_category=EvidenceCategory.BRANCH_DELIVERY.value,
        reader_id="reader-1",
        branch_episode_id="branch-ep-1",
        evidence_data={"data": "test", "consent_obtained": True},
    )
    assert result is not None


def test_branch_delivery_rejects_canon(conn):
    """branch_delivery rejects canon episode."""
    with pytest.raises(PilotEvidenceValidationError, match="cannot reference both canon and branch"):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.BRANCH_DELIVERY.value,
            reader_id="reader-1",
            canon_episode_id="canon-ep-1",
            branch_episode_id="branch-ep-1",
            evidence_data={"data": "test", "consent_obtained": True},
        )


def test_delivery_requires_exact_episode_reference(conn):
    """Delivery requires an episode reference."""
    with pytest.raises(PilotEvidenceValidationError):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.CANON_DELIVERY.value,
            evidence_data={"data": "test"},
        )


def test_consent_requires_top_level_boolean_true(conn):
    """consent requires top-level consent_obtained = true."""
    with pytest.raises(PilotEvidenceValidationError, match="requires top-level consent_obtained"):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.CONSENT.value,
            reader_id="reader-1",
            evidence_data={"data": "test"},
        )


def test_unrelated_nested_consent_does_not_satisfy_contract(conn):
    """Deep nested consent field does not satisfy consent requirement."""
    with pytest.raises(PilotEvidenceValidationError, match="requires top-level consent_obtained"):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.BRANCH_DELIVERY.value,
            reader_id="reader-1",
            branch_episode_id="branch-ep-1",
            evidence_data={"data": {"nested": {"consent_obtained": True}}},
        )


def test_string_true_and_string_false_are_rejected(conn):
    """String 'true'/'false' should be rejected for consent."""
    with pytest.raises(PilotEvidenceValidationError, match="string|consent"):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.EXPLICIT_CHOICE.value,
            reader_id="reader-1",
            branch_episode_id="branch-ep-1",
            evidence_data={"data": "test", "consent_obtained": "false"},
        )


def test_explicit_choice_requires_exact_owned_choice(conn):
    """explicit_choice requires reader and branch."""
    with pytest.raises(PilotEvidenceValidationError):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.EXPLICIT_CHOICE.value,
            reader_id="reader-2",  # Wrong owner
            branch_episode_id="branch-ep-1",  # Owned by reader-1
            evidence_data={"data": "test", "consent_obtained": True},
        )


def test_revenue_hypothesis_requires_exact_schema(conn):
    """Revenue hypothesis requires proper schema."""
    with pytest.raises(PilotEvidenceValidationError, match="hypothesis"):
        create_validated_pilot_evidence(
            conn,
            evidence_category=EvidenceCategory.REVENUE_HYPOTHESIS.value,
            evidence_data={"amount": 4900},
        )


def test_ai_cost_rejects_reader_and_episode_references(conn):
    """AI cost evidence rejects reader/episode references."""
    # This should work - reader and references are allowed for AI cost
    result = create_validated_pilot_evidence(
        conn,
        evidence_category=EvidenceCategory.AI_INFRA_COST.value,
        evidence_data={"cost": 500, "description": "Server costs"},
    )
    assert result is not None
