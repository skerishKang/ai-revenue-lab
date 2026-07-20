"""Tests for the benchmark runner module.

Tests the benchmark runner's ability to:
- Run fixture bundles against MockProvider
- Record provider/model identity
- Distinguish provider failure from model-quality failure
- Support repeated runs
- Record token/latency/retry accounting
- Persist benchmark records to file-backed SQLite
"""

import json
import os
import sys
import tempfile

import pytest

_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_DIR))

from app.db import get_connection
from app.pipeline.fixtures import list_bundles
from scripts.benchmark import (
    _classify_failure,
    _create_benchmark_table,
    _ensure_participant,
    _provider_info,
    _setup_benchmark_db,
    run_benchmark,
)


class TestClassifyFailure:
    def test_passed_returns_none(self):
        assert _classify_failure("passed", None) is None

    def test_schema_mismatch_is_model_quality(self):
        assert _classify_failure("failed", "schema_mismatch") == "model_quality"

    def test_invalid_json_is_model_quality(self):
        assert _classify_failure("failed", "invalid_json") == "model_quality"

    def test_provider_error_is_provider(self):
        assert _classify_failure("failed", "provider_error") == "provider"

    def test_timeout_is_provider(self):
        assert _classify_failure("failed", "timeout") == "provider"

    def test_connection_error_is_provider(self):
        assert _classify_failure("failed", "connection_error") == "provider"

    def test_rate_limit_is_provider(self):
        assert _classify_failure("failed", "rate_limit") == "provider"

    def test_none_error_is_model_quality(self):
        assert _classify_failure("failed", None) == "model_quality"


class TestBenchmarkDbSetup:
    def test_creates_benchmark_table(self):
        conn = get_connection(":memory:")
        _create_benchmark_table(conn)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "benchmark_runs" in table_names
        conn.close()

    def test_setup_benchmark_db_applies_migrations(self):
        conn = _setup_benchmark_db(":memory:")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "participants" in table_names
        assert "benchmark_runs" in table_names
        conn.close()


class TestEnsureParticipant:
    def test_creates_participant(self):
        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(conn)
        assert pid == "bench-synthetic-participant"
        assert inp_id is not None
        conn.close()

    def test_idempotent(self):
        conn = _setup_benchmark_db(":memory:")
        pid1, inp1 = _ensure_participant(conn)
        pid2, inp2 = _ensure_participant(conn)
        assert pid1 == pid2
        assert inp1 != inp2
        conn.close()


class TestBenchmarkRun:
    def test_single_fixture_mock_provider(self):
        results = run_benchmark(
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 1
        r = results[0]
        assert r["fixture"] == "korean_founder"
        assert r["run_index"] == 0
        assert r["success"] is True
        assert r["failure_category"] is None
        assert r["latency_seconds"] >= 0
        assert r["validation_result"] == "passed"

    def test_multiple_fixtures(self):
        available = list_bundles()
        if len(available) < 2:
            pytest.skip("need at least 2 fixtures")
        results = run_benchmark(
            fixture_names=available[:2],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 2
        assert results[0]["fixture"] != results[1]["fixture"]

    def test_repeated_runs(self):
        results = run_benchmark(
            fixture_names=["korean_founder"],
            repeat=3,
            db_path=":memory:",
        )
        assert len(results) == 3
        for i, r in enumerate(results):
            assert r["run_index"] == i
            assert r["success"] is True

    def test_provider_failure_classification(self):
        from app.ai.mock import MockProvider
        from app.pipeline.fixtures import load_bundle
        from app.pipeline.service import GenerationRequest, GenerationService
        from scripts.benchmark import (
            _run_fixture_once,
            _ensure_participant,
            _setup_benchmark_db,
            _provider_info,
        )

        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(conn)
        fixture = load_bundle("korean_founder")

        failing_provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
        )
        info = _provider_info(failing_provider)
        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        result = _run_fixture_once(
            provider=failing_provider,
            fixture=fixture,
            db_conn=conn,
            participant_id=pid,
            input_id=inp_id,
            run_index=0,
            benchmark_name="test-fail",
        )

        assert result["success"] is False
        assert result["failure_category"] == "provider"
        conn.close()

    def test_benchmark_record_persisted(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            results = run_benchmark(
                fixture_names=["korean_founder"],
                repeat=1,
                db_path=db_path,
            )
            conn = get_connection(db_path)
            rows = conn.execute(
                "SELECT * FROM benchmark_runs WHERE fixture_name = 'korean_founder'"
            ).fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row["provider"] == "mockprovider"
            assert row["advertised_model"] == "mock-personal-edition-v1"
            assert row["success"] == 1
            assert row["is_provider_failure"] == 0
            assert row["is_model_quality_failure"] == 0
            conn.close()
        finally:
            os.unlink(db_path)

    def test_output_json_report(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            results = run_benchmark(
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            assert "benchmark_name" in report
            assert report["provider"] == "mockprovider"
            assert report["advertised_model"] == "mock-personal-edition-v1"
            assert report["total_runs"] == 1
            assert len(report["results"]) == 1
        finally:
            os.unlink(output_path)

    def test_no_credentials_in_benchmark_records(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            run_benchmark(
                fixture_names=["korean_founder"],
                repeat=1,
                db_path=db_path,
            )
            conn = get_connection(db_path)
            rows = conn.execute("SELECT * FROM benchmark_runs").fetchall()
            for row in rows:
                all_values = " ".join(
                    str(row[col]) for col in row.keys() if row[col] is not None
                )
                assert "sk-" not in all_values.lower()
                assert "api_key" not in all_values.lower()
                assert "bearer" not in all_values.lower()
            conn.close()
        finally:
            os.unlink(db_path)
