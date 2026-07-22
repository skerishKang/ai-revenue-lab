"""Tests for the validator-feedback repair benchmark (CTO review 5027501906).

These tests prove:
- the bad (corrupted) candidate deterministically fails validation;
- the repaired candidate passes validation;
- the same provider instance serves both the candidate and repair calls;
- the repair request carries the corrupted candidate, normalized validator
  findings, a repair instruction, a correlation_id and an attempt_id, and
  excludes raw private participant input;
- the candidate and repair provider calls have separate accounting;
- the MockProvider is scripted to return a candidate then a repaired response.
"""

import json
import os
import sys
from pathlib import Path

import pytest

_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _DIR)

from app.db import apply_migrations, get_connection  # noqa: E402
from app.config import Settings  # noqa: E402
from app.ai.mock import MockProvider  # noqa: E402
from app.domain.models import EditionContent  # noqa: E402
from app.pipeline import validators as validators_mod  # noqa: E402
from app.pipeline.fixtures import load_bundle  # noqa: E402
from app.pipeline.service import (  # noqa: E402
    GenerationRequest,
    GenerationService,
    RepairRequest,
)
from app.pipeline.validators import (  # noqa: E402
    normalize_validation_findings,
)
from scripts.benchmark import (  # noqa: E402
    _build_repair_provider,
    _ensure_participant,
    _run_validator_feedback_repair,
    _setup_benchmark_db,
)

MIGRATIONS = str(Path(_DIR) / "migrations")
_INVALID_SEGMENT_ID = "s999"


def _make_provider(fixture, *, repair_payload=None):
    return MockProvider(
        model="mock-personal-edition-v1",
        responses=[
            {"task": "editorial_plan", "kind": "payload", "payload": fixture.plan_payload},
            {"task": "edition_draft", "kind": "payload", "payload": fixture.draft_payload},
            {
                "task": "edition_repair",
                "kind": "payload",
                "payload": repair_payload or fixture.draft_payload,
            },
        ],
    )


def _corrupt(candidate_content: EditionContent):
    data = candidate_content.model_dump()
    data["sections"][0]["source_segment_ids"] = [_INVALID_SEGMENT_ID]
    return EditionContent.model_validate(data)


def test_bad_phase_deterministically_fails():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-badfail", input_text=fixture.input_text)
    provider = _make_provider(fixture)
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    corrupted = _corrupt(candidate.content)
    with pytest.raises(Exception):
        validators_mod.validate_draft(
            corrupted,
            plan=candidate.plan,
            segments=candidate.segments,
            is_follow_up=False,
            feedback_id=None,
        )
    conn.close()


def test_repaired_phase_succeeds():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-repaired", input_text=fixture.input_text)
    provider = _make_provider(fixture)
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    corrupted = _corrupt(candidate.content)
    with pytest.raises(Exception):
        validators_mod.validate_draft(
            corrupted,
            plan=candidate.plan,
            segments=candidate.segments,
            is_follow_up=False,
            feedback_id=None,
        )
    findings = normalize_validation_findings(
        Exception("draft section s0 references unknown segment id")
    )
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    repair_request = RepairRequest(
        participant_id=pid,
        input_id=inp,
        corrupted_candidate=corrupted.model_dump(),
        validator_findings=findings,
        repair_instruction="repair it",
        correlation_id="corr-1",
        attempt_id="attempt-1",
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
    )
    outcome = service.repair_edition(
        conn, repair_request=repair_request, plan=candidate.plan, segments=candidate.segments
    )
    assert outcome.succeeded
    assert outcome.validation_status == "passed"
    conn.close()


