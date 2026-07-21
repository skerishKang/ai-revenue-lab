#!/usr/bin/env python3
"""Synthetic runtime benchmark runner for Personal Edition.

Records provider/model identity, task and prompt version, success/failure
category, latency, retry count, token usage, deterministic validation
result, and synthetic result reference.  Never stores raw credentials,
token material, or full generated private output.

Usage:
    python -m scripts.benchmark run <task> [--fixture NAME] [--repeat N] [--output PATH] [--db PATH] [--correct MINUTES]
    python -m scripts.benchmark update-correction --run-id ID --minutes N [--db PATH]

Tasks:
    editorial_plan             Run only the editorial-plan stage
    first_edition              Full pipeline first edition
    feedback_second_edition    Follow-up edition with feedback
    adversarial_grounding      Prohibited-inference grounding test
    validator_feedback_repair  Validation failure then repair

The runner uses the same provider configured for the application via
environment variables (AI_PROVIDER, AI_BASE_URL, AI_MODEL, etc.).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_DIR))

from app.ai.mock import MockProvider
from app.config import Settings
from app.db import apply_migrations, get_connection
from app.domain.enums import ProviderErrorCategory
from app.pipeline.errors import (
    NOT_ATTEMPTED,
    PROVIDER_FAILED,
    VALIDATION_FAILED,
    VALIDATION_PASSED,
)
from app.pipeline.fixtures import (
    FixtureBundle,
    inject_feedback_id,
    list_bundles,
    load_bundle,
)
from app.pipeline.prompts import DRAFT_PROMPT_VERSION, PLAN_PROMPT_VERSION
from app.pipeline.segmentation import segment_text
from app.pipeline.service import (
    GenerationRequest,
    GenerationService,
    RepairRequest,
    _provider_call_with_retry,
)
from app.pipeline import validators as validators_mod
from app.pipeline.validators import normalize_validation_findings
from app.domain.models import EditionContent
from app.pipeline.prompts import (
    DRAFT_PROMPT_VERSION,
    PLAN_PROMPT_VERSION,
    REPAIR_PROMPT_VERSION,
    TASK_EDITORIAL_PLAN,
    TASK_EDITION_DRAFT,
    TASK_EDITION_REPAIR,
)

ALL_TASKS = [
    "editorial_plan",
    "first_edition",
    "feedback_second_edition",
    "adversarial_grounding",
    "validator_feedback_repair",
]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


def _build_provider(settings: Settings, fixture: FixtureBundle | None = None):
    if settings.ai_provider == "mock":
        model = settings.ai_model
        if fixture is not None and fixture.plan_payload and fixture.draft_payload:
            return MockProvider(
                model=model,
                task_payloads={
                    "editorial_plan": fixture.plan_payload,
                    "edition_draft": fixture.draft_payload,
                },
            )
        return MockProvider(model=model)

    if settings.ai_provider == "external" and settings.ai_base_url:
        from app.ai.external import ExternalProvider
        from app.domain.enums import CostClass
        cost_class = CostClass(settings.ai_cost_class)
        return ExternalProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            cost_class=cost_class,
            response_format_mode=settings.ai_response_format_mode,
        )

    raise SystemExit(
        "provider config fail-closed: AI_PROVIDER must be 'mock' "
        "or AI_BASE_URL must be set for an external provider"
    )


def _provider_info(provider: Any) -> dict[str, str]:
    return {
        "provider": getattr(
            provider, "provider", provider.__class__.__name__.lower()
        ),
        "model": getattr(provider, "model", "unknown"),
    }


# ---------------------------------------------------------------------------
# Benchmark DB
# ---------------------------------------------------------------------------


def _create_benchmark_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_runs (
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

    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(benchmark_runs)").fetchall()
    }

    for col, typedef in [
        ("failure_detail", "TEXT"),
        ("failure_stage", "TEXT"),
        ("generation_run_refs", "TEXT"),
        ("provider_call_count", "INTEGER NOT NULL DEFAULT 0"),
        ("case_id", "TEXT"),
        ("phase_name", "TEXT"),
        ("upstream_failure_detail", "TEXT"),
        ("upstream_failure_stage", "TEXT"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE benchmark_runs ADD COLUMN {col} {typedef}")

    if "run_group" not in existing_cols:
        conn.execute(
            "ALTER TABLE benchmark_runs "
            "ADD COLUMN run_group TEXT NOT NULL DEFAULT 'default'"
        )

    has_old_constraint = False
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='benchmark_runs'"
        ).fetchone()
        if row and row[0]:
            ddl = row[0].upper()
            if "CHECK" in ddl and "FAILURE_CATEGORY" in ddl:
                has_old_constraint = True
    except Exception:
        pass

    if has_old_constraint:
        conn.execute("ALTER TABLE benchmark_runs RENAME TO benchmark_runs_old")
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
                generation_run_refs TEXT,
                provider_call_count INTEGER NOT NULL DEFAULT 0,
                case_id TEXT,
                phase_name TEXT,
                upstream_failure_detail TEXT,
                upstream_failure_stage TEXT
            )
            """
        )
        old_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(benchmark_runs_old)").fetchall()
        }
        new_cols_list = [
            "id", "benchmark_name", "fixture_name", "run_group", "run_index",
            "provider", "advertised_model", "task_type", "prompt_version",
            "started_at", "completed_at", "latency_seconds", "success",
            "failure_category", "error_category", "error_message",
            "retry_count", "input_tokens", "output_tokens", "total_tokens",
            "validation_result", "synthetic_result_ref",
            "human_correction_minutes", "is_provider_failure",
            "is_model_quality_failure", "failure_detail", "failure_stage",
            "generation_run_refs", "provider_call_count",
            "case_id", "phase_name",
            "upstream_failure_detail", "upstream_failure_stage",
        ]
        cols_to_copy = [c for c in new_cols_list if c in old_cols]
        placeholders = ", ".join(["?"] * len(cols_to_copy))
        col_names = ", ".join(cols_to_copy)
        rows = conn.execute(
            f"SELECT {col_names} FROM benchmark_runs_old"
        ).fetchall()
        for row in rows:
            conn.execute(
                f"INSERT INTO benchmark_runs ({col_names}) VALUES ({placeholders})",
                tuple(row),
            )
        conn.execute("DROP TABLE benchmark_runs_old")

    conn.commit()


