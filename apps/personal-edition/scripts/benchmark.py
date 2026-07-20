#!/usr/bin/env python3
"""Synthetic runtime benchmark runner for Personal Edition.

Records provider/model identity, task and prompt version, success/failure
category, latency, retry count, token usage, deterministic validation
result, and synthetic result reference.  Never stores raw credentials,
token material, or full generated private output.

Usage:
    python -m scripts.benchmark [--fixture NAME] [--repeat N] [--output PATH]

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
from app.pipeline.errors import PROVIDER_FAILED, VALIDATION_FAILED, VALIDATION_PASSED
from app.pipeline.fixtures import FixtureBundle, inject_feedback_id, list_bundles, load_bundle
from app.pipeline.prompts import DRAFT_PROMPT_VERSION, PLAN_PROMPT_VERSION
from app.pipeline.service import GenerationRequest, GenerationService


def _build_provider(settings: Settings, fixture: FixtureBundle | None = None):
    if settings.ai_provider == "mock" or not settings.ai_base_url:
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
    from app.ai.external import ExternalProvider
    return ExternalProvider(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )


def _provider_info(provider: Any) -> dict[str, str]:
    return {
        "provider": getattr(provider, "provider", provider.__class__.__name__.lower()),
        "model": getattr(provider, "model", "unknown"),
    }


def _create_benchmark_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_runs (
            id TEXT PRIMARY KEY,
            benchmark_name TEXT NOT NULL,
            fixture_name TEXT NOT NULL,
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
            is_model_quality_failure INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()


def _record_benchmark_run(
    conn: sqlite3.Connection,
    *,
    benchmark_name: str,
    fixture_name: str,
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
) -> None:
    run_id = str(uuid.uuid4())
    is_provider = 1 if failure_category == "provider" else 0
    is_model = 1 if failure_category == "model_quality" else 0
    conn.execute(
        "INSERT INTO benchmark_runs "
        "(id, benchmark_name, fixture_name, run_index, provider, advertised_model, "
        "task_type, prompt_version, started_at, completed_at, latency_seconds, "
        "success, failure_category, error_category, error_message, retry_count, "
        "input_tokens, output_tokens, total_tokens, validation_result, "
        "synthetic_result_ref, human_correction_minutes, is_provider_failure, "
        "is_model_quality_failure) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
        (
            run_id, benchmark_name, fixture_name, run_index,
            provider_info["provider"], provider_info["model"],
            task_type, prompt_version, started_at, completed_at,
            latency_seconds, 1 if success else 0, failure_category,
            error_category, error_message, retry_count,
            input_tokens, output_tokens, total_tokens, validation_result,
            synthetic_result_ref, is_provider, is_model,
        ),
    )
    conn.commit()


def _classify_failure(
    result_validation_status: str | None,
    result_error_category: str | None,
) -> str | None:
    if result_validation_status == VALIDATION_PASSED:
        return None
    if result_error_category in (
        None,
        ProviderErrorCategory.SCHEMA_MISMATCH.value,
        ProviderErrorCategory.INVALID_JSON.value,
    ):
        return "model_quality"
    return "provider"


def _run_fixture_once(
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
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    task_start = time.monotonic()

    service = GenerationService(provider=provider)
    request = GenerationRequest(
        participant_id=participant_id,
        input_id=input_id,
        allow_short_sample=True,
    )
    result = service.generate_edition(db_conn, request=request)

    task_latency = time.monotonic() - task_start

    plan_success = result.plan_run.success
    draft_success = result.draft_run.success
    combined_success = plan_success and draft_success

    if combined_success:
        combined_validation = VALIDATION_PASSED
    elif result.draft_run.validation_status == VALIDATION_FAILED:
        combined_validation = VALIDATION_FAILED
    else:
        combined_validation = result.plan_run.validation_status or PROVIDER_FAILED

    total_retry = result.plan_run.retry_count + result.draft_run.retry_count

    total_input_tokens: int | None = None
    total_output_tokens: int | None = None

    for stage in (result.plan_run, result.draft_run):
        if stage.run_id:
            from app import generation_run_repository as gr_repo
            run_record = gr_repo.get_generation_run_by_id(db_conn, stage.run_id)
            if run_record:
                if run_record.input_tokens is not None:
                    total_input_tokens = (total_input_tokens or 0) + run_record.input_tokens
                if run_record.output_tokens is not None:
                    total_output_tokens = (total_output_tokens or 0) + run_record.output_tokens

    last_error_category: str | None = None
    last_error_message: str | None = None
    if not combined_success:
        if not draft_success:
            last_error_category = result.draft_run.error_category
            last_error_message = result.draft_run.error_message
        elif not plan_success:
            last_error_category = result.plan_run.error_category
            last_error_message = result.plan_run.error_message

    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    if combined_success:
        failure_category = None
        validation_result = "passed"
        synthetic_result_ref = f"bench-{fixture.name}-{run_index}-ok"
    else:
        failure_category = _classify_failure(combined_validation, last_error_category)
        validation_result = "failed"
        synthetic_result_ref = f"bench-{fixture.name}-{run_index}-fail"

    _record_benchmark_run(
        db_conn,
        benchmark_name=benchmark_name,
        fixture_name=fixture.name,
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
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        total_tokens=(
            (total_input_tokens or 0) + (total_output_tokens or 0)
            if total_input_tokens is not None or total_output_tokens is not None
            else None
        ),
        validation_result=validation_result,
        synthetic_result_ref=synthetic_result_ref,
    )

    return {
        "fixture": fixture.name,
        "run_index": run_index,
        "success": combined_success,
        "failure_category": failure_category,
        "latency_seconds": task_latency,
        "retry_count": total_retry,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "validation_result": validation_result,
        "synthetic_result_ref": synthetic_result_ref,
    }


def _setup_benchmark_db(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    migrations_dir = str(_DIR / "migrations")
    apply_migrations(conn, migrations_dir)
    _create_benchmark_table(conn)
    return conn


def _ensure_participant(
    conn: sqlite3.Connection, input_text: str | None = None
) -> tuple[str, str]:
    from app import participant_repository as pt_repo
    from app import input_repository as input_repo

    pid = "bench-synthetic-participant"
    existing = pt_repo.get_participant_by_id(conn, pid)
    if existing is None:
        pt_repo.create_participant(
            conn,
            participant_id=pid,
            display_name="Benchmark Synthetic User",
            preferred_language="ko",
        )
    raw_text = input_text or ("benchmark synthetic input text " * 150)
    inp = input_repo.create_input(
        conn,
        participant_id=pid,
        raw_text=raw_text,
        consent_confirmed=1,
    )
    return pid, inp.id


def run_benchmark(
    *,
    fixture_names: list[str] | None = None,
    repeat: int = 1,
    output_path: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    settings = Settings()

    resolved_db = db_path or ":memory:"
    conn = _setup_benchmark_db(resolved_db)

    if fixture_names is None:
        fixture_names = list_bundles()

    results: list[dict[str, Any]] = []
    benchmark_name = f"runtime-benchmark-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

    info: dict[str, str] | None = None
    for fname in fixture_names:
        fixture = load_bundle(fname)
        pid, input_id = _ensure_participant(conn, input_text=fixture.input_text)
        provider = _build_provider(settings, fixture=fixture)
        if info is None:
            info = _provider_info(provider)
        for i in range(repeat):
            print(
                f"  [{fname}] run {i + 1}/{repeat} ... ",
                end="",
                flush=True,
            )
            res = _run_fixture_once(
                provider=provider,
                fixture=fixture,
                db_conn=conn,
                participant_id=pid,
                input_id=input_id,
                run_index=i,
                benchmark_name=benchmark_name,
            )
            status = "OK" if res["success"] else f"FAIL({res['failure_category']})"
            print(
                f"{status}  latency={res['latency_seconds']:.3f}s  "
                f"retries={res['retry_count']}"
            )
            results.append(res)

    conn.close()

    if output_path and info is not None:
        report = {
            "benchmark_name": benchmark_name,
            "provider": info["provider"],
            "advertised_model": info["model"],
            "fixture_count": len(fixture_names),
            "repeat": repeat,
            "total_runs": len(results),
            "results": results,
        }
        Path(output_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nBenchmark report written to {output_path}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Personal Edition runtime benchmark runner"
    )
    parser.add_argument(
        "--fixture",
        action="append",
        dest="fixtures",
        help="Fixture name to run (can be repeated). Default: all fixtures.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to repeat each fixture (default: 1).",
    )
    parser.add_argument(
        "--output",
        help="Path to write the JSON benchmark report.",
    )
    parser.add_argument(
        "--db",
        help="Path to SQLite database for benchmark records (default: in-memory).",
    )
    args = parser.parse_args()

    print("Personal Edition Runtime Benchmark")
    print("=" * 40)
    results = run_benchmark(
        fixture_names=args.fixtures,
        repeat=args.repeat,
        output_path=args.output,
        db_path=args.db,
    )

    successes = sum(1 for r in results if r["success"])
    failures = sum(1 for r in results if not r["success"])
    provider_failures = sum(
        1 for r in results if r.get("failure_category") == "provider"
    )
    model_failures = sum(
        1 for r in results if r.get("failure_category") == "model_quality"
    )

    print("\n" + "=" * 40)
    print(f"Total: {len(results)}  OK: {successes}  FAIL: {failures}")
    print(f"Provider failures: {provider_failures}  Model-quality failures: {model_failures}")
    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