def test_same_provider_instance_used():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-sameprov", input_text=fixture.input_text)
    provider = _make_provider(fixture)
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    corrupted = _corrupt(candidate.content)
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    repair_request = RepairRequest(
        participant_id=pid,
        input_id=inp,
        corrupted_candidate=corrupted.model_dump(),
        validator_findings=normalize_validation_findings(Exception("x")),
        repair_instruction="repair it",
        correlation_id="corr-1",
        attempt_id="attempt-1",
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
    )
    service.repair_edition(
        conn, repair_request=repair_request, plan=candidate.plan, segments=candidate.segments
    )
    task_names = [r["task_name"] for r in provider.requests]
    # The same instance handled the candidate (plan + draft) and the repair.
    assert "editorial_plan" in task_names
    assert "edition_draft" in task_names
    assert "edition_repair" in task_names
    assert len(provider.requests) == 3
    conn.close()


def test_repair_request_contains_required_fields():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-reqfields", input_text=fixture.input_text)
    provider = _make_provider(fixture)
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    corrupted = _corrupt(candidate.content)
    findings = normalize_validation_findings(
        Exception("draft section s0 references unknown segment id")
    )
    corr_id, attempt_id = "corr-xyz", "attempt-xyz"
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    repair_request = RepairRequest(
        participant_id=pid,
        input_id=inp,
        corrupted_candidate=corrupted.model_dump(),
        validator_findings=findings,
        repair_instruction="repair it privacy-safely",
        correlation_id=corr_id,
        attempt_id=attempt_id,
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
    )
    service.repair_edition(
        conn, repair_request=repair_request, plan=candidate.plan, segments=candidate.segments
    )
    repair_reqs = [r for r in provider.requests if r["task_name"] == "edition_repair"]
    assert repair_reqs, "no repair request recorded"
    payload = repair_reqs[0]["user_payload"]

    # corrupted candidate present
    assert payload["corrupted_candidate"] == corrupted.model_dump()
    # normalized validator findings present and structured
    assert isinstance(payload["validator_findings"], list)
    assert payload["validator_findings"], "validator findings must be non-empty"
    for f in payload["validator_findings"]:
        assert {"rule", "severity", "message"} <= set(f.keys())
    assert payload["validator_findings"][0]["rule"] == "unknown_segment_reference"
    # instruction + correlation + attempt present
    assert payload["repair_instruction"] == "repair it privacy-safely"
    assert payload["correlation_id"] == corr_id
    assert payload["attempt_id"] == attempt_id
    # excludes raw private participant input
    raw_row = conn.execute(
        "SELECT raw_text FROM inputs WHERE id = ?", (inp,)
    ).fetchone()
    raw_text = raw_row["raw_text"] if raw_row else ""
    dumped = json.dumps(payload, ensure_ascii=False)
    assert raw_text not in dumped
    assert "segments" not in payload
    conn.close()


def test_candidate_and_repair_have_separate_accounting():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-acct", input_text=fixture.input_text)
    provider = _make_provider(fixture)
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    corrupted = _corrupt(candidate.content)
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    repair_request = RepairRequest(
        participant_id=pid,
        input_id=inp,
        corrupted_candidate=corrupted.model_dump(),
        validator_findings=normalize_validation_findings(Exception("x")),
        repair_instruction="repair it",
        correlation_id="corr-1",
        attempt_id="attempt-1",
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
    )
    outcome = service.repair_edition(
        conn, repair_request=repair_request, plan=candidate.plan, segments=candidate.segments
    )
    assert outcome.run_id is not None
    assert outcome.run_id != candidate.plan_outcome.run_id
    assert outcome.run_id != candidate.draft_outcome.run_id
    row = conn.execute(
        "SELECT * FROM generation_runs WHERE id = ?", (outcome.run_id,)
    ).fetchone()
    assert row is not None
    assert row["task_type"] == "edition_repair"
    conn.close()