def _record_benchmark_run(
    conn: sqlite3.Connection,
    *,
    benchmark_name: str,
    fixture_name: str,
    run_group: str,
    run_index: int,
    provider_info: dict[str, str],
    task_type: str,
    prompt_version: str | None,
    started_at: str,
    completed_at: str,
    latency_seconds: float,
    success: bool,
    failure_category: str | None,
    error_category: str | None,
    error_message: str | None,
    retry_count: int,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    validation_result: str,
    synthetic_result_ref: str,
    failure_detail: str | None = None,
    failure_stage: str | None = None,
    generation_run_refs: list[str] | None = None,
    provider_call_count: int = 0,
    case_id: str | None = None,
    phase_name: str | None = None,
    upstream_failure_detail: str | None = None,
    upstream_failure_stage: str | None = None,
) -> None:
    run_id = str(uuid.uuid4())
    is_provider = 1 if failure_category == "provider" else 0
    is_model = 1 if failure_category == "model_quality" else 0
    refs_json = json.dumps(generation_run_refs) if generation_run_refs else None
    conn.execute(
        "INSERT INTO benchmark_runs "
        "(id, benchmark_name, fixture_name, run_group, run_index, provider, "
        "advertised_model, task_type, prompt_version, started_at, completed_at, "
        "latency_seconds, success, failure_category, error_category, "
        "error_message, retry_count, input_tokens, output_tokens, total_tokens, "
        "validation_result, synthetic_result_ref, human_correction_minutes, "
        "is_provider_failure, is_model_quality_failure, "
        "failure_detail, failure_stage, generation_run_refs, "
        "provider_call_count, case_id, phase_name, "
        "upstream_failure_detail, upstream_failure_stage) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            benchmark_name,
            fixture_name,
            run_group,
            run_index,
            provider_info["provider"],
            provider_info["model"],
            task_type,
            prompt_version,
            started_at,
            completed_at,
            latency_seconds,
            1 if success else 0,
            failure_category,
            error_category,
            error_message,
            retry_count,
            input_tokens,
            output_tokens,
            total_tokens,
            validation_result,
            synthetic_result_ref,
            is_provider,
            is_model,
            failure_detail,
            failure_stage,
            refs_json,
            provider_call_count,
            case_id,
            phase_name,
            upstream_failure_detail,
            upstream_failure_stage,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------

_FAILURE_DETAILS = frozenset({
    "rate_limit",
    "auth_failure",
    "timeout",
    "connection_error",
    "provider_error",
    "response_format_unsupported",
    "schema_rejected",
    "refusal",
    "invalid_json",
    "schema_mismatch",
    "deterministic_validation",
    "grounding_failure",
    "upstream_plan_failed",
    "first_edition_setup_failed",
    "not_attempted",
    "unknown",
})

_PROVIDER_ERROR_CATEGORIES = frozenset({
    ProviderErrorCategory.TIMEOUT.value,
    ProviderErrorCategory.CONNECTION_ERROR.value,
    ProviderErrorCategory.RATE_LIMIT.value,
    ProviderErrorCategory.AUTH_FAILURE.value,
    ProviderErrorCategory.PROVIDER_ERROR.value,
    ProviderErrorCategory.RESPONSE_FORMAT_UNSUPPORTED.value,
    ProviderErrorCategory.SCHEMA_REJECTED.value,
    ProviderErrorCategory.REFUSAL.value,
})


def _classify_failure_detailed(
    result_validation_status: str | None,
    result_error_category: str | None,
) -> tuple[str | None, str | None]:
    if result_validation_status == VALIDATION_PASSED:
        return None, None

    if result_error_category in _PROVIDER_ERROR_CATEGORIES:
        return "provider", result_error_category

    if result_error_category in (
        ProviderErrorCategory.SCHEMA_MISMATCH.value,
        ProviderErrorCategory.INVALID_JSON.value,
    ):
        return "model_quality", result_error_category

    if result_validation_status == VALIDATION_FAILED:
        return "model_quality", "deterministic_validation"

    return "model_quality", "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_failure(
    result_validation_status: str | None,
    result_error_category: str | None,
) -> str | None:
    category, _detail = _classify_failure_detailed(
        result_validation_status, result_error_category
    )
    return category


