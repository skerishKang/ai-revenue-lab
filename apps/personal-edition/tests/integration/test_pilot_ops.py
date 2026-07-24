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

from app.db import apply_migrations, get_connection
from app.db_runtime import SqliteRuntimeConnection
from scripts.pilot_ops import (
    BenchmarkRunRecord,
    CorrectionRecord,
    DeletionRequestRecord,
    PaymentEvidenceRecord,
    PilotRecordType,
    _create_pilot_table,
    execute_deletion,
    export_evidence,
    list_records,
    pseudonymize_id,
    record_operation,
    reject_or_redact_sensitive,
)


def _setup_pilot_db(db_path: str = ":memory:"):
    conn = get_connection(db_path)
    apply_migrations(conn, "migrations")
    _create_pilot_table(SqliteRuntimeConnection(conn))
    return conn


class TestRecordOperation:
    def test_creates_benchmark_run(self):
        conn = _setup_pilot_db()
        record = BenchmarkRunRecord(
            participant_id="p1",
            benchmark_name="test-benchmark",
            fixture_name="korean_founder",
            run_group="first_edition",
            run_index=0,
            provider="mock",
            advertised_model="mock-v1",
            task_type="full_pipeline",
            started_at="2025-01-01T00:00:00.000Z",
            latency_seconds=1.5,
            success=True,
            validation_result="passed",
        )
        result = record_operation(SqliteRuntimeConnection(conn), record)
        assert result.record_id is not None
        records = list_records(SqliteRuntimeConnection(conn), participant_id="p1")
        assert len(records) == 1
        assert records[0]["record_type"] == "benchmark_run"
        conn.close()

    def test_creates_payment_evidence(self):
        conn = _setup_pilot_db()
        record = PaymentEvidenceRecord(
            participant_id="p1",
            amount=4900.0,
            currency="KRW",
            payment_method="bank_transfer",
            payment_date="2025-01-01",
            internal_reference="ref-001",
        )
        result = record_operation(SqliteRuntimeConnection(conn), record)
        assert result.record_id is not None
        records = list_records(SqliteRuntimeConnection(conn), participant_id="p1")
        assert len(records) == 1
        assert records[0]["record_type"] == "payment_evidence"
        conn.close()

    def test_creates_correction(self):
        conn = _setup_pilot_db()
        record = CorrectionRecord(
            participant_id="p1",
            benchmark_run_id="run-001",
            human_correction_minutes=12.5,
        )
        result = record_operation(SqliteRuntimeConnection(conn), record)
        assert result.record_id is not None
        records = list_records(SqliteRuntimeConnection(conn), participant_id="p1")
        assert len(records) == 1
        assert records[0]["record_type"] == "correction"
        conn.close()


class TestListRecords:
    def test_lists_all_records(self):
        conn = _setup_pilot_db()
        r1 = BenchmarkRunRecord(
            participant_id="p1",
            benchmark_name="test",
            fixture_name="korean_founder",
            run_group="first_edition",
            run_index=0,
            provider="mock",
            advertised_model="mock-v1",
            task_type="full_pipeline",
            started_at="2025-01-01T00:00:00.000Z",
        )
        r2 = PaymentEvidenceRecord(
            participant_id="p1",
            amount=4900.0,
            currency="KRW",
            payment_date="2025-01-01",
            internal_reference="ref-001",
        )
        record_operation(SqliteRuntimeConnection(conn), r1)
        record_operation(SqliteRuntimeConnection(conn), r2)
        records = list_records(SqliteRuntimeConnection(conn), participant_id="p1")
        assert len(records) == 2
        conn.close()

    def test_filters_by_type(self):
        conn = _setup_pilot_db()
        r1 = BenchmarkRunRecord(
            participant_id="p1",
            benchmark_name="test",
            fixture_name="korean_founder",
            run_group="first_edition",
            run_index=0,
            provider="mock",
            advertised_model="mock-v1",
            task_type="full_pipeline",
            started_at="2025-01-01T00:00:00.000Z",
        )
        r2 = PaymentEvidenceRecord(
            participant_id="p1",
            amount=4900.0,
            currency="KRW",
            payment_date="2025-01-01",
            internal_reference="ref-001",
        )
        record_operation(SqliteRuntimeConnection(conn), r1)
        record_operation(SqliteRuntimeConnection(conn), r2)
        records = list_records(
            conn, record_type=PilotRecordType.BENCHMARK_RUN.value
        )
        assert len(records) == 1
        assert records[0]["record_type"] == "benchmark_run"
        conn.close()


