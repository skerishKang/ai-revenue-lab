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
from app.domain.enums import ProviderErrorCategory
from app.pipeline.errors import NOT_ATTEMPTED, VALIDATION_FAILED, VALIDATION_PASSED
from app.pipeline.fixtures import list_bundles, load_bundle
from app.pipeline.service import GenerationRequest, GenerationService
from scripts.benchmark import (
    _classify_failure,
    _classify_failure_detailed,
    _create_benchmark_table,
    _ensure_participant,
    _provider_info,
    _setup_benchmark_db,
    _token_total,
    _sum_non_null_tokens,
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

    def test_response_format_unsupported_is_provider(self):
        assert _classify_failure("provider_failed", "response_format_unsupported") == "provider"

    def test_schema_rejected_is_provider(self):
        assert _classify_failure("provider_failed", "schema_rejected") == "provider"


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
        pid, inp_id = _ensure_participant(
            conn, participant_id="bench-synthetic-participant"
        )
        assert pid == "bench-synthetic-participant"
        assert inp_id is not None
        conn.close()

    def test_idempotent(self):
        conn = _setup_benchmark_db(":memory:")
        pid1, inp1 = _ensure_participant(
            conn, participant_id="bench-synthetic-participant"
        )
        pid2, inp2 = _ensure_participant(
            conn, participant_id="bench-synthetic-participant"
        )
        assert pid1 == pid2
        assert inp1 != inp2
        conn.close()


class TestBenchmarkRun:
    def test_single_fixture_mock_provider(self):
        results = run_benchmark(
            task="first_edition",
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
            task="first_edition",
            fixture_names=available[:2],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 2
        assert results[0]["fixture"] != results[1]["fixture"]

    def test_repeated_runs(self):
        results = run_benchmark(
            task="first_edition",
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
            _ensure_participant,
            _setup_benchmark_db,
            _provider_info,
        )

        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(
            conn, participant_id="bench-test-fail"
        )
        fixture = load_bundle("korean_founder")

        failing_provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
        )
        info = _provider_info(failing_provider)

        service = GenerationService(provider=failing_provider)
        request = GenerationRequest(
            participant_id=pid,
            input_id=inp_id,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        )
        result = service.generate_edition(conn, request=request)

        assert result.succeeded is False
        conn.close()

    def test_benchmark_record_persisted(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            results = run_benchmark(
                task="first_edition",
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
                task="first_edition",
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
                task="first_edition",
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


class TestFailureTaxonomy:
    def test_passed_returns_none_category_and_detail(self):
        cat, detail = _classify_failure_detailed(VALIDATION_PASSED, None)
        assert cat is None
        assert detail is None

    def test_timeout_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.TIMEOUT.value
        )
        assert cat == "provider"
        assert detail == "timeout"

    def test_connection_error_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.CONNECTION_ERROR.value
        )
        assert cat == "provider"
        assert detail == "connection_error"

    def test_rate_limit_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.RATE_LIMIT.value
        )
        assert cat == "provider"
        assert detail == "rate_limit"

    def test_auth_failure_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.AUTH_FAILURE.value
        )
        assert cat == "provider"
        assert detail == "auth_failure"

    def test_provider_error_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.PROVIDER_ERROR.value
        )
        assert cat == "provider"
        assert detail == "provider_error"

    def test_response_format_unsupported_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed",
            ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED.value,
        )
        assert cat == "provider"
        assert detail == "response_format_unsupported"

    def test_schema_rejected_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.SCHEMA_REJECTED.value
        )
        assert cat == "provider"
        assert detail == "schema_rejected"

    def test_refusal_is_provider(self):
        cat, detail = _classify_failure_detailed(
            "provider_failed", ProviderErrorCategory.REFUSAL.value
        )
        assert cat == "provider"
        assert detail == "refusal"

    def test_schema_mismatch_is_model_quality(self):
        cat, detail = _classify_failure_detailed(
            "failed", ProviderErrorCategory.SCHEMA_MISMATCH.value
        )
        assert cat == "model_quality"
        assert detail == "schema_mismatch"

    def test_invalid_json_is_model_quality(self):
        cat, detail = _classify_failure_detailed(
            "failed", ProviderErrorCategory.INVALID_JSON.value
        )
        assert cat == "model_quality"
        assert detail == "invalid_json"

    def test_none_error_with_validation_failed_is_deterministic(self):
        cat, detail = _classify_failure_detailed(VALIDATION_FAILED, None)
        assert cat == "model_quality"
        assert detail == "deterministic_validation"

    def test_none_error_with_provider_failed_is_unknown(self):
        cat, detail = _classify_failure_detailed("provider_failed", None)
        assert cat == "model_quality"
        assert detail == "unknown"

    def test_backward_compat_classify_failure(self):
        assert _classify_failure(VALIDATION_PASSED, None) is None
        assert _classify_failure("failed", "timeout") == "provider"
        assert _classify_failure("failed", "schema_mismatch") == "model_quality"
        assert _classify_failure("failed", None) == "model_quality"

    def test_all_provider_categories_map_to_provider(self):
        provider_cats = [
            "timeout", "connection_error", "rate_limit", "auth_failure",
            "provider_error", "response_format_unsupported", "schema_rejected",
            "refusal",
        ]
        for cat_val in provider_cats:
            cat, detail = _classify_failure_detailed("provider_failed", cat_val)
            assert cat == "provider", f"expected provider for {cat_val}"
            assert detail == cat_val

    def test_all_model_quality_categories_map_to_model_quality(self):
        mq_cats = ["schema_mismatch", "invalid_json"]
        for cat_val in mq_cats:
            cat, detail = _classify_failure_detailed("failed", cat_val)
            assert cat == "model_quality", f"expected model_quality for {cat_val}"
            assert detail == cat_val

    def test_failure_details_is_frozen(self):
        from scripts.benchmark import _FAILURE_DETAILS
        assert "rate_limit" in _FAILURE_DETAILS
        assert "auth_failure" in _FAILURE_DETAILS
        assert "timeout" in _FAILURE_DETAILS
        assert "connection_error" in _FAILURE_DETAILS
        assert "provider_error" in _FAILURE_DETAILS
        assert "response_format_unsupported" in _FAILURE_DETAILS
        assert "schema_rejected" in _FAILURE_DETAILS
        assert "refusal" in _FAILURE_DETAILS
        assert "invalid_json" in _FAILURE_DETAILS
        assert "schema_mismatch" in _FAILURE_DETAILS
        assert "deterministic_validation" in _FAILURE_DETAILS
        assert "grounding_failure" in _FAILURE_DETAILS
        assert "upstream_plan_failed" in _FAILURE_DETAILS
        assert "first_edition_setup_failed" in _FAILURE_DETAILS
        assert "not_attempted" in _FAILURE_DETAILS
        assert "unknown" in _FAILURE_DETAILS