def _setup_benchmark_db(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    migrations_dir = str(_DIR / "migrations")
    apply_migrations(conn, migrations_dir)
    _create_benchmark_table(conn)
    return conn


def _ensure_participant(
    conn: sqlite3.Connection,
    participant_id: str,
    input_text: str | None = None,
) -> tuple[str, str]:
    from app import input_repository as input_repo
    from app import participant_repository as pt_repo

    existing = pt_repo.get_participant_by_id(conn, participant_id)
    if existing is None:
        pt_repo.create_participant(
            conn,
            participant_id=participant_id,
            display_name=f"Benchmark {participant_id}",
            preferred_language="ko",
        )
    raw_text = input_text or ("benchmark synthetic input text " * 150)
    inp = input_repo.create_input(
        conn,
        participant_id=participant_id,
        raw_text=raw_text,
        consent_confirmed=1,
    )
    return participant_id, inp.id


def _collect_tokens(
    db_conn: sqlite3.Connection, *run_ids: str
) -> tuple[int | None, int | None]:
    from app import generation_run_repository as gr_repo

    total_input: int | None = None
    total_output: int | None = None
    for run_id in run_ids:
        if run_id:
            rec = gr_repo.get_generation_run_by_id(db_conn, run_id)
            if rec:
                if rec.input_tokens is not None:
                    total_input = (total_input or 0) + rec.input_tokens
                if rec.output_tokens is not None:
                    total_output = (total_output or 0) + rec.output_tokens
    return total_input, total_output


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _token_total(
    input_tokens: int | None, output_tokens: int | None
) -> int | None:
    if input_tokens is not None or output_tokens is not None:
        return (input_tokens or 0) + (output_tokens or 0)
    return None


def _sum_non_null_tokens(values: list[int | None]) -> int | None:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    return sum(non_null)


def _stage_provider_call_count(outcome) -> int:
    """Calculate actual HTTP calls from a stage outcome."""
    if outcome.validation_status == NOT_ATTEMPTED:
        return 0
    if outcome.run_id is None:
        return 0
    return outcome.retry_count + 1


GROUNDING_RULES = frozenset({
    "unknown_segment_reference",
    "missing_provenance",
    "duplicate_section_id",
    "section_not_in_plan",
    "section_references_no_segments",
})


def _is_grounding_failure(error_message: str | None) -> bool:
    if not error_message:
        return False
    lowered = error_message.lower()
    return any(term in lowered for term in [
        "unknown segment", "prohibited", "invented", "personal fact",
        "grounding", "not grounded",
    ])


def _apply_human_correction(
    conn: sqlite3.Connection, benchmark_name: str, minutes: float
) -> None:
    conn.execute(
        "UPDATE benchmark_runs SET human_correction_minutes = ? "
        "WHERE benchmark_name = ?",
        (minutes, benchmark_name),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Task runners
# ---------------------------------------------------------------------------


def _run_editorial_plan(
    *,
    provider: Any,
    fixture: FixtureBundle,
    db_conn: sqlite3.Connection,
    participant_id: str,
    input_id: str,
    run_index: int,
    benchmark_name: str,
) -> dict[str, Any]:
    from app.domain.models import EditorialPlan, ParticipantPreferences
    from app.pipeline import validators as val_mod
    from app.pipeline.prompts import (
        build_plan_system_prompt,
        build_plan_user_payload,
    )

    info = _provider_info(provider)
    started_at = _now_iso()
    task_start = time.monotonic()

    language = fixture.language
    segments = segment_text(fixture.input_text)
    preferences = ParticipantPreferences()

    plan_system = build_plan_system_prompt(language)
    plan_payload = build_plan_user_payload(
        participant_id=participant_id,
        segments=segments,
        preferences=preferences,
        language=language,
        is_follow_up=False,
        feedback_id=None,
        feedback_directions=[],
        feedback_free_text=None,
        prior_edition_summary=None,
        prohibited_inferences=list(fixture.prohibited_inventions),
    )

    plan, plan_outcome = _provider_call_with_retry(
        provider=provider,
        task_name="editorial_plan",
        system_prompt=plan_system,
        user_payload=plan_payload,
        response_schema=EditorialPlan,
        max_retries=2,
        prompt_version=PLAN_PROMPT_VERSION,
        conn=db_conn,
        participant_id=participant_id,
    )

    task_latency = time.monotonic() - task_start

    if plan is not None:
        try:
            val_mod.validate_plan(
                plan, segments=segments, is_follow_up=False
            )
            plan_valid = True
            combined_validation = VALIDATION_PASSED
        except Exception:
            plan_valid = False
            combined_validation = VALIDATION_FAILED
    else:
        plan_valid = False
        combined_validation = plan_outcome.validation_status or PROVIDER_FAILED

    combined_success = plan_valid and plan_outcome.success
    failure_category, failure_detail = _classify_failure_detailed(
        combined_validation, plan_outcome.error_category
    )

    input_tokens, output_tokens = _collect_tokens(db_conn, plan_outcome.run_id)
    completed_at = _now_iso()

    validation_result = "passed" if combined_success else "failed"
    ref_tag = "ok" if combined_success else "fail"
    synthetic_result_ref = f"bench-{fixture.name}-{run_index}-{ref_tag}"

    gen_refs = [r for r in [plan_outcome.run_id] if r]

    case_id = f"{benchmark_name}:{fixture.name}:editorial_plan:{run_index}"

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="editorial_plan",
        run_index=run_index,
        provider_info=info,
        task_type="editorial_plan",
        prompt_version=PLAN_PROMPT_VERSION,
        started_at=started_at,
        completed_at=completed_at,
        latency_seconds=task_latency,
        success=combined_success,
        failure_category=failure_category,
        error_category=plan_outcome.error_category,
        error_message=plan_outcome.error_message,
        retry_count=plan_outcome.retry_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_token_total(input_tokens, output_tokens),
        validation_result=validation_result,
        synthetic_result_ref=synthetic_result_ref,
        failure_detail=failure_detail,
        failure_stage="plan" if not combined_success else None,
        generation_run_refs=gen_refs,
        provider_call_count=_stage_provider_call_count(plan_outcome),
        case_id=case_id,
        phase_name="editorial_plan",
    )

    return {
        "fixture": fixture.name,
        "run_index": run_index,
        "run_group": "editorial_plan",
        "success": combined_success,
        "failure_category": failure_category,
        "failure_detail": failure_detail,
        "failure_stage": "plan" if not combined_success else None,
        "latency_seconds": task_latency,
        "retry_count": plan_outcome.retry_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": _token_total(input_tokens, output_tokens),
        "provider_call_count": _stage_provider_call_count(plan_outcome),
        "generation_run_refs": gen_refs,
        "validation_result": validation_result,
        "synthetic_result_ref": synthetic_result_ref,
        "case_id": case_id,
        "phase_name": "editorial_plan",
    }


def _run_first_edition(
    *,
    provider: Any,
    fixture: FixtureBundle,
    db_conn: sqlite3.Connection,
    participant_id: str,
    input_id: str,
    run_index: int,
    benchmark_name: str,
) -> dict[str, Any]:
    info = _provider_info(provider)
    started_at = _now_iso()
    task_start = time.monotonic()

    service = GenerationService(provider=provider)
    request = GenerationRequest(
        participant_id=participant_id,
        input_id=input_id,
        prohibited_inferences=fixture.prohibited_inventions,
        allow_short_sample=True,
    )
    result = service.generate_edition(db_conn, request=request)

    task_latency = time.monotonic() - task_start

    plan_ok = result.plan_run.success
    draft_ok = result.draft_run.success
    plan_attempted = result.plan_run.validation_status != NOT_ATTEMPTED
    draft_attempted = result.draft_run.validation_status != NOT_ATTEMPTED
    combined_success = plan_ok and draft_ok

    if combined_success:
        combined_validation = VALIDATION_PASSED
    elif result.draft_run.validation_status == VALIDATION_FAILED:
        combined_validation = VALIDATION_FAILED
    else:
        combined_validation = (
            result.plan_run.validation_status or PROVIDER_FAILED
        )

    total_retry = result.plan_run.retry_count + result.draft_run.retry_count
    input_tokens, output_tokens = _collect_tokens(
        db_conn, result.plan_run.run_id, result.draft_run.run_id
    )

    last_error_category: str | None = None
    last_error_message: str | None = None
    failure_stage: str | None = None
    if not combined_success:
        if not plan_ok and plan_attempted:
            failure_stage = "plan"
            last_error_category = result.plan_run.error_category
            last_error_message = result.plan_run.error_message
        elif not draft_ok and draft_attempted:
            failure_stage = "draft"
            last_error_category = result.draft_run.error_category
            last_error_message = result.draft_run.error_message

    completed_at = _now_iso()

    if combined_success:
        failure_category = None
        failure_detail = None
        validation_result = "passed"
        ref_tag = "ok"
    else:
        failure_category, failure_detail = _classify_failure_detailed(
            combined_validation, last_error_category
        )
        validation_result = "failed"
        ref_tag = "fail"

    synthetic_result_ref = f"bench-{fixture.name}-{run_index}-{ref_tag}"

    gen_refs = [r for r in [result.plan_run.run_id, result.draft_run.run_id] if r]

    case_id = f"{benchmark_name}:{fixture.name}:first_edition:{run_index}"

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="first_edition",
        run_index=run_index,
        provider_info=info,
        task_type="full_pipeline",
        prompt_version=f"{PLAN_PROMPT_VERSION}+{DRAFT_PROMPT_VERSION}",
        started_at=started_at,
        completed_at=completed_at,
        latency_seconds=task_latency,
        success=combined_success,
        failure_category=failure_category,
        error_category=last_error_category,
        error_message=last_error_message,
        retry_count=total_retry,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_token_total(input_tokens, output_tokens),
        validation_result=validation_result,
        synthetic_result_ref=synthetic_result_ref,
        failure_detail=failure_detail,
        failure_stage=failure_stage,
        generation_run_refs=gen_refs,
        provider_call_count=(
            _stage_provider_call_count(result.plan_run)
            + _stage_provider_call_count(result.draft_run)
        ),
        case_id=case_id,
        phase_name="first_edition",
    )

    return {
        "fixture": fixture.name,
        "run_index": run_index,
        "run_group": "first_edition",
        "success": combined_success,
        "failure_category": failure_category,
        "failure_detail": failure_detail,
        "failure_stage": failure_stage,
        "latency_seconds": task_latency,
        "retry_count": total_retry,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": _token_total(input_tokens, output_tokens),
        "plan_attempted": plan_attempted,
        "draft_attempted": draft_attempted,
        "provider_call_count": (
            _stage_provider_call_count(result.plan_run)
            + _stage_provider_call_count(result.draft_run)
        ),
        "generation_run_refs": gen_refs,
        "validation_result": validation_result,
        "synthetic_result_ref": synthetic_result_ref,
        "case_id": case_id,
        "phase_name": "first_edition",
        "upstream_failure_stage": failure_stage,
        "upstream_failure_detail": failure_detail,
    }


