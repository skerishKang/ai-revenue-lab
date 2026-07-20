"""Tests for pilot operations recording.

Verifies:
- Record creation for all pilot event types
- File-backed persistence (close/reopen)
- Privacy: no sensitive payment details stored
- No credential leakage in records
"""

import json
import os
import sys
import tempfile

import pytest

_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_DIR))

from app.db import get_connection
from scripts.pilot_ops import (
    _create_pilot_table,
    export_pilot_evidence,
    get_participant_records,
    record_costs,
    record_correction,
    record_deletion,
    record_engagement,
    record_invitation,
    record_offer,
    record_payment_evidence,
    record_revenue,
    record_sample_edition,
)


def _setup_pilot_db(db_path: str = ":memory:"):
    conn = get_connection(db_path)
    _create_pilot_table(conn)
    return conn


class TestRecordInvitation:
    def test_creates_invitation(self):
        conn = _setup_pilot_db()
        rid = record_invitation(
            conn, "p1",
            contact_method="email",
            consent_confirmed=True,
            notes="Test invitation",
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert len(records) == 1
        assert records[0]["record_type"] == "invitation"
        assert records[0]["record"]["consent_confirmed"] is True
        conn.close()


class TestRecordSampleEdition:
    def test_creates_sample_edition(self):
        conn = _setup_pilot_db()
        rid = record_sample_edition(
            conn, "p1", "edition-001",
            edition_number=1,
            is_free=True,
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert len(records) == 1
        assert records[0]["record_type"] == "sample_edition"
        assert records[0]["edition_id"] == "edition-001"
        conn.close()


class TestRecordOffer:
    def test_creates_offer(self):
        conn = _setup_pilot_db()
        rid = record_offer(
            conn, "p1",
            editions_count=7,
            price_krw=4900,
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record"]["editions_count"] == 7
        assert records[0]["record"]["price_krw"] == 4900
        conn.close()


class TestRecordPaymentEvidence:
    def test_creates_payment_evidence(self):
        conn = _setup_pilot_db()
        rid = record_payment_evidence(
            conn, "p1",
            amount_krw=4900,
            payment_method="bank_transfer",
            evidence_description="Screenshot of transfer confirmation",
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record_type"] == "payment_evidence"
        assert records[0]["record"]["amount_krw"] == 4900

    def test_no_payer_identity_stored(self):
        conn = _setup_pilot_db()
        record_payment_evidence(
            conn, "p1",
            amount_krw=4900,
            payment_method="bank_transfer",
            evidence_description="transfer proof",
        )
        records = get_participant_records(conn, "p1")
        record_json = json.dumps(records[0]["record"])
        assert "card_number" not in record_json
        assert "account_number" not in record_json
        assert "ssn" not in record_json
        assert "resident_registration" not in record_json
        conn.close()


class TestRecordCorrection:
    def test_creates_correction(self):
        conn = _setup_pilot_db()
        rid = record_correction(
            conn, "p1", "edition-001",
            correction_minutes=12.5,
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record"]["correction_minutes"] == 12.5
        conn.close()


class TestRecordEngagement:
    def test_creates_engagement(self):
        conn = _setup_pilot_db()
        rid = record_engagement(
            conn, "p1", "edition-001",
            feedback_text="Good edition",
            engagement_signal="positive",
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record"]["engagement_signal"] == "positive"
        conn.close()


class TestRecordCosts:
    def test_creates_costs(self):
        conn = _setup_pilot_db()
        rid = record_costs(
            conn, "p1",
            ai_cost_krw=0.0,
            infrastructure_cost_krw=500.0,
        )
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record"]["infrastructure_cost_krw"] == 500.0
        conn.close()


class TestRecordRevenue:
    def test_creates_revenue(self):
        conn = _setup_pilot_db()
        rid = record_revenue(conn, "p1", revenue_krw=4900.0)
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record"]["revenue_krw"] == 4900.0
        conn.close()


class TestRecordDeletion:
    def test_creates_deletion(self):
        conn = _setup_pilot_db()
        rid = record_deletion(conn, "p1", reason="participant requested")
        assert rid is not None
        records = get_participant_records(conn, "p1")
        assert records[0]["record_type"] == "deletion_request"
        conn.close()


class TestFileBackedPersistence:
    def test_close_reopen_preserves_records(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = _setup_pilot_db(db_path)
            record_invitation(conn, "p1", consent_confirmed=True)
            record_offer(conn, "p1", editions_count=7, price_krw=4900)
            conn.close()

            conn2 = _setup_pilot_db(db_path)
            records = get_participant_records(conn2, "p1")
            assert len(records) == 2
            assert records[0]["record_type"] == "invitation"
            assert records[1]["record_type"] == "offer"
            conn2.close()
        finally:
            os.unlink(db_path)


class TestExportEvidence:
    def test_exports_all_records(self):
        conn = _setup_pilot_db()
        record_invitation(conn, "p1", consent_confirmed=True)
        record_invitation(conn, "p2", consent_confirmed=True)
        evidence = export_pilot_evidence(conn)
        assert evidence["total_records"] == 2
        assert set(evidence["participants"]) == {"p1", "p2"}
        conn.close()


class TestNoCredentialInRecords:
    def test_no_structured_credential_fields_in_records(self):
        conn = _setup_pilot_db()
        record_payment_evidence(
            conn, "p1",
            amount_krw=4900,
            payment_method="manual",
            evidence_description="transfer proof",
        )
        records = get_participant_records(conn, "p1")
        record_data = records[0]["record"]
        assert "api_key" not in record_data
        assert "secret" not in record_data
        assert "password" not in record_data
        assert "token" not in record_data
        assert "card_number" not in record_data
        assert "account_number" not in record_data
        conn.close()
