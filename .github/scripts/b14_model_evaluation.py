"""Canonical B14 provider/model evaluation harness.

This source slice is intentionally inert: importing it and running its CLI
never constructs a network transport. A caller must inject a transport and
explicitly opt into a live run in a later, separately authorized benchmark.

The harness evaluates the existing synthetic Korean fixture against the five
manual-pin candidates named by #2676. It records bounded metadata and hashes,
never raw prompts or responses. Objective rubric checks are deterministic;
subjective Korean-quality rubrics remain MANUAL_REVIEW_REQUIRED.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from b14_candidate_live_smoke import (  # noqa: E402
    AUTO_MODEL_ID,
    CHAT_PATH,
    CANDIDATE_REGISTRY,
    CandidateSpec,
    MAX_RESPONSE_BYTES,
    resolve_candidate,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "padiem-chat"
    / "tests"
    / "fixtures"
    / "padiem_tier_benchmark_v1.json"
)
EVALUATION_CANDIDATE_IDS = ("agnes", "motif", "mercury", "atria", "luna")
REQUIRED_CASE_IDS = frozenset({
    "KR-CONV-001",
    "KR-REASON-001",
    "KR-INSTR-001",
    "KR-CODE-001",
    "KR-LONG-001",
    "KR-SUMMARY-001",
})
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
MAX_EVALUATION_CASES = 6
NO_NETWORK_TRANSPORT = "LIVE_PROVIDER_CALL=0"
Transport = Callable[[str, str, dict[str, Any] | None], tuple[int, bytes]]


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    category: str
    http_status: int
    response_hash: str
    actual_model: str | None
    fallback_used: bool
    attempt_count: int | None
    latency_ms: int
    objective_checks: dict[str, bool]
    manual_review: tuple[str, ...]
    contract_errors: tuple[str, ...] = ()
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "http_status": self.http_status,
            "response_hash": self.response_hash,
            "actual_model": self.actual_model,
            "fallback_used": self.fallback_used,
            "attempt_count": self.attempt_count,
            "latency_ms": self.latency_ms,
            "objective_checks": self.objective_checks,
            "manual_review": list(self.manual_review),
            "contract_errors": list(self.contract_errors),
            "error_code": self.error_code,
        }


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    """Load and validate the shared synthetic benchmark fixture."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("version") != "padiem-tier-benchmark-v1":
        raise ValueError("fixture_version_unsupported")
    if value.get("provider_calls_authorized") is not False:
        raise ValueError("fixture_provider_calls_must_be_disabled")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != MAX_EVALUATION_CASES:
        raise ValueError("fixture_case_count_invalid")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids):
        raise ValueError("fixture_case_duplicate_or_invalid")
    if set(case_ids) != REQUIRED_CASE_IDS:
        raise ValueError("fixture_case_unknown_or_missing")
    return value


def _bounded_response(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("response_not_object")
    return value


def _content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        return ""
    return message["content"]


def _safe_error_code(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict) and error.get("code") in {"invalid_request", "upstream_error", "no_safe_route"}:
        return str(error["code"])
    return "unknown"


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?。！？]+", text) if part.strip()])


def _objective_checks(case: dict[str, Any], content: str) -> dict[str, bool]:
    """Only checks whose truth is mechanically decidable are scored here."""

    expected = case.get("expected_answer")
    if expected is not None:
        return {"correct_answer": expected.casefold() in content.casefold()}
    if case.get("id") == "KR-INSTR-001":
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return {
            "all_constraints_met": (
                len(lines) == 3
                and all(len(line) <= 12 for line in lines)
                and lines[0].startswith("요약:")
                and "우산" in content
            )
        }
    if case.get("id") == "KR-SUMMARY-001":
        return {
            "two_sentences": _sentence_count(content) == 2,
            "key_facts_preserved": any(
                term in content for term in ("토요일", "전기", "충전", "엘리베이터")
            ),
        }
    return {}


def _manual_rubrics(rubric: Iterable[str], objective: Iterable[str]) -> tuple[str, ...]:
    objective_set = set(objective)
    return tuple(item for item in rubric if item not in objective_set)