def _run_feedback_second_edition(
    *,
    settings: Settings,
    fixture: FixtureBundle,
    db_conn: sqlite3.Connection,
    participant_id: str,
    input_id: str,
    run_index: int,
    benchmark_name: str,
) -> dict[str, Any]:
    from app import edition_repository as ed_repo
    from app import feedback_repository as fb_repo

    provider = _build_provider(settings, fixture=fixture)
    first_info = _provider_info(provider)
    service = GenerationService(provider=provider)
    request = GenerationRequest(
        participant_id=participant_id,
        input_id=input_id,
        prohibited_inferences=fixture.prohibited_inventions,
        allow_short_sample=True,
    )

    task_started_at = _now_iso()
    task_start = time.monotonic()

    first_result = service.generate_edition(db_conn, request=request)

    if not first_result.succeeded or first_result.edition_id is None:
        completed_at = _now_iso()
        task_latency = time.monotonic() - task_start

        first_input_tokens, first_output_tokens = _collect_tokens(
            db_conn,
            first_result.plan_run.run_id,
            first_result.draft_run.run_id,
        )
        first_retry = (
            first_result.plan_run.retry_count
            + first_result.draft_run.retry_count
        )

        first_error_category = (
            first_result.draft_run.error_category
            or first_result.plan_run.error_category
        )
        first_error_message = (
            first_result.draft_run.error_message
            or first_result.plan_run.error_message
        )

        gen_refs = [
            r for r in [
                first_result.plan_run.run_id,
                first_result.draft_run.run_id,
            ] if r
        ]

        upstream_failure_stage = None
        upstream_failure_detail = None
        if not first_result.plan_run.success and first_result.plan_run.validation_status != NOT_ATTEMPTED:
            upstream_failure_stage = "plan"
            _, upstream_failure_detail = _classify_failure_detailed(
                first_result.plan_run.validation_status,
                first_result.plan_run.error_category,
            )
        elif not first_result.draft_run.success and first_result.draft_run.validation_status != NOT_ATTEMPTED:
            upstream_failure_stage = "draft"
            _, upstream_failure_detail = _classify_failure_detailed(
                first_result.draft_run.validation_status,
                first_result.draft_run.error_category,
            )

        case_id = f"{benchmark_name}:{fixture.name}:feedback_second_edition:{run_index}"

        _record_benchmark_run(
            db_conn,
            benchmark_name=benchmark_name,
            fixture_name=fixture.name,
            run_group="feedback_second_edition",
            run_index=run_index,
            provider_info=first_info,
            task_type="full_pipeline",
            prompt_version=f"{PLAN_PROMPT_VERSION}+{DRAFT_PROMPT_VERSION}",
            started_at=task_started_at,
            completed_at=completed_at,
            latency_seconds=task_latency,
            success=False,
            failure_category="pipeline_prevented",
            error_category=first_error_category,
            error_message="first edition failed during feedback setup",
            retry_count=first_retry,
            input_tokens=first_input_tokens,
            output_tokens=first_output_tokens,
            total_tokens=_token_total(first_input_tokens, first_output_tokens),
            validation_result="failed",
            synthetic_result_ref=f"bench-{fixture.name}-{run_index}-setup-fail",
            failure_detail="first_edition_setup_failed",
            failure_stage="plan" if not first_result.plan_run.success else "draft",
            generation_run_refs=gen_refs,
            provider_call_count=(
                _stage_provider_call_count(first_result.plan_run)
                + _stage_provider_call_count(first_result.draft_run)
            ),
            case_id=case_id,
            phase_name="feedback_second_edition",
            upstream_failure_detail=upstream_failure_detail,
            upstream_failure_stage=upstream_failure_stage,
        )
        return {
            "fixture": fixture.name,
            "run_index": run_index,
            "run_group": "feedback_second_edition",
            "success": False,
            "failure_category": "pipeline_prevented",
            "failure_detail": "first_edition_setup_failed",
            "failure_stage": "plan" if not first_result.plan_run.success else "draft",
            "latency_seconds": task_latency,
            "retry_count": first_retry,
            "input_tokens": first_input_tokens,
            "output_tokens": first_output_tokens,
            "total_tokens": _token_total(first_input_tokens, first_output_tokens),
            "plan_attempted": first_result.plan_run.validation_status != NOT_ATTEMPTED,
            "draft_attempted": first_result.draft_run.validation_status != NOT_ATTEMPTED,
            "provider_call_count": (
                _stage_provider_call_count(first_result.plan_run)
                + _stage_provider_call_count(first_result.draft_run)
            ),
            "generation_run_refs": gen_refs,
            "validation_result": "failed",
            "synthetic_result_ref": f"bench-{fixture.name}-{run_index}-setup-fail",
            "case_id": case_id,
            "phase_name": "feedback_second_edition",
            "upstream_failure_detail": upstream_failure_detail,
            "upstream_failure_stage": upstream_failure_stage,
        }

    ed_repo.update_edition_publication(
        db_conn, first_result.edition_id, "published"
    )

    direction_choices = json.dumps(list(fixture.feedback_directions))
    fb_record = fb_repo.create_feedback(
        db_conn,
        participant_id=participant_id,
        edition_id=first_result.edition_id,
        direction_choices=direction_choices,
        free_text=fixture.feedback_free_text,
    )
    feedback_id = fb_record.id

    follow_up_service = GenerationService(provider=provider)
    follow_up_request = GenerationRequest(
        participant_id=participant_id,
        input_id=input_id,
        is_follow_up=True,
        prior_edition_id=first_result.edition_id,
        feedback_id=feedback_id,
        prohibited_inferences=fixture.prohibited_inventions,
        allow_short_sample=True,
    )
    follow_up_result = follow_up_service.generate_edition(
        db_conn, request=follow_up_request
    )

    task_latency = time.monotonic() - task_start
    combined_success = follow_up_result.succeeded

    if combined_success:
        combined_validation = VALIDATION_PASSED
        failure_category = None
        failure_detail = None
        failure_stage = None
        last_error_category = None
        last_error_message = None
    else:
        if follow_up_result.draft_run.validation_status == VALIDATION_FAILED:
            combined_validation = VALIDATION_FAILED
        else:
            combined_validation = (
                follow_up_result.plan_run.validation_status or PROVIDER_FAILED
            )
        last_error_category = (
            follow_up_result.draft_run.error_category
            or follow_up_result.plan_run.error_category
        )
        last_error_message = (
            follow_up_result.draft_run.error_message
            or follow_up_result.plan_run.error_message
        )
        failure_category, failure_detail = _classify_failure_detailed(
            combined_validation, last_error_category
        )
        if not follow_up_result.plan_run.success:
            failure_stage = "plan"
        elif not follow_up_result.draft_run.success:
            failure_stage = "draft"
        else:
            failure_stage = None

    total_retry = (
        first_result.plan_run.retry_count
        + first_result.draft_run.retry_count
        + follow_up_result.plan_run.retry_count
        + follow_up_result.draft_run.retry_count
    )

    all_gen_run_ids = (
        first_result.plan_run.run_id,
        first_result.draft_run.run_id,
        follow_up_result.plan_run.run_id,
        follow_up_result.draft_run.run_id,
    )
    input_tokens, output_tokens = _collect_tokens(db_conn, *all_gen_run_ids)

    completed_at = _now_iso()
    validation_result = "passed" if combined_success else "failed"
    ref_tag = "ok" if combined_success else "fail"
    synthetic_result_ref = f"bench-{fixture.name}-{run_index}-{ref_tag}"

    first_gen_refs = [
        r for r in [
            first_result.plan_run.run_id,
            first_result.draft_run.run_id,
        ] if r
    ]
    follow_gen_refs = [
        r for r in [
            follow_up_result.plan_run.run_id,
            follow_up_result.draft_run.run_id,
        ] if r
    ]
    all_gen_refs = first_gen_refs + follow_gen_refs

    total_provider_calls = (
        _stage_provider_call_count(first_result.plan_run)
        + _stage_provider_call_count(first_result.draft_run)
        + _stage_provider_call_count(follow_up_result.plan_run)
        + _stage_provider_call_count(follow_up_result.draft_run)
    )

    case_id = f"{benchmark_name}:{fixture.name}:feedback_second_edition:{run_index}"

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="feedback_second_edition",
        run_index=run_index,
        provider_info=first_info,
        task_type="full_pipeline",
        prompt_version=f"{PLAN_PROMPT_VERSION}+{DRAFT_PROMPT_VERSION}",
        started_at=task_started_at,
        completed_at=completed_at,
        latency_seconds=task_latency,
        success=combined_success,
        failure_category=failure_category,
        error_category=last_error_category,
        error_message=last_error_message,
        retry_count=total_retry,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_token_total(input_tokens, output_tokens),
        validation_result=validation_result,
        synthetic_result_ref=synthetic_result_ref,
        failure_detail=failure_detail,
        failure_stage=failure_stage,
        generation_run_refs=all_gen_refs,
        provider_call_count=total_provider_calls,
        case_id=case_id,
        phase_name="feedback_second_edition",
    )

    return {
        "fixture": fixture.name,
        "run_index": run_index,
        "run_group": "feedback_second_edition",
        "success": combined_success,
        "failure_category": failure_category,
        "failure_detail": failure_detail,
        "failure_stage": failure_stage,
        "latency_seconds": task_latency,
        "retry_count": total_retry,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": _token_total(input_tokens, output_tokens),
        "plan_attempted": follow_up_result.plan_run.validation_status != NOT_ATTEMPTED,
        "draft_attempted": follow_up_result.draft_run.validation_status != NOT_ATTEMPTED,
        "provider_call_count": total_provider_calls,
        "generation_run_refs": all_gen_refs,
        "validation_result": validation_result,
        "synthetic_result_ref": synthetic_result_ref,
        "case_id": case_id,
        "phase_name": "feedback_second_edition",
        "upstream_failure_stage": None,
        "upstream_failure_detail": None,
    }