def test_mock_scripted_candidate_then_repaired_response():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-scripted", input_text=fixture.input_text)
    provider = _make_provider(fixture, repair_payload=fixture.draft_payload)
    service = GenerationService(provider=provider)
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    repair_request = RepairRequest(
        participant_id=pid,
        input_id=inp,
        corrupted_candidate=_corrupt(candidate.content).model_dump(),
        validator_findings=normalize_validation_findings(Exception("x")),
        repair_instruction="repair it",
        correlation_id="corr-1",
        attempt_id="attempt-1",
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
    )
    outcome = service.repair_edition(
        conn, repair_request=repair_request, plan=candidate.plan, segments=candidate.segments
    )
    assert outcome.succeeded
    assert outcome.content is not None
    # The repaired content is a valid EditionContent (scripted draft payload).
    assert outcome.content.edition_title
    conn.close()


def test_end_to_end_repair_benchmark_records_three_phases():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-e2e", input_text=fixture.input_text)
    settings = Settings()
    results = _run_validator_feedback_repair(
        settings=settings,
        fixture=fixture,
        db_conn=conn,
        participant_id=pid,
        input_id=inp,
        run_index=0,
        benchmark_name="bench-e2e-x",
    )
    by_phase = {r["phase"]: r for r in results}
    assert "repair_candidate_generation" in by_phase
    assert "repair_bad_validation" in by_phase
    assert "repair_provider" in by_phase
    assert by_phase["repair_candidate_generation"]["success"] is True
    assert by_phase["repair_candidate_generation"]["validation_result"] == "passed"
    # bad phase must fail validation
    assert by_phase["repair_bad_validation"]["success"] is False
    assert by_phase["repair_bad_validation"]["validation_result"] == "failed"
    # repair phase must pass
    assert by_phase["repair_provider"]["success"] is True
    assert by_phase["repair_provider"]["validation_result"] == "passed"
    # distinct run indexing so accounting cannot be confused
    rows = conn.execute(
        "SELECT task_type, run_index FROM benchmark_runs "
        "WHERE benchmark_name = 'bench-e2e-x' ORDER BY run_index"
    ).fetchall()
    task_types = [r["task_type"] for r in rows]
    assert task_types == [
        "repair_candidate_generation",
        "repair_bad_validation",
        "repair_provider",
    ]
    conn.close()


def test_end_to_end_uses_same_provider_instance():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    pid, inp = _ensure_participant(conn, "bench-e2e-prov", input_text=fixture.input_text)
    settings = Settings()
    shared = _make_provider(fixture)
    import scripts.benchmark as benchmark_mod

    original = benchmark_mod._build_repair_provider
    benchmark_mod._build_repair_provider = lambda s, f: shared
    try:
        benchmark_mod._run_validator_feedback_repair(
            settings=settings,
            fixture=fixture,
            db_conn=conn,
            participant_id=pid,
            input_id=inp,
            run_index=0,
            benchmark_name="bench-e2e-prov-x",
        )
    finally:
        benchmark_mod._build_repair_provider = original
    task_names = [r["task_name"] for r in shared.requests]
    assert "editorial_plan" in task_names
    assert "edition_draft" in task_names
    assert "edition_repair" in task_names
    conn.close()


# ---------------------------------------------------------------------------
# Blocker 1/2/3: shared full validation, persisted accounting, allowed universe
# ---------------------------------------------------------------------------

import copy  # noqa: E402

from app.pipeline.service import VALIDATION_FAILED, VALIDATION_PASSED  # noqa: E402


def _repair_payload_for_first_section(draft_payload, first_segment_id):
    """Return a deep copy of the draft payload with section 0 fixed to the
    supplied (valid) segment id. This is what a correct repair should produce
    after the s999 corruption; callers layer injections on top."""
    data = copy.deepcopy(draft_payload)
    data["sections"][0]["source_segment_ids"] = [first_segment_id]
    return data


def _fixture_allowed_ids(fixture):
    """Authoritative reference universe derived from the fixture's own plan and
    draft: every segment id referenced by the draft and every plan section id."""
    seg = set()
    for s in fixture.draft_payload["sections"]:
        seg.update(s.get("source_segment_ids", []))
    sec = {s["section_id"] for s in fixture.plan_payload["sections"]}
    return tuple(sorted(seg)), tuple(sorted(sec))


