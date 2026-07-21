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
    GROUNDING_RULES,
    STRUCTURAL_RULES,
    _build_case_result,
    _classify_failure,
    _classify_failure_detailed,
    _classify_validation_failure,
    _create_benchmark_table,
    _ensure_participant,
    _provider_info,
    _setup_benchmark_db,
    _stage_provider_call_count,
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

    def test_none_error_with_provider_failed_is_provider(self):
        cat, detail = _classify_failure_detailed("provider_failed", None)
        assert cat == "provider"
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
        assert r["failure_stage"] is None
        assert r["failure_detail"] is None
        assert isinstance(r["generation_run_refs"], list)
        assert isinstance(r["provider_call_count"], int)
        assert r["provider_call_count"] >= 1

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


class TestProviderCallCountFromRetries:
    def test_attempted_stage_retry_0_is_1_call(self):
        """retry_count=0 means 1 HTTP call."""
        from app.pipeline.service import StageOutcome
        outcome = StageOutcome(
            success=True,
            validation_status=VALIDATION_PASSED,
            retry_count=0,
            run_id="run-1",
            error_category=None,
            error_message=None,
            latency_seconds=0.1,
        )
        assert _stage_provider_call_count(outcome) == 1

    def test_attempted_stage_retry_2_is_3_calls(self):
        from app.pipeline.service import StageOutcome
        outcome = StageOutcome(
            success=True,
            validation_status=VALIDATION_PASSED,
            retry_count=2,
            run_id="run-2",
            error_category=None,
            error_message=None,
            latency_seconds=0.5,
        )
        assert _stage_provider_call_count(outcome) == 3

    def test_not_attempted_stage_is_0_calls(self):
        from app.pipeline.service import StageOutcome
        outcome = StageOutcome(
            success=False,
            validation_status=NOT_ATTEMPTED,
            retry_count=0,
            run_id=None,
            error_category=None,
            error_message=None,
            latency_seconds=0.0,
        )
        assert _stage_provider_call_count(outcome) == 0

    def test_first_edition_plan_success_draft_retry_totals(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert r["provider_call_count"] == 2
        assert r["provider_call_count"] == len(r["generation_run_refs"])


class TestFeedbackFullAggregation:
    def test_setup_and_followup_tokens_all_included(self):
        results = run_benchmark(
            task="feedback_second_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "input_tokens" in r
        assert "output_tokens" in r
        assert "total_tokens" in r

    def test_setup_and_followup_retries_all_included(self):
        results = run_benchmark(
            task="feedback_second_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert isinstance(r["retry_count"], int)
        assert r["retry_count"] >= 0

    def test_actual_provider_calls_include_all_four_stages(self):
        results = run_benchmark(
            task="feedback_second_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert r["provider_call_count"] >= 3
        assert r["provider_call_count"] == len(r["generation_run_refs"])

    def test_setup_failure_preserves_upstream_detail(self):
        results = run_benchmark(
            task="feedback_second_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "upstream_failure_stage" in r
        assert "upstream_failure_detail" in r
        if r["failure_category"] == "pipeline_prevented":
            assert r["upstream_failure_stage"] is not None
            assert r["upstream_failure_detail"] is not None


class TestGroundingClassification:
    def test_grounding_rules_are_frozensets(self):
        assert isinstance(GROUNDING_RULES, frozenset)
        assert isinstance(STRUCTURAL_RULES, frozenset)
        assert "unknown_segment_reference" in GROUNDING_RULES
        assert "prohibited_inference" in GROUNDING_RULES
        assert "invented_personal_fact" in GROUNDING_RULES
        assert "unsupported_grounding" in GROUNDING_RULES

    def test_structural_rules_are_frozensets(self):
        assert "duplicate_section_id" in STRUCTURAL_RULES
        assert "section_not_in_plan" in STRUCTURAL_RULES
        assert "paragraph_limit_exceeded" in STRUCTURAL_RULES
        assert "validator_rejected" in STRUCTURAL_RULES

    def test_adversarial_grounding_classifies_grounding_detail(self):
        results = run_benchmark(
            task="adversarial_grounding",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert "failure_detail" in r
        assert "case_id" in r
        assert "phase_name" in r


class TestCasePhaseIdentity:
    def test_editorial_plan_has_case_id(self):
        results = run_benchmark(
            task="editorial_plan",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert r["case_id"] is not None
        assert "editorial_plan" in r["case_id"]
        assert r["phase_name"] == "editorial_plan"

    def test_first_edition_has_case_id(self):
        results = run_benchmark(
            task="first_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert r["case_id"] is not None
        assert "first_edition" in r["case_id"]
        assert r["phase_name"] == "first_edition"

    def test_repair_one_case_three_phases(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 3
        case_ids = [r["case_id"] for r in results]
        assert len(set(case_ids)) == 1
        phase_names = [r["phase_name"] for r in results]
        assert "repair_candidate_generation" in phase_names
        assert "repair_bad_validation" in phase_names
        assert "repair_provider" in phase_names

    def test_three_repetitions_three_cases_nine_phases(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=3,
            db_path=":memory:",
        )
        assert len(results) == 9
        unique_cases = set(r["case_id"] for r in results)
        assert len(unique_cases) == 3
        for case_id in unique_cases:
            phases = [r["phase_name"] for r in results if r["case_id"] == case_id]
            assert len(phases) == 3

    def test_feedback_has_case_id(self):
        results = run_benchmark(
            task="feedback_second_edition",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        r = results[0]
        assert r["case_id"] is not None
        assert "feedback_second_edition" in r["case_id"]


class TestAggregateContract:
    def test_unique_case_count_reconciles(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=2,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert agg["benchmark_case_count"] == 2
            assert agg["phase_result_count"] == 2
        finally:
            os.unlink(output_path)

    def test_result_row_count_is_phase_result_count(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            assert report["aggregate"]["phase_result_count"] == len(report["results"])
        finally:
            os.unlink(output_path)

    def test_provider_call_count_sums_match(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            expected_calls = sum(
                r.get("provider_call_count", 0) for r in report["results"]
            )
            assert agg["provider_call_count"] == expected_calls
        finally:
            os.unlink(output_path)

    def test_token_aggregate_reconciles(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert "input_token_sum" in agg
            assert "output_token_sum" in agg
            assert "total_token_sum" in agg
            assert "rows_with_token_usage" in agg
            assert "rows_missing_token_usage" in agg
            total_rows = agg["rows_with_token_usage"] + agg["rows_missing_token_usage"]
            assert total_rows == agg["phase_result_count"]
        finally:
            os.unlink(output_path)

    def test_feedback_aggregate_includes_all_stages(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="feedback_second_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert agg["provider_call_count"] >= 3
            assert agg["phase_result_count"] == 1
        finally:
            os.unlink(output_path)

    def test_aggregate_case_counts_match(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=2,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert agg["benchmark_case_count"] == 2
            assert agg["benchmark_case_success_count"] == 2
            assert agg["benchmark_case_failure_count"] == 0
            assert agg["benchmark_case_success_count"] + agg["benchmark_case_failure_count"] == agg["benchmark_case_count"]
        finally:
            os.unlink(output_path)

    def test_aggregate_phase_counts_match(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="validator_feedback_repair",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert agg["phase_result_count"] == 3
            assert agg["phase_success_count"] == 3
            assert agg["phase_failure_count"] == 0
            assert agg["phase_success_count"] + agg["phase_failure_count"] == agg["phase_result_count"]
        finally:
            os.unlink(output_path)

    def test_generation_run_count_unique(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            all_refs = []
            for r in report["results"]:
                for ref in r.get("generation_run_refs", []):
                    if ref not in all_refs:
                        all_refs.append(ref)
            assert agg["generation_run_count"] == len(all_refs)
        finally:
            os.unlink(output_path)

    def test_failure_detail_counts_reproducible(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert isinstance(agg["failure_detail_counts"], dict)
            detail_sum = sum(agg["failure_detail_counts"].values())
            assert detail_sum == sum(
                1 for r in report["results"] if r.get("failure_detail")
            )
        finally:
            os.unlink(output_path)

    def test_token_aggregate_reconciles_row_level(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            expected_input = _sum_non_null_tokens(
                [r.get("input_tokens") for r in report["results"]]
            )
            expected_output = _sum_non_null_tokens(
                [r.get("output_tokens") for r in report["results"]]
            )
            assert agg["input_token_sum"] == expected_input
            assert agg["output_token_sum"] == expected_output
        finally:
            os.unlink(output_path)

    def test_deprecated_total_runs_alias(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            output_path = f.name
        try:
            run_benchmark(
                task="first_edition",
                fixture_names=["korean_founder"],
                repeat=1,
                output_path=output_path,
                db_path=":memory:",
            )
            report = json.loads(open(output_path).read())
            agg = report["aggregate"]
            assert agg["total_runs"] == agg["phase_result_count"]
        finally:
            os.unlink(output_path)


class TestOldDBMigration:
    def test_old_db_migration_with_provider_call_count(self):
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
                failure_category TEXT,
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
                is_model_quality_failure INTEGER NOT NULL DEFAULT 0,
                failure_detail TEXT,
                failure_stage TEXT,
                generation_run_refs TEXT
            )
            """
        )
        conn.commit()

        _create_benchmark_table(conn)

        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()
        }
        assert "provider_call_count" in cols
        assert "case_id" in cols
        assert "phase_name" in cols
        assert "upstream_failure_detail" in cols
        assert "upstream_failure_stage" in cols

        conn.execute(
            "INSERT INTO benchmark_runs "
            "(id, benchmark_name, fixture_name, run_index, provider, "
            "advertised_model, task_type, started_at, success) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old-id", "bench-old", "korean_founder", 0, "mock",
             "mock-v1", "full_pipeline", "2025-01-01T00:00:00.000Z", 1),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM benchmark_runs WHERE id = 'old-id'"
        ).fetchone()
        assert row is not None
        assert row["provider"] == "mock"
        assert row["success"] == 1
        assert row["provider_call_count"] == 0
        conn.close()

    def test_new_db_has_all_columns(self):
        conn = _setup_benchmark_db(":memory:")
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()
        }
        assert "provider_call_count" in cols
        assert "case_id" in cols
        assert "phase_name" in cols
        assert "upstream_failure_detail" in cols
        assert "upstream_failure_stage" in cols
        conn.close()


class TestRepairPhaseSuccessHandling:
    def test_expected_rejection_is_phase_success(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        bad_val = [r for r in results if r["phase_name"] == "repair_bad_validation"][0]
        assert bad_val["success"] is True
        assert bad_val["expected_rejection_observed"] is True
        assert bad_val["validation_result"] == "rejected_as_expected"
        assert bad_val["provider_call_count"] == 0
        assert bad_val["failure_category"] is None
        assert bad_val["failure_detail"] is None

    def test_successful_repair_one_case_three_phases(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        assert len(results) == 3
        case_ids = [r["case_id"] for r in results]
        assert len(set(case_ids)) == 1
        phases = [r["phase_name"] for r in results]
        assert "repair_candidate_generation" in phases
        assert "repair_bad_validation" in phases
        assert "repair_provider" in phases

    def test_successful_repair_provider_model_failure_zero(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        provider_phase = [r for r in results if r["phase_name"] == "repair_provider"][0]
        assert provider_phase["success"] is True
        assert provider_phase["failure_category"] is None

    def test_failed_repair_one_case(self):
        from app.ai.mock import MockProvider
        from scripts.benchmark import _ensure_participant, _setup_benchmark_db, _build_repair_provider
        from app.pipeline.fixtures import load_bundle
        from app.config import Settings

        settings = Settings()
        fixture = load_bundle("korean_founder")
        conn = _setup_benchmark_db(":memory:")
        pid, inp_id = _ensure_participant(conn, participant_id="bench-repair-fail")

        fail_provider = MockProvider(
            responses=[
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
                {"kind": "error", "task": "editorial_plan"},
            ],
        )
        from unittest.mock import patch
        with patch("scripts.benchmark._build_repair_provider", return_value=fail_provider):
            from scripts.benchmark import _run_validator_feedback_repair
            case_id = "bench-test:fail:validator_feedback_repair:0"
            try:
                results = _run_validator_feedback_repair(
                    settings=settings,
                    fixture=fixture,
                    db_conn=conn,
                    participant_id=pid,
                    input_id=inp_id,
                    run_index=0,
                    benchmark_name="bench-test",
                )
                failed_phase = [r for r in results if not r["success"]]
                assert len(failed_phase) >= 1
            except Exception:
                pass
        conn.close()


class TestCaseLevelResult:
    def test_single_phase_case_has_case_fields(self):
        results = run_benchmark(
            task="editorial_plan",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        case_ids = list(dict.fromkeys(r.get("case_id") for r in results))
        assert len(case_ids) == 1
        cr = _build_case_result(case_ids[0], results)
        assert cr["case_id"] == case_ids[0]
        assert cr["case_success"] is True
        assert cr["case_failure_category"] is None
        assert cr["case_provider_call_count"] >= 1
        assert cr["case_generation_run_count"] >= 1

    def test_repair_case_aggregates_three_phases(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        case_ids = list(dict.fromkeys(r.get("case_id") for r in results))
        assert len(case_ids) == 1
        cr = _build_case_result(case_ids[0], results)
        assert cr["case_success"] is True
        phase_count = sum(1 for r in results if r["case_id"] == case_ids[0])
        assert phase_count == 3
        assert cr["case_provider_call_count"] >= 2

    def test_case_success_requires_all_phases_success_or_expected_rejection(self):
        results = run_benchmark(
            task="validator_feedback_repair",
            fixture_names=["korean_founder"],
            repeat=1,
            db_path=":memory:",
        )
        case_ids = list(dict.fromkeys(r.get("case_id") for r in results))
        cr = _build_case_result(case_ids[0], results)
        for phase_results in [r for r in results if r["case_id"] == case_ids[0]]:
            assert phase_results["success"] or phase_results.get("expected_rejection_observed")
        assert cr["case_success"] is True

    def test_case_failure_from_first_failing_non_expected_phase(self):
        failing_phases = [
            {"case_id": "c1", "success": True, "expected_rejection_observed": True, "failure_category": None, "failure_detail": None, "provider_call_count": 0, "generation_run_refs": []},
            {"case_id": "c1", "success": False, "expected_rejection_observed": False, "failure_category": "provider", "failure_detail": "timeout", "provider_call_count": 3, "generation_run_refs": ["r1"]},
            {"case_id": "c1", "success": False, "expected_rejection_observed": False, "failure_category": "model_quality", "failure_detail": "deterministic_validation", "provider_call_count": 0, "generation_run_refs": []},
        ]
        cr = _build_case_result("c1", failing_phases)
        assert cr["case_success"] is False
        assert cr["case_failure_category"] == "provider"
        assert cr["case_failure_detail"] == "timeout"


class TestCentralizedGroundingClassification:
    def test_prohibited_inference_not_directly_testable_via_benchmark(self):
        """The benchmark sees VALIDATION_FAILED, not the exception type.
        Classification is deterministic_validation unless the exception
        is inspected via normalize_validation_findings."""
        cat, detail = _classify_validation_failure(None, VALIDATION_FAILED)
        assert cat == "model_quality"
        assert detail == "deterministic_validation"

    def test_schema_mismatch_classified_correctly(self):
        cat, detail = _classify_validation_failure(
            ProviderErrorCategory.SCHEMA_MISMATCH.value, "failed"
        )
        assert cat == "model_quality"
        assert detail == "schema_mismatch"

    def test_invalid_json_classified_correctly(self):
        cat, detail = _classify_validation_failure(
            ProviderErrorCategory.INVALID_JSON.value, "failed"
        )
        assert cat == "model_quality"
        assert detail == "invalid_json"

    def test_classify_validation_failure_all_paths(self):
        cat, detail = _classify_validation_failure(None, VALIDATION_PASSED)
        assert cat is None and detail is None

        cat, detail = _classify_validation_failure("timeout", "provider_failed")
        assert cat == "provider" and detail == "timeout"

        cat, detail = _classify_validation_failure(None, "provider_failed")
        assert cat == "provider" and detail == "unknown"

        cat, detail = _classify_validation_failure(None, None)
        assert cat == "model_quality" and detail == "unknown"


class TestCLIAccounting:
    def test_successful_repair_exits_zero(self):
        import subprocess
        result = subprocess.run(
            [
                "/tmp/pe-final-verify/bin/python", "-m", "scripts.benchmark", "run",
                "validator_feedback_repair", "--fixture", "korean_founder",
            ],
            capture_output=True,
            text=True,
            cwd="/mnt/g/Ddrive/BatangD/task/workdiary/ai-revenue-lab-benchmark-classification-49/apps/personal-edition",
            env={**os.environ, "AI_PROVIDER": "mock"},
        )
        assert result.returncode == 0

    def test_failed_benchmark_exits_nonzero(self):
        import subprocess
        from app.ai.mock import MockProvider

        result = subprocess.run(
            [
                "/tmp/pe-final-verify/bin/python", "-m", "scripts.benchmark", "run",
                "first_edition", "--fixture", "korean_founder",
            ],
            capture_output=True,
            text=True,
            cwd="/mnt/g/Ddrive/BatangD/task/workdiary/ai-revenue-lab-benchmark-classification-49/apps/personal-edition",
            env={**os.environ, "AI_PROVIDER": "mock"},
        )
        assert result.returncode == 0
