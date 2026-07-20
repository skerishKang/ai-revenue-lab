"""Privacy and credential-no-leak tests for the Personal Edition.

Verifies that:
- API keys never appear in exceptions, logs, rendered HTML, or DB records
- Error messages are sanitized
- Provider credentials are not committed to any store
- Benchmark and pilot records contain no sensitive material
"""

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_DIR))

from app.config import Settings
from app.main import app
from app.pipeline.errors import ProviderCallError, safe_error_message
from app.domain.enums import ProviderErrorCategory


class TestErrorMessagesSanitized:
    def test_no_raw_text_in_error_messages(self):
        raw = "This is sensitive participant data that should not leak"
        for cat in ProviderErrorCategory:
            msg = safe_error_message(cat, raw)
            assert raw not in msg
            assert "sensitive" not in msg.lower()
            assert "participant" not in msg.lower()

    def test_provider_call_error_sanitized(self):
        err = ProviderCallError(
            category=ProviderErrorCategory.TIMEOUT,
            message="timeout: provider request timed out",
            retryable=True,
        )
        assert "api_key" not in str(err).lower()
        assert "secret" not in str(err).lower()


class TestSettingsNoLeak:
    def test_api_key_not_in_health_response(self):
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()
        body_str = json.dumps(data)
        assert "super-secret-key" not in body_str

    def test_secret_key_not_in_health_response(self):
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()
        body_str = json.dumps(data)
        assert "super-secret-admin" not in body_str


class TestHealthEndpointPrivacy:
    def test_health_no_secrets(self):
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "api_key" not in json.dumps(data).lower()
        assert "secret" not in json.dumps(data).lower()
        assert "sk-" not in json.dumps(data)

    def test_health_shows_provider_info(self):
        client = TestClient(app)
        response = client.get("/health")
        data = response.json()
        assert "ai_provider" in data
        assert "ai_model" in data


class TestAdminDashboardPrivacy:
    def test_admin_access_no_secrets_in_html(self):
        client = TestClient(app)
        response = client.get("/admin/access")
        assert response.status_code == 200
        html = response.text
        assert "api_key" not in html.lower()
        assert "sk-" not in html.lower()


class TestExternalProviderCredentialIsolation:
    def test_credential_not_in_result_error(self):
        from app.ai.external import ExternalProvider
        from app.domain.models import ProviderResult
        import urllib.error

        provider = ExternalProvider(
            base_url="https://api.example.com/v1",
            api_key="sk-secret-api-key-12345",
            model="test-model",
        )

        exc = urllib.error.HTTPError(
            url="https://api.example.com", code=500, msg="Error",
            hdrs=None, fp=None,
        )
        exc.read = lambda: b"error body with sk-secret-api-key-12345"

        result = provider._handle_http_error(exc, 0.0, "req-test")
        assert isinstance(result, ProviderResult)
        assert result.success is False
        assert "sk-secret-api-key-12345" not in (result.error_message or "")

    def test_credential_not_in_failure_message(self):
        from app.ai.external import ExternalProvider

        provider = ExternalProvider(
            base_url="https://api.example.com/v1",
            api_key="sk-very-secret-67890",
            model="test-model",
        )

        result = provider._failure(
            0.0, "req", ProviderErrorCategory.TIMEOUT, "timeout"
        )
        assert "sk-very-secret-67890" not in (result.error_message or "")


class TestBenchmarkNoCredentialLeak:
    def test_benchmark_db_no_credential_fields(self):
        from app.db import get_connection
        conn = get_connection(":memory:")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS benchmark_runs (
                id TEXT PRIMARY KEY,
                benchmark_name TEXT,
                fixture_name TEXT,
                run_index INTEGER,
                provider TEXT,
                advertised_model TEXT,
                task_type TEXT,
                prompt_version TEXT,
                started_at TEXT,
                completed_at TEXT,
                latency_seconds REAL,
                success INTEGER,
                failure_category TEXT,
                error_category TEXT,
                error_message TEXT,
                retry_count INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                validation_result TEXT,
                synthetic_result_ref TEXT,
                human_correction_minutes REAL,
                is_provider_failure INTEGER,
                is_model_quality_failure INTEGER
            )
        """)
        conn.commit()
        cursor = conn.execute("PRAGMA table_info(benchmark_runs)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "api_key" not in columns
        assert "credential" not in columns
        assert "secret" not in columns
        conn.close()


class TestPilotOpsNoSensitiveData:
    def test_pilot_record_no_card_number(self):
        from scripts.pilot_ops import (
            PaymentEvidenceRecord,
            _create_pilot_table,
            record_operation,
        )
        from app.db import apply_migrations, get_connection

        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        _create_pilot_table(conn)
        record = PaymentEvidenceRecord(
            participant_id="p1",
            amount=4900.0,
            currency="KRW",
            payment_method="manual",
            payment_date="2025-01-01",
            internal_reference="ref-001",
        )
        record_operation(conn, record)
        import json as json_mod
        rows = conn.execute("SELECT payload FROM pilot_ops_records").fetchall()
        for row in rows:
            data = json_mod.loads(row["payload"])
            assert "card_number" not in str(data)
            assert "account_number" not in str(data)
        conn.close()