def _run_repair_with(
    conn,
    fixture,
    *,
    repair_payload,
    allowed_segment_ids,
    allowed_plan_section_ids,
    participant_tag,
):
    provider = _make_provider(fixture, repair_payload=repair_payload)
    service = GenerationService(provider=provider)
    pid, inp = _ensure_participant(
        conn, participant_tag, input_text=fixture.input_text
    )
    candidate = service.generate_repair_candidate(
        conn,
        request=GenerationRequest(
            participant_id=pid,
            input_id=inp,
            prohibited_inferences=fixture.prohibited_inventions,
            allow_short_sample=True,
        ),
    )
    assert candidate.succeeded
    corrupted = _corrupt(candidate.content)
    repair_request = RepairRequest(
        participant_id=pid,
        input_id=inp,
        corrupted_candidate=corrupted.model_dump(),
        validator_findings=normalize_validation_findings(Exception("x")),
        repair_instruction="repair it privacy-safely",
        correlation_id="corr-1",
        attempt_id="attempt-1",
        prohibited_inferences=fixture.prohibited_inventions,
        allowed_segment_ids=allowed_segment_ids,
        allowed_plan_section_ids=allowed_plan_section_ids,
    )
    outcome = service.repair_edition(
        conn,
        repair_request=repair_request,
        plan=candidate.plan,
        segments=candidate.segments,
    )
    row = None
    if outcome.run_id is not None:
        row = conn.execute(
            "SELECT * FROM generation_runs WHERE id = ?", (outcome.run_id,)
        ).fetchone()
    return outcome, row


def test_repair_fixes_invalid_id_but_introduces_script_fails():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    valid_seg = fixture.draft_payload["sections"][0]["source_segment_ids"][0]
    payload = _repair_payload_for_first_section(fixture.draft_payload, valid_seg)
    payload["edition_title"] = "<script>alert(1)</script>"
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    outcome, row = _run_repair_with(
        conn,
        fixture,
        repair_payload=payload,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
        participant_tag="bench-script-run",
    )
    assert outcome.succeeded is False
    assert outcome.validation_status == VALIDATION_FAILED
    assert row is not None
    assert row["success"] == 0
    assert row["validation_status"] == VALIDATION_FAILED
    conn.close()


def test_repair_fixes_invalid_id_but_introduces_javascript_fails():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    valid_seg = fixture.draft_payload["sections"][0]["source_segment_ids"][0]
    payload = _repair_payload_for_first_section(fixture.draft_payload, valid_seg)
    payload["edition_title"] = "javascript:alert(1)"
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    outcome, row = _run_repair_with(
        conn,
        fixture,
        repair_payload=payload,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
        participant_tag="bench-js-run",
    )
    assert outcome.succeeded is False
    assert outcome.validation_status == VALIDATION_FAILED
    assert row is not None
    assert row["success"] == 0
    assert row["validation_status"] == VALIDATION_FAILED
    conn.close()


def test_repair_fixes_invalid_id_but_introduces_prohibited_invention_fails():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    assert fixture.prohibited_inventions, "fixture must list prohibited inventions"
    valid_seg = fixture.draft_payload["sections"][0]["source_segment_ids"][0]
    payload = _repair_payload_for_first_section(fixture.draft_payload, valid_seg)
    payload["edition_title"] = "invented " + fixture.prohibited_inventions[0]
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    outcome, row = _run_repair_with(
        conn,
        fixture,
        repair_payload=payload,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
        participant_tag="bench-inv-run",
    )
    assert outcome.succeeded is False
    assert outcome.validation_status == VALIDATION_FAILED
    assert row is not None
    assert row["success"] == 0
    assert row["validation_status"] == VALIDATION_FAILED
    conn.close()