class TestFileBackedPersistence:
    def test_close_reopen_preserves_records(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = _setup_pilot_db(db_path)
            r1 = BenchmarkRunRecord(
                participant_id="p1",
                benchmark_name="test",
                fixture_name="korean_founder",
                run_group="first_edition",
                run_index=0,
                provider="mock",
                advertised_model="mock-v1",
                task_type="full_pipeline",
                started_at="2025-01-01T00:00:00.000Z",
            )
            record_operation(SqliteRuntimeConnection(conn), r1)
            conn.close()

            conn2 = _setup_pilot_db(db_path)
            records = list_records(conn2, participant_id="p1")
            assert len(records) == 1
            assert records[0]["record_type"] == "benchmark_run"
            conn2.close()
        finally:
            os.unlink(db_path)


class TestExportEvidence:
    def test_exports_with_pseudonymization(self):
        conn = _setup_pilot_db()
        r1 = BenchmarkRunRecord(
            participant_id="real-participant-id",
            benchmark_name="test",
            fixture_name="korean_founder",
            run_group="first_edition",
            run_index=0,
            provider="mock",
            advertised_model="mock-v1",
            task_type="full_pipeline",
            started_at="2025-01-01T00:00:00.000Z",
        )
        record_operation(SqliteRuntimeConnection(conn), r1)
        exported = export_evidence(SqliteRuntimeConnection(conn), export_safe=True)
        assert len(exported) == 1
        assert exported[0]["participant_id"] != "real-participant-id"
        assert exported[0]["participant_id"].startswith("P-")
        conn.close()

    def test_pseudonymize_id_deterministic(self):
        id1 = pseudonymize_id("participant-1")
        id2 = pseudonymize_id("participant-1")
        assert id1 == id2
        id3 = pseudonymize_id("participant-2")
        assert id1 != id3


class TestDeletionWorkflow:
    def test_execute_deletion(self):
        conn = _setup_pilot_db()
        from app import participant_repository as pt_repo
        pt_repo.create_participant(
            SqliteRuntimeConnection(conn),
            participant_id="p1",
            display_name="Test User",
            preferred_language="ko",
        )
        result = execute_deletion(SqliteRuntimeConnection(conn), "p1", reason="test deletion")
        assert result["deleted"] is True
        records = list_records(SqliteRuntimeConnection(conn), participant_id="p1")
        assert len(records) == 2
        # Deterministic ordering contract: newest first (created_at DESC,
        # rowid DESC). The deletion completion is recorded after the request,
        # so it appears first.
        assert records[0]["record_type"] == "deletion_completion"
        assert records[1]["record_type"] == "deletion_request"
        conn.close()


class TestSensitiveValueDetection:
    def test_rejects_card_number(self):
        with pytest.raises(ValueError, match="card_number"):
            reject_or_redact_sensitive(
                "card number is 4111-1111-1111-1111",
                reject=True,
                field_name="test",
            )

    def test_redacts_email(self):
        result = reject_or_redact_sensitive(
            "email is test@example.com",
            reject=False,
            field_name="test",
        )
        assert "test@example.com" not in result
        assert "[REDACTED-EMAIL]" in result


class TestPaymentEvidenceRestrictions:
    def test_rejects_payer_name(self):
        conn = _setup_pilot_db()
        with pytest.raises(ValueError, match="payer_name"):
            PaymentEvidenceRecord(
                participant_id="p1",
                amount=4900.0,
                currency="KRW",
                payment_date="2025-01-01",
                internal_reference="ref-001",
                data={"payer_name": "John Doe"},
            )

    def test_rejects_card_number_in_data(self):
        conn = _setup_pilot_db()
        with pytest.raises(ValueError, match="card_number"):
            PaymentEvidenceRecord(
                participant_id="p1",
                amount=4900.0,
                currency="KRW",
                payment_date="2025-01-01",
                internal_reference="ref-001",
                data={"card_number": "4111-1111-1111-1111"},
            )