def request_body(spec: CandidateSpec, case: dict[str, Any]) -> dict[str, Any]:
    """Build a manual, deterministic request for one fixture case."""

    return {
        "model": spec.model_id,
        "messages": [{"role": "user", "content": case["prompt"]}],
        "temperature": 0,
        "max_tokens": 512,
    }


def evaluate_candidate(
    candidate_id: str,
    transport: Transport,
    *,
    fixture: dict[str, Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Evaluate one explicit candidate with an injected transport."""

    if candidate_id not in EVALUATION_CANDIDATE_IDS:
        raise ValueError("candidate_not_manual_pin")
    spec = resolve_candidate(candidate_id)
    corpus = fixture or load_fixture()
    results: list[CaseResult] = []
    for case in corpus["cases"]:
        started = clock()
        status, raw = transport("POST", CHAT_PATH, request_body(spec, case))
        latency_ms = max(0, int((clock() - started) * 1000))
        response_hash = _hash(raw)
        try:
            payload = _bounded_response(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            results.append(CaseResult(
                case_id=case["id"],
                category=case["category"],
                http_status=status,
                response_hash=response_hash,
                actual_model=None,
                fallback_used=False,
                attempt_count=None,
                latency_ms=latency_ms,
                objective_checks={},
                manual_review=tuple(case["rubric"]),
                contract_errors=("malformed_or_oversized_result",),
                error_code="invalid_json",
            ))
            continue
        meta = payload.get("business14") if isinstance(payload.get("business14"), dict) else {}
        content = _content(payload)
        objective = _objective_checks(case, content)
        actual_model = meta.get("actual_response_model") or payload.get("model")
        fallback_used = meta.get("fallback_used") is True
        attempt_count = meta.get("attempt_count")
        contract_errors: list[str] = []
        if status < 200 or status >= 300:
            contract_errors.append("http_not_success")
        if actual_model != spec.upstream_model:
            contract_errors.append("actual_model_missing_or_mismatch")
        if fallback_used:
            contract_errors.append("silent_fallback")
        if attempt_count != 1:
            contract_errors.append("attempt_count_not_one")
        results.append(CaseResult(
            case_id=case["id"],
            category=case["category"],
            http_status=status,
            response_hash=response_hash,
            actual_model=actual_model,
            fallback_used=fallback_used,
            attempt_count=attempt_count,
            latency_ms=latency_ms,
            objective_checks=objective,
            manual_review=_manual_rubrics(case["rubric"], objective),
            contract_errors=tuple(contract_errors),
            error_code=None if status == 200 else _safe_error_code(payload),
        ))
    # Timing is bounded evidence; raw request/response payloads are never retained.
    objective_total = sum(len(result.objective_checks) for result in results)
    objective_passed = sum(sum(result.objective_checks.values()) for result in results)
    return {
        "candidate_id": spec.candidate_id,
        "tier": spec.tier,
        "provider_id": spec.provider_id,
        "model_id": spec.model_id,
        "upstream_model": spec.upstream_model,
        "fixture_version": corpus["version"],
        "transport": "INJECTED_TRANSPORT",
        "live_provider_call": False,
        "case_count": len(results),
        "objective_total": objective_total,
        "objective_passed": objective_passed,
        "manual_review_required": any(result.manual_review for result in results),
        "status": "FAIL_CLOSED" if any(result.contract_errors for result in results) else "PASS",
        "cases": [result.to_dict() for result in results],
    }


def blocked_reason() -> str:
    return "LIVE_PROVIDER_CALL=0; explicit injected transport required"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in EVALUATION_CANDIDATE_IDS or "--live" not in args:
        print("B14_MODEL_EVALUATION=BLOCKED")
        print(NO_NETWORK_TRANSPORT)
        print("PRODUCTION_MUTATION=0")
        return 0
    print("B14_MODEL_EVALUATION=BLOCKED_TRANSPORT_REQUIRED")
    print(NO_NETWORK_TRANSPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