def test_repair_valid_repair_with_allowed_ids_succeeds():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    valid_seg = fixture.draft_payload["sections"][0]["source_segment_ids"][0]
    payload = _repair_payload_for_first_section(fixture.draft_payload, valid_seg)
    seg_ids, sec_ids = _fixture_allowed_ids(fixture)
    outcome, row = _run_repair_with(
        conn,
        fixture,
        repair_payload=payload,
        allowed_segment_ids=seg_ids,
        allowed_plan_section_ids=sec_ids,
        participant_tag="bench-valid-run",
    )
    assert outcome.succeeded is True
    assert outcome.validation_status == VALIDATION_PASSED
    assert row is not None
    assert row["success"] == 1
    assert row["validation_status"] == VALIDATION_PASSED
    conn.close()


def test_repair_rejects_invented_segment_id_outside_allowed_universe():
    conn = _setup_benchmark_db(":memory:")
    fixture = load_bundle("korean_founder")
    # The corrupted first section had a unique source segment (s001); the
    # authoritative allowed set deliberately omits it, proving the repair cannot
    # infer it and any reference outside the allowed universe is rejected even
    # when the id is a real, known segment.
    first_seg = fixture.draft_payload["sections"][0]["source_segment_ids"][0]
    other_seg = fixture.draft_payload["sections"][1]["source_segment_ids"][0]
    payload = _repair_payload_for_first_section(fixture.draft_payload, first_seg)
    allowed_segment_ids = (other_seg,)
    allowed_plan_section_ids = tuple(
        sorted(s["section_id"] for s in fixture.plan_payload["sections"])
    )
    outcome, row = _run_repair_with(
        conn,
        fixture,
        repair_payload=payload,
        allowed_segment_ids=allowed_segment_ids,
        allowed_plan_section_ids=allowed_plan_section_ids,
        participant_tag="bench-invented-run",
    )
    assert outcome.succeeded is False
    assert outcome.validation_status == VALIDATION_FAILED
    assert row is not None
    assert row["success"] == 0
    assert row["validation_status"] == VALIDATION_FAILED
    conn.close()


# ---------------------------------------------------------------------------
# CTO review 5028100149 residual gap 1: the allowed reference universe must be
# required and fail closed; an empty set must never skip enforcement.
# ---------------------------------------------------------------------------


def test_repair_request_rejects_empty_allowed_segment_ids():
    """Constructing a RepairRequest without an allowed segment universe fails
    closed rather than silently skipping reference-universe enforcement."""
    fixture = load_bundle("korean_founder")
    _, sec_ids = _fixture_allowed_ids(fixture)
    with pytest.raises(ValueError):
        RepairRequest(
            participant_id="p",
            input_id="i",
            corrupted_candidate={},
            validator_findings=[],
            repair_instruction="repair it",
            correlation_id="c",
            attempt_id="a",
            prohibited_inferences=fixture.prohibited_inventions,
            allowed_segment_ids=(),
            allowed_plan_section_ids=sec_ids,
        )


def test_repair_request_rejects_empty_allowed_plan_section_ids():
    """Constructing a RepairRequest without an allowed plan-section universe
    fails closed rather than silently skipping reference-universe enforcement."""
    fixture = load_bundle("korean_founder")
    seg_ids, _ = _fixture_allowed_ids(fixture)
    with pytest.raises(ValueError):
        RepairRequest(
            participant_id="p",
            input_id="i",
            corrupted_candidate={},
            validator_findings=[],
            repair_instruction="repair it",
            correlation_id="c",
            attempt_id="a",
            prohibited_inferences=fixture.prohibited_inventions,
            allowed_segment_ids=seg_ids,
            allowed_plan_section_ids=(),
        )


def test_repair_request_rejects_both_universes_empty():
    """The default-empty RepairRequest (the previous bypass) now fails closed."""
    fixture = load_bundle("korean_founder")
    with pytest.raises(ValueError):
        RepairRequest(
            participant_id="p",
            input_id="i",
            corrupted_candidate={},
            validator_findings=[],
            repair_instruction="repair it",
            correlation_id="c",
            attempt_id="a",
            prohibited_inferences=fixture.prohibited_inventions,
        )