def _run_adversarial_grounding(
    *,
    provider: Any,
    fixture: FixtureBundle,
    db_conn: sqlite3.Connection,
    participant_id: str,
    input_id: str,
    run_index: int,
    benchmark_name: str,
) -> dict[str, Any]:
    info = _provider_info(provider)
    started_at = _now_iso()
    task_start = time.monotonic()

    service = GenerationService(provider=provider)
    request = GenerationRequest(
        participant_id=participant_id,
        input_id=input_id,
        prohibited_inferences=fixture.prohibited_inventions,
        allow_short_sample=True,
    )
    result = service.generate_edition(db_conn, request=request)

    task_latency = time.monotonic() - task_start
    combined_success = result.succeeded

    plan_attempted = result.plan_run.validation_status != NOT_ATTEMPTED
    draft_attempted = result.draft_run.validation_status != NOT_ATTEMPTED

    if combined_success:
        combined_validation = VALIDATION_PASSED
    elif result.draft_run.validation_status == VALIDATION_FAILED:
        combined_validation = VALIDATION_FAILED
    else:
        combined_validation = (
            result.plan_run.validation_status or PROVIDER_FAILED
        )

    total_retry = result.plan_run.retry_count + result.draft_run.retry_count
    input_tokens, output_tokens = _collect_tokens(
        db_conn, result.plan_run.run_id, result.draft_run.run_id
    )

    last_error_category: str | None = None
    last_error_message: str | None = None
    failure_stage: str | None = None
    if not combined_success:
        if not result.plan_run.success and plan_attempted:
            failure_stage = "plan"
            last_error_category = result.plan_run.error_category
            last_error_message = result.plan_run.error_message
        elif not result.draft_run.success and draft_attempted:
            failure_stage = "draft"
            last_error_category = result.draft_run.error_category
            last_error_message = result.draft_run.error_message

    completed_at = _now_iso()
    failure_category, failure_detail = _classify_failure_detailed(
        combined_validation, last_error_category
    )

    if (
        not combined_success
        and combined_validation == VALIDATION_FAILED
        and result.plan_run.success
        and not result.draft_run.success
        and _is_grounding_failure(last_error_message)
    ):
        failure_detail = "grounding_failure"

    validation_result = "passed" if combined_success else "failed"
    ref_tag = "ok" if combined_success else "adversarial-caught"
    synthetic_result_ref = f"bench-{fixture.name}-{run_index}-{ref_tag}"

    gen_refs = [r for r in [result.plan_run.run_id, result.draft_run.run_id] if r]

    case_id = f"{benchmark_name}:{fixture.name}:adversarial_grounding:{run_index}"

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="adversarial_grounding",
        run_index=run_index,
        provider_info=info,
        task_type="full_pipeline",
        prompt_version=f"{PLAN_PROMPT_VERSION}+{DRAFT_PROMPT_VERSION}",
        started_at=started_at,
        completed_at=completed_at,
        latency_seconds=task_latency,
        success=combined_success,
        failure_category=failure_category,
        error_category=last_error_category,
        error_message=last_error_message,
        retry_count=total_retry,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_token_total(input_tokens, output_tokens),
        validation_result=validation_result,
        synthetic_result_ref=synthetic_result_ref,
        failure_detail=failure_detail,
        failure_stage=failure_stage,
        generation_run_refs=gen_refs,
        provider_call_count=(
            _stage_provider_call_count(result.plan_run)
            + _stage_provider_call_count(result.draft_run)
        ),
        case_id=case_id,
        phase_name="adversarial_grounding",
    )

    return {
        "fixture": fixture.name,
        "run_index": run_index,
        "run_group": "adversarial_grounding",
        "success": combined_success,
        "failure_category": failure_category,
        "failure_detail": failure_detail,
        "failure_stage": failure_stage,
        "latency_seconds": task_latency,
        "retry_count": total_retry,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": _token_total(input_tokens, output_tokens),
        "plan_attempted": plan_attempted,
        "draft_attempted": draft_attempted,
        "provider_call_count": (
            _stage_provider_call_count(result.plan_run)
            + _stage_provider_call_count(result.draft_run)
        ),
        "generation_run_refs": gen_refs,
        "validation_result": validation_result,
        "synthetic_result_ref": synthetic_result_ref,
        "case_id": case_id,
        "phase_name": "adversarial_grounding",
        "upstream_failure_stage": failure_stage,
        "upstream_failure_detail": failure_detail,
    }


_REPAIR_INVALID_SEGMENT_ID = "s999"
_REPAIR_INSTRUCTION = (
    "Repair the corrupted candidate so it passes deterministic validation. "
    "Restore every section's source_segment_ids to valid segment identifiers, "
    "keep the same plan section ids, and preserve intent and privacy."
)