class TestPipelineStageTracking:
    def test_first_edition_success_has_no_failure_stage(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 1
        r = results[0]
        assert r["success"] is True
        assert r["failure_stage"] is None
        assert r["failure_category"] is None
        assert r["failure_detail"] is None
        assert r["plan_attempted"] is True
        assert r["draft_attempted"] is True
        assert r["provider_call_count"] == 2
        assert len(r["generation_run_refs"]) == 2

    def test_first_edition_plan_attempted_tracked(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "plan_attempted" in r
        assert "draft_attempted" in r
        assert isinstance(r["plan_attempted"], bool)
        assert isinstance(r["draft_attempted"], bool)

    def test_editorial_plan_has_failure_stage(self):
        results = run_benchmark(
            task="editorial_plan",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 1
        r = results[0]
        assert "failure_stage" in r
        assert "failure_detail" in r
        assert "generation_run_refs" in r
        assert "provider_call_count" in r

    def test_adversarial_grounding_has_stage_tracking(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "plan_attempted" in r
        assert "draft_attempted" in r
        assert "failure_stage" in r
        assert "failure_detail" in r

    def test_db_has_failure_detail_column(self):
        conn = _setup_benchmark_db(":memory:")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()}
        assert "failure_detail" in cols
        assert "failure_stage" in cols
        assert "generation_run_refs" in cols
        conn.close()

    def test_benchmark_record_has_failure_detail(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                db_path=db_path,
            )
            conn = get_connection(db_path)
            row = conn.execute(
                "SELECT failure_detail, failure_stage, generation_run_refs "
                "FROM benchmark_runs LIMIT 1"
            ).fetchone()
            assert row is not None
            assert row["failure_detail"] is None or isinstance(row["failure_detail"], str)
            assert row["failure_stage"] is None or isinstance(row["failure_stage"], str)
            conn.close()
        finally:
            os.unlink(db_path)


class TestTokenAccounting:
    def test_token_total_none_when_both_none(self):
        assert _token_total(None, None) is None

    def test_token_total_sums_when_both_present(self):
        assert _token_total(100, 50) == 150

    def test_token_total_treats_none_as_zero_when_other_present(self):
        assert _token_total(100, None) == 100
        assert _token_total(None, 50) == 50

    def test_sum_non_null_tokens_empty_list(self):
        assert _sum_non_null_tokens([]) is None

    def test_sum_non_null_tokens_all_none(self):
        assert _sum_non_null_tokens([None, None]) is None

    def test_sum_non_null_tokens_mixed(self):
        assert _sum_non_null_tokens([100, None, 50]) == 150

    def test_sum_non_null_tokens_all_present(self):
        assert _sum_non_null_tokens([10, 20, 30]) == 60

    def test_tokens_null_when_pipeline_not_executed(self):
        from app.ai.mock import MockProvider
        from scripts.benchmark import _ensure_participant, _setup_benchmark_db

        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(conn, participant_id="bench-token-test")
        fixture = load_bundle("korean_founder")

        failing_provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
        )

        service = GenerationService(provider=failing_provider)
        request = GenerationRequest(
            participant_id=pid,
            input_id=inp_id,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        )
        result = service.generate_edition(conn, request=request)

        from scripts.benchmark import _collect_tokens
        inp, out = _collect_tokens(conn, result.plan_run.run_id, result.draft_run.run_id)
        assert inp is None
        assert out is None
        assert _token_total(inp, out) is None
        conn.close()

    def test_success_result_has_token_fields(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "input_tokens" in r
        assert "output_tokens" in r
        assert "total_tokens" in r
        if r["success"]:
            assert r["total_tokens"] is None or isinstance(r["total_tokens"], int)


class TestProviderCallAccounting:
    def test_first_edition_has_provider_call_count(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "provider_call_count" in r
        assert "generation_run_refs" in r
        assert isinstance(r["provider_call_count"], int)
        assert isinstance(r["generation_run_refs"], list)
        assert r["provider_call_count"] == len(r["generation_run_refs"])

    def test_editorial_plan_has_generation_run_refs(self):
        results = run_benchmark(
            task="editorial_plan",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "generation_run_refs" in r
        assert "provider_call_count" in r
        assert r["provider_call_count"] == len(r["generation_run_refs"])

    def test_generation_run_refs_are_strings(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        for ref in r["generation_run_refs"]:
            assert isinstance(ref, str)
            assert len(ref) > 0

    def test_generation_run_refs_persisted_in_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                db_path=db_path,
            )
            conn = get_connection(db_path)
            row = conn.execute(
                "SELECT generation_run_refs FROM benchmark_runs LIMIT 1"
            ).fetchone()
            assert row is not None
            refs = json.loads(row["generation_run_refs"])
            assert isinstance(refs, list)
            assert len(refs) == 2
            conn.close()
        finally:
            os.unlink(db_path)


class TestBenchmarkTableMigration:
    def test_idempotent_migration_on_existing_db(self):
        conn = get_connection(":memory:")
        conn.execute(
            """
            CREATE TABLE benchmark_runs (
                id TEXT PRIMARY KEY,
                benchmark_name TEXT NOT NULL,
                fixture_name TEXT NOT NULL,
                run_group TEXT NOT NULL DEFAULT 'default',
                run_index INTEGER NOT NULL,
                provider TEXT NOT NULL,
                advertised_model TEXT NOT NULL,
                task_type TEXT NOT NULL,
                prompt_version TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                latency_seconds REAL,
                success INTEGER NOT NULL DEFAULT 0,
                failure_category TEXT CHECK(failure_category IS NULL OR failure_category IN ('provider', 'model_quality')),
                error_category TEXT,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                validation_result TEXT,
                synthetic_result_ref TEXT,
                human_correction_minutes REAL,
                is_provider_failure INTEGER NOT NULL DEFAULT 0,
                is_model_quality_failure INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()

        _create_benchmark_table(conn)

        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()
        }
        assert "failure_detail" in cols
        assert "failure_stage" in cols
        assert "generation_run_refs" in cols
        assert "run_group" in cols
        conn.close()

    def test_migration_preserves_existing_data(self):
        conn = get_connection(":memory:")
        conn.execute(
            """
            CREATE TABLE benchmark_runs (
                id TEXT PRIMARY KEY,
                benchmark_name TEXT NOT NULL,
                fixture_name TEXT NOT NULL,
                run_group TEXT NOT NULL DEFAULT 'default',
                run_index INTEGER NOT NULL,
                provider TEXT NOT NULL,
                advertised_model TEXT NOT NULL,
                task_type TEXT NOT NULL,
                prompt_version TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                latency_seconds REAL,
                success INTEGER NOT NULL DEFAULT 0,
                failure_category TEXT CHECK(failure_category IS NULL OR failure_category IN ('provider', 'model_quality')),
                error_category TEXT,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                validation_result TEXT,
                synthetic_result_ref TEXT,
                human_correction_minutes REAL,
                is_provider_failure INTEGER NOT NULL DEFAULT 0,
                is_model_quality_failure INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO benchmark_runs "
            "(id, benchmark_name, fixture_name, run_index, provider, "
            "advertised_model, task_type, started_at, success) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("test-id", "bench-test", "korean_founder", 0, "mock",
             "mock-v1", "full_pipeline", "2025-01-01T00:00:00.000Z", 1),
        )
        conn.commit()

        _create_benchmark_table(conn)

        row = conn.execute(
            "SELECT * FROM benchmark_runs WHERE id = 'test-id'"
        ).fetchone()
        assert row is not None
        assert row["provider"] == "mock"
        assert row["success"] == 1
        conn.close()

    def test_migration_called_twice_no_error(self):
        conn = get_connection(":memory:")
        _create_benchmark_table(conn)
        _create_benchmark_table(conn)
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()
        }
        assert "failure_detail" in cols
        conn.close()


class TestFeedbackSetupPreservation:
    def test_setup_failure_preserves_latency(self):
        from app.ai.mock import MockProvider
        from scripts.benchmark import _ensure_participant, _setup_benchmark_db
        from app.pipeline.service import GenerationRequest, GenerationService

        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(conn, participant_id="bench-fb-test")
        fixture = load_bundle("korean_founder")

        failing_provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
        )
        service = GenerationService(provider=failing_provider)
        request = GenerationRequest(
            participant_id=pid,
            input_id=inp_id,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        )
        first_result = service.generate_edition(conn, request=request)

        assert not first_result.succeeded

        from scripts.benchmark import (
            _collect_tokens,
            _record_benchmark_run,
            _now_iso,
            _provider_info,
            _token_total,
        )

        input_tokens, output_tokens = _collect_tokens(
            conn,
            first_result.plan_run.run_id,
            first_result.draft_run.run_id,
        )
        total_retry = (
            first_result.plan_run.retry_count
            + first_result.draft_run.retry_count
        )

        started_at = _now_iso()
        _record_benchmark_run(
            conn,
            benchmark_name="bench-test",
            fixture_name="korean_founder",
            run_group="feedback_second_edition",
            run_index=0,
            provider_info=_provider_info(failing_provider),
            task_type="full_pipeline",
            prompt_version="plan+draft",
            started_at=started_at,
            completed_at=_now_iso(),
            latency_seconds=0.5,
            success=False,
            failure_category="pipeline_prevented",
            error_category=first_result.plan_run.error_category,
            error_message="first edition failed during feedback setup",
            retry_count=total_retry,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=_token_total(input_tokens, output_tokens),
            validation_result="failed",
            synthetic_result_ref="bench-test-setup-fail",
            failure_detail="first_edition_setup_failed",
            failure_stage="plan",
            generation_run_refs=[
                r for r in [
                    first_result.plan_run.run_id,
                    first_result.draft_run.run_id,
                ] if r
            ],
        )

        row = conn.execute(
            "SELECT failure_category, failure_detail, failure_stage, "
            "latency_seconds, retry_count "
            "FROM benchmark_runs WHERE synthetic_result_ref = 'bench-test-setup-fail'"
        ).fetchone()
        assert row is not None
        assert row["failure_category"] == "pipeline_prevented"
        assert row["failure_detail"] == "first_edition_setup_failed"
        assert row["failure_stage"] == "plan"
        assert row["latency_seconds"] > 0
        assert row["retry_count"] >= 0
        conn.close()

    def test_setup_failure_preserves_tokens(self):
        from app.ai.mock import MockProvider
        from scripts.benchmark import (
            _ensure_participant,
            _setup_benchmark_db,
            _collect_tokens,
            _token_total,
        )
        from app.pipeline.service import GenerationRequest, GenerationService

        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(conn, participant_id="bench-fb-tok")
        fixture = load_bundle("korean_founder")

        failing_provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
        )
        service = GenerationService(provider=failing_provider)
        request = GenerationRequest(
            participant_id=pid,
            input_id=inp_id,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        )
        first_result = service.generate_edition(conn, request=request)

        input_tokens, output_tokens = _collect_tokens(
            conn,
            first_result.plan_run.run_id,
            first_result.draft_run.run_id,
        )

        assert input_tokens is None
        assert output_tokens is None
        assert _token_total(input_tokens, output_tokens) is None
        conn.close()