def _build_repair_provider(settings: Settings, fixture: FixtureBundle):
    """Build the single provider instance used for both repair phases.

    For MockProvider the candidate (plan + draft) and the scripted repair
    response are supplied as ordered scripted responses so the same instance
    serves both the candidate generation and the repair call. For an external
    provider the same configured provider/model is reused; no live call happens
    in tests.
    """
    if settings.ai_provider == "mock":
        model = settings.ai_model
        return MockProvider(
            model=model,
            responses=[
                {
                    "task": TASK_EDITORIAL_PLAN,
                    "kind": "payload",
                    "payload": fixture.plan_payload,
                },
                {
                    "task": TASK_EDITION_DRAFT,
                    "kind": "payload",
                    "payload": fixture.draft_payload,
                },
                {
                    "task": TASK_EDITION_REPAIR,
                    "kind": "payload",
                    "payload": fixture.draft_payload,
                },
            ],
        )
    if settings.ai_provider == "external" and settings.ai_base_url:
        from app.ai.external import ExternalProvider
        from app.domain.enums import CostClass

        cost_class = CostClass(settings.ai_cost_class)
        return ExternalProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            cost_class=cost_class,
            response_format_mode=settings.ai_response_format_mode,
        )
    raise SystemExit(
        "provider config fail-closed: AI_PROVIDER must be 'mock' "
        "or AI_BASE_URL must be set for an external provider"
    )


def _run_validator_feedback_repair(
    *,
    settings: Settings,
    fixture: FixtureBundle,
    db_conn: sqlite3.Connection,
    participant_id: str,
    input_id: str,
    run_index: int,
    benchmark_name: str,
) -> list[dict[str, Any]]:
    """Validator-feedback repair benchmark.

    Proves the model receives validator feedback and repairs its own invalid
    candidate (CTO review 5027501906). The harness never asks the provider to
    misbehave: the invalid candidate is produced by deterministic corruption.
    """
    results: list[dict[str, Any]] = []

    provider = _build_repair_provider(settings, fixture)
    provider_info = _provider_info(provider)

    # Phases 1-2: one candidate via the configured provider; preserve accounting.
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        db_conn,
        request=GenerationRequest(
            participant_id=participant_id,
            input_id=input_id,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )

    cand_in, cand_out = _collect_tokens(
        db_conn, candidate.plan_outcome.run_id, candidate.draft_outcome.run_id
    )
    cand_latency = (candidate.plan_outcome.latency_seconds or 0) + (
        candidate.draft_outcome.latency_seconds or 0
    )
    cand_retry = (candidate.plan_outcome.retry_count or 0) + (
        candidate.draft_outcome.retry_count or 0
    )

    if not candidate.succeeded or candidate.content is None or candidate.plan is None:
        cand_error_category = (
            candidate.draft_outcome.error_category
            or candidate.plan_outcome.error_category
        )
        cand_error_validation = (
            candidate.draft_outcome.validation_status
            or candidate.plan_outcome.validation_status
        )
        cand_failure_category, cand_failure_detail = _classify_failure_detailed(
            cand_error_validation, cand_error_category
        )
        cand_gen_refs = [
            r for r in [
                candidate.plan_outcome.run_id,
                candidate.draft_outcome.run_id,
            ] if r
        ]
        case_id = f"{benchmark_name}:{fixture.name}:validator_feedback_repair:{run_index}"
        _record_benchmark_run(
            db_conn,
            benchmark_name=benchmark_name,
            fixture_name=fixture.name,
            run_group="validator_feedback_repair",
            run_index=run_index * 3,
            provider_info=provider_info,
            task_type="repair_candidate_generation",
            prompt_version=f"{PLAN_PROMPT_VERSION}+{DRAFT_PROMPT_VERSION}",
            started_at=_now_iso(),
            completed_at=_now_iso(),
            latency_seconds=cand_latency,
            success=False,
            failure_category=cand_failure_category,
            error_category=cand_error_category,
            error_message="candidate generation failed",
            retry_count=cand_retry,
            input_tokens=cand_in,
            output_tokens=cand_out,
            total_tokens=_token_total(cand_in, cand_out),
            validation_result="failed",
            synthetic_result_ref=f"bench-{fixture.name}-{run_index}-candidate-fail",
            failure_detail=cand_failure_detail,
            failure_stage="plan" if not candidate.plan_outcome.success else "draft",
            generation_run_refs=cand_gen_refs,
            provider_call_count=(
                _stage_provider_call_count(candidate.plan_outcome)
                + _stage_provider_call_count(candidate.draft_outcome)
            ),
            case_id=case_id,
            phase_name="repair_candidate_generation",
        )
        return [
            {
                "fixture": fixture.name,
                "run_index": run_index,
                "phase": "repair_candidate_generation",
                "success": False,
                "validation_result": "failed",
                "failure_category": cand_failure_category,
                "failure_detail": cand_failure_detail,
                "generation_run_refs": cand_gen_refs,
                "provider_call_count": (
                    _stage_provider_call_count(candidate.plan_outcome)
                    + _stage_provider_call_count(candidate.draft_outcome)
                ),
                "repair_attempted": False,
                "case_id": case_id,
                "phase_name": "repair_candidate_generation",
                "upstream_failure_stage": "plan" if not candidate.plan_outcome.success else "draft",
                "upstream_failure_detail": cand_failure_detail,
            }
        ]

    cand_gen_refs = [
        r for r in [
            candidate.plan_outcome.run_id,
            candidate.draft_outcome.run_id,
        ] if r
    ]

    case_id = f"{benchmark_name}:{fixture.name}:validator_feedback_repair:{run_index}"

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="validator_feedback_repair",
        run_index=run_index * 3,
        provider_info=provider_info,
        task_type="repair_candidate_generation",
        prompt_version=f"{PLAN_PROMPT_VERSION}+{DRAFT_PROMPT_VERSION}",
        started_at=_now_iso(),
        completed_at=_now_iso(),
        latency_seconds=cand_latency,
        success=True,
        failure_category=None,
        error_category=None,
        error_message=None,
        retry_count=cand_retry,
        input_tokens=cand_in,
        output_tokens=cand_out,
        total_tokens=_token_total(cand_in, cand_out),
        validation_result="passed",
        synthetic_result_ref=f"bench-{fixture.name}-{run_index}-candidate",
        failure_detail=None,
        failure_stage=None,
        generation_run_refs=cand_gen_refs,
        provider_call_count=(
            _stage_provider_call_count(candidate.plan_outcome)
            + _stage_provider_call_count(candidate.draft_outcome)
        ),
        case_id=case_id,
        phase_name="repair_candidate_generation",
    )
    results.append(
        {
            "fixture": fixture.name,
            "run_index": run_index,
            "phase": "repair_candidate_generation",
            "success": True,
            "validation_result": "passed",
            "latency_seconds": cand_latency,
            "retry_count": cand_retry,
            "input_tokens": cand_in,
            "output_tokens": cand_out,
            "total_tokens": _token_total(cand_in, cand_out),
            "candidate_plan_run_id": candidate.plan_outcome.run_id,
            "candidate_draft_run_id": candidate.draft_outcome.run_id,
            "generation_run_refs": cand_gen_refs,
            "provider_call_count": (
                _stage_provider_call_count(candidate.plan_outcome)
                + _stage_provider_call_count(candidate.draft_outcome)
            ),
            "case_id": case_id,
            "phase_name": "repair_candidate_generation",
            "upstream_failure_stage": None,
            "upstream_failure_detail": None,
        }
    )

    # Phase 3: deterministic harness corruption (invalid synthetic segment id).
    corrupted_dict = candidate.content.model_dump()
    if corrupted_dict.get("sections"):
        corrupted_dict["sections"][0]["source_segment_ids"] = [
            _REPAIR_INVALID_SEGMENT_ID
        ]
    corrupted = EditionContent.model_validate(corrupted_dict)

    # Phases 4-5: run the accepted deterministic validator; require failure.
    bad_validation_failed = False
    bad_error: Exception | None = None
    try:
        validators_mod.validate_draft(
            corrupted,
            plan=candidate.plan,
            segments=candidate.segments,
            is_follow_up=False,
            feedback_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - any deterministic rejection counts
        bad_validation_failed = True
        bad_error = exc

    assert bad_validation_failed, (
        "validator-feedback repair: the deterministically corrupted candidate "
        "unexpectedly passed validation; the benchmark cannot demonstrate repair"
    )

    validator_findings = (
        normalize_validation_findings(bad_error)
        if bad_error is not None
        else []
    )

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="validator_feedback_repair",
        run_index=run_index * 3 + 1,
        provider_info=provider_info,
        task_type="repair_bad_validation",
        prompt_version=PLAN_PROMPT_VERSION,
        started_at=_now_iso(),
        completed_at=_now_iso(),
        latency_seconds=0.0,
        success=False,
        failure_category="model_quality",
        error_category=ProviderErrorCategory.SCHEMA_MISMATCH.value,
        error_message="deterministic validator rejected corrupted candidate",
        retry_count=0,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        validation_result="failed",
        synthetic_result_ref=f"bench-{fixture.name}-{run_index}-bad",
        failure_detail="deterministic_validation",
        failure_stage="draft",
        generation_run_refs=[],
        provider_call_count=0,
        case_id=case_id,
        phase_name="repair_bad_validation",
    )
    results.append(
        {
            "fixture": fixture.name,
            "run_index": run_index,
            "phase": "repair_bad_validation",
            "success": False,
            "validation_result": "failed",
            "validator_findings": validator_findings,
            "generation_run_refs": [],
            "provider_call_count": 0,
            "case_id": case_id,
            "phase_name": "repair_bad_validation",
            "upstream_failure_stage": None,
            "upstream_failure_detail": None,
        }
    )

    # Phases 6-7: privacy-safe repair request to the SAME provider instance.
    correlation_id = f"bench-{fixture.name}-{run_index}-corr"
    attempt_id = f"bench-{fixture.name}-{run_index}-attempt-1"
    # Authoritative, privacy-safe reference universe: IDs only, no segment text.
    allowed_segment_ids = tuple(
        sorted(seg.segment_id for seg in candidate.segments)
    )
    allowed_plan_section_ids = tuple(
        sorted(s.section_id for s in candidate.plan.sections)
    )

    repair_request = RepairRequest(
        participant_id=participant_id,
        input_id=input_id,
        corrupted_candidate=corrupted.model_dump(),
        validator_findings=validator_findings,
        repair_instruction=_REPAIR_INSTRUCTION,
        correlation_id=correlation_id,
        attempt_id=attempt_id,
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=allowed_segment_ids,
        allowed_plan_section_ids=allowed_plan_section_ids,
    )

    repair_outcome = service.repair_edition(
        db_conn,
        repair_request=repair_request,
        plan=candidate.plan,
        segments=candidate.segments,
    )

    repair_success = repair_outcome.succeeded
    repair_in, repair_out = _collect_tokens(db_conn, repair_outcome.run_id)
    repair_ref = f"bench-{fixture.name}-{run_index}-repair"

    repair_gen_refs = [r for r in [repair_outcome.run_id] if r]

    repair_category, repair_detail = _classify_failure_detailed(
        repair_outcome.validation_status,
        repair_outcome.error_category,
    ) if not repair_success else (None, None)

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
        run_group="validator_feedback_repair",
        run_index=run_index * 3 + 2,
        provider_info=provider_info,
        task_type="repair_provider",
        prompt_version=f"{DRAFT_PROMPT_VERSION}+{REPAIR_PROMPT_VERSION}",
        started_at=_now_iso(),
        completed_at=_now_iso(),
        latency_seconds=repair_outcome.latency_seconds or 0.0,
        success=repair_success,
        failure_category=repair_category,
        error_category=repair_outcome.error_category,
        error_message=repair_outcome.error_message,
        retry_count=repair_outcome.retry_count,
        input_tokens=repair_in,
        output_tokens=repair_out,
        total_tokens=_token_total(repair_in, repair_out),
        validation_result="passed" if repair_success else "failed",
        synthetic_result_ref=repair_ref,
        failure_detail=repair_detail,
        failure_stage="repair" if not repair_success else None,
        generation_run_refs=repair_gen_refs,
        provider_call_count=_stage_provider_call_count(repair_outcome),
        case_id=case_id,
        phase_name="repair_provider",
    )
    results.append(
        {
            "fixture": fixture.name,
            "run_index": run_index,
            "phase": "repair_provider",
            "success": repair_success,
            "validation_result": VALIDATION_PASSED
            if repair_success
            else VALIDATION_FAILED,
            "latency_seconds": repair_outcome.latency_seconds,
            "retry_count": repair_outcome.retry_count,
            "input_tokens": repair_in,
            "output_tokens": repair_out,
            "total_tokens": _token_total(repair_in, repair_out),
            "repair_run_id": repair_outcome.run_id,
            "correlation_id": correlation_id,
            "attempt_id": attempt_id,
            "generation_run_refs": repair_gen_refs,
            "provider_call_count": _stage_provider_call_count(repair_outcome),
            "repair_attempted": True,
            "failure_category": repair_category,
            "failure_detail": repair_detail,
            "failure_stage": "repair" if not repair_success else None,
            "case_id": case_id,
            "phase_name": "repair_provider",
            "upstream_failure_stage": None,
            "upstream_failure_detail": None,
        }
    )

    return results



def _dispatch_task(
    *,
    task: str,
    settings: Settings,
    fixture: FixtureBundle,
    db_conn: sqlite3.Connection,
    participant_id: str,
    input_id: str,
    run_index: int,
    benchmark_name: str,
) -> list[dict[str, Any]] | None:
    if task == "editorial_plan":
        provider = _build_provider(settings, fixture=fixture)
        return [
            _run_editorial_plan(
                provider=provider,
                fixture=fixture,
                db_conn=db_conn,
                participant_id=participant_id,
                input_id=input_id,
                run_index=run_index,
                benchmark_name=benchmark_name,
            )
        ]

    if task == "first_edition":
        provider = _build_provider(settings, fixture=fixture)
        return [
            _run_first_edition(
                provider=provider,
                fixture=fixture,
                db_conn=db_conn,
                participant_id=participant_id,
                input_id=input_id,
                run_index=run_index,
                benchmark_name=benchmark_name,
            )
        ]

    if task == "feedback_second_edition":
        if not fixture.follow_up_plan_payload or not fixture.follow_up_draft_payload:
            return None
        return [
            _run_feedback_second_edition(
                settings=settings,
                fixture=fixture,
                db_conn=db_conn,
                participant_id=participant_id,
                input_id=input_id,
                run_index=run_index,
                benchmark_name=benchmark_name,
            )
        ]

    if task == "adversarial_grounding":
        provider = _build_provider(settings, fixture=fixture)
        return [
            _run_adversarial_grounding(
                provider=provider,
                fixture=fixture,
                db_conn=db_conn,
                participant_id=participant_id,
                input_id=input_id,
                run_index=run_index,
                benchmark_name=benchmark_name,
            )
        ]

    if task == "validator_feedback_repair":
        if not fixture.plan_payload or not fixture.draft_payload:
            return None
        return _run_validator_feedback_repair(
            settings=settings,
            fixture=fixture,
            db_conn=db_conn,
            participant_id=participant_id,
            input_id=input_id,
            run_index=run_index,
            benchmark_name=benchmark_name,
        )

    raise ValueError(f"unknown task: {task}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_benchmark(
    *,
    task: str,
    fixture_names: list[str] | None = None,
    repeat: int = 1,
    output_path: str | None = None,
    db_path: str | None = None,
    human_correction_minutes: float | None = None,
) -> list[dict[str, Any]]:
    settings = Settings()

    resolved_db = db_path or "var/benchmark.db"
    conn = _setup_benchmark_db(resolved_db)

    if fixture_names is None:
        fixture_names = list_bundles()

    results: list[dict[str, Any]] = []
    benchmark_name = (
        f"benchmark-{task}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    )

    info: dict[str, str] | None = None
    for fname in fixture_names:
        fixture = load_bundle(fname)
        for i in range(repeat):
            participant_id = f"bench-{benchmark_name}-{fname}-repeat-{i}"
            pid, input_id = _ensure_participant(
                conn,
                participant_id=participant_id,
                input_text=fixture.input_text,
            )

            print(
                f"  [{fname}] task={task} run {i + 1}/{repeat} ... ",
                end="",
                flush=True,
            )

            run_results = _dispatch_task(
                task=task,
                settings=settings,
                fixture=fixture,
                db_conn=conn,
                participant_id=pid,
                input_id=input_id,
                run_index=i,
                benchmark_name=benchmark_name,
            )

            if run_results is None:
                print("SKIP")
                continue

            if info is None:
                dummy = _build_provider(settings, fixture=fixture)
                info = _provider_info(dummy)

            for res in run_results:
                results.append(res)
                status = (
                    "OK"
                    if res["success"]
                    else f"FAIL({res.get('failure_category', '?')})"
                )
                latency = res.get("latency_seconds", 0)
                retries = res.get("retry_count", 0)
                print(f"{status}  latency={latency:.3f}s  retries={retries}")

    if human_correction_minutes is not None:
        _apply_human_correction(conn, benchmark_name, human_correction_minutes)

    conn.close()

    if output_path and info is not None:
        aggregate = {
            "benchmark_case_count": len(set(r.get("case_id") for r in results if r.get("case_id"))),
            "phase_result_count": len(results),
            "provider_call_count": sum(r.get("provider_call_count", 0) for r in results),
            "provider_failure_count": sum(1 for r in results if r.get("failure_category") == "provider"),
            "model_quality_failure_count": sum(1 for r in results if r.get("failure_category") == "model_quality"),
            "pipeline_prevented_count": sum(1 for r in results if r.get("failure_category") == "pipeline_prevented"),
            "input_token_sum": _sum_non_null_tokens([r.get("input_tokens") for r in results]),
            "output_token_sum": _sum_non_null_tokens([r.get("output_tokens") for r in results]),
            "total_token_sum": _sum_non_null_tokens([r.get("total_tokens") for r in results]),
            "rows_with_token_usage": sum(1 for r in results if r.get("total_tokens") is not None),
            "rows_missing_token_usage": sum(1 for r in results if r.get("total_tokens") is None),
        }
        report = {
            "benchmark_name": benchmark_name,
            "task": task,
            "provider": info["provider"],
            "advertised_model": info["model"],
            "fixture_count": len(fixture_names),
            "repeat": repeat,
            "total_runs": len(results),
            "results": results,
            "aggregate": aggregate,
        }
        Path(output_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nBenchmark report written to {output_path}")

    return results


# ---------------------------------------------------------------------------
# update-correction subcommand
# ---------------------------------------------------------------------------


def update_correction(
    *,
    db_path: str,
    run_id: str,
    minutes: float,
) -> None:
    conn = get_connection(db_path)
    cursor = conn.execute(
        "UPDATE benchmark_runs SET human_correction_minutes = ? WHERE id = ?",
        (minutes, run_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        print(f"Error: no benchmark run found with id {run_id}")
        sys.exit(1)
    print(f"Updated run {run_id} with human_correction_minutes={minutes}")
    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Personal Edition runtime benchmark runner"
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a benchmark task")
    run_parser.add_argument(
        "task",
        choices=ALL_TASKS,
        help="Benchmark task type.",
    )
    run_parser.add_argument(
        "--fixture",
        action="append",
        dest="fixtures",
        help="Fixture name (repeatable). Default: all fixtures.",
    )
    run_parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat count per fixture (default: 1).",
    )
    run_parser.add_argument(
        "--output",
        help="Path to write the JSON benchmark report.",
    )
    run_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (default: var/benchmark.db).",
    )
    run_parser.add_argument(
        "--correct",
        type=float,
        default=None,
        metavar="MINUTES",
        help="Set human_correction_minutes for all runs after completion.",
    )

    uc_parser = subparsers.add_parser(
        "update-correction",
        help="Update human_correction_minutes for a run",
    )
    uc_parser.add_argument(
        "--run-id",
        required=True,
        help="Benchmark run ID to update.",
    )
    uc_parser.add_argument(
        "--minutes",
        type=float,
        required=True,
        help="Correction minutes value.",
    )
    uc_parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (default: var/benchmark.db).",
    )

    args = parser.parse_args()

    if args.command == "update-correction":
        update_correction(
            db_path=args.db or "var/benchmark.db",
            run_id=args.run_id,
            minutes=args.minutes,
        )
        return

    if args.command == "run":
        print("Personal Edition Runtime Benchmark")
        print("=" * 40)
        print(f"Task: {args.task}")
        results = run_benchmark(
            task=args.task,
            fixture_names=args.fixtures,
            repeat=args.repeat,
            output_path=args.output,
            db_path=args.db,
            human_correction_minutes=args.correct,
        )

        successes = sum(1 for r in results if r["success"])
        failures = sum(1 for r in results if not r["success"])
        provider_failures = sum(
            1 for r in results if r.get("failure_category") == "provider"
        )
        model_failures = sum(
            1 for r in results if r.get("failure_category") == "model_quality"
        )
        pipeline_failures = sum(
            1 for r in results
            if r.get("failure_category") == "pipeline_prevented"
        )

        detail_counts: dict[str, int] = {}
        for r in results:
            d = r.get("failure_detail")
            if d is not None:
                detail_counts[d] = detail_counts.get(d, 0) + 1

        unique_case_ids = set(r.get("case_id") for r in results if r.get("case_id"))
        total_provider_calls = sum(r.get("provider_call_count", 0) for r in results)

        print("\n" + "=" * 40)
        print(f"Total: {len(results)}  OK: {successes}  FAIL: {failures}")
        print(f"Cases: {len(unique_case_ids)}  Provider calls: {total_provider_calls}")
        print(
            f"Provider failures: {provider_failures}  "
            f"Model-quality failures: {model_failures}  "
            f"Pipeline-prevented: {pipeline_failures}"
        )
        if detail_counts:
            print("Failure details:")
            for detail, count in sorted(detail_counts.items()):
                print(f"  {detail}: {count}")
        if failures > 0:
            sys.exit(1)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
